"""Case-isolated orchestration for one deterministic evaluation run."""

from __future__ import annotations

import hashlib
import tempfile
import warnings
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from agent_trace_sdk import (
    InspectEvidenceSink,
    TraceContext,
    status_for,
)

from .assertions import ASSERTION_REGISTRY_VERSION
from .dataset_validator import validate_dataset
from .evaluation_policy import TrialEvaluation
from .evidence import atomic_json, finish_evidence
from .judge import (
    JudgeClient,
    load_judge_rubric,
    validate_judge_case_spec,
)
from .provider import (
    AdapterOutput,
    EvaluationPreflightError,
    EvaluationProvider,
)
from .schemas import (
    CaseResult,
    DatasetBundle,
    EvaluationRunResult,
    RunConfig,
)

CORE_BEHAVIOR_POLICY_VERSION = "core-behavior-v1"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def run_evaluation(
    dataset: DatasetBundle,
    config: RunConfig,
    provider_or_factory: Any,
    *,
    judge_client: JudgeClient | None = None,
    output_dir: str | Path | None = None,
) -> EvaluationRunResult:
    if isinstance(provider_or_factory, EvaluationProvider):
        provider = provider_or_factory
    else:
        warnings.warn(
            "passing a model-client factory is deprecated; pass an EvaluationProvider",
            DeprecationWarning,
            stacklevel=2,
        )
        from .providers.mini_agent import MiniAgentProvider

        provider = MiniAgentProvider.from_dataset(
            dataset,
            provider_or_factory,
            verify_current=False,
        )
    return run_provider_evaluation(
        dataset,
        config,
        provider,
        judge_client=judge_client,
        output_dir=output_dir,
    )


def run_provider_evaluation(
    dataset: DatasetBundle,
    config: RunConfig,
    provider: EvaluationProvider,
    *,
    judge_client: JudgeClient | None = None,
    output_dir: str | Path | None = None,
) -> EvaluationRunResult:
    if (
        config.run_mode == "agent_benchmark"
        and dataset.lifecycle_state != "FROZEN"
        and not config.allow_non_frozen_dataset
    ):
        raise ValueError(
            "agent_benchmark requires a FROZEN dataset; "
            "use allow_non_frozen_dataset only for provisional runs"
        )
    rubric = None
    judge_metadata = None
    if config.judge is not None and config.judge.enabled:
        if judge_client is None:
            raise EvaluationPreflightError(
                "JUDGE_CLIENT_REQUIRED",
                "Judge client is required when Judge is enabled",
                evidence_path=config.judge.rubric_path,
            )
        if config.run_mode == "agent_benchmark" and dataset.lifecycle_state != "FROZEN":
            raise EvaluationPreflightError(
                "JUDGE_REQUIRES_FROZEN_DATASET",
                "formal Judge evaluation requires a FROZEN dataset",
                evidence_path=dataset.manifest_path,
            )
        try:
            rubric = load_judge_rubric(config.judge.rubric_path)
            rubric_sha256 = hashlib.sha256(
                Path(config.judge.rubric_path).read_bytes()
            ).hexdigest()
        except (OSError, ValueError) as exc:
            raise EvaluationPreflightError(
                "JUDGE_RUBRIC_INVALID",
                str(exc),
                evidence_path=config.judge.rubric_path,
            ) from exc
        judge_metadata = {
            **judge_client.metadata(),
            "prompt_version": rubric.prompt_version,
            "rubric_id": rubric.rubric_id,
            "rubric_version": rubric.version,
            "output_schema_version": rubric.output_schema_version,
            "rubric_sha256": rubric_sha256,
            "timeout_seconds": config.judge.timeout_seconds,
            "max_retries": config.judge.max_retries,
        }
        try:
            for case in dataset.cases:
                if case.oracle.judge is not None:
                    validate_judge_case_spec(case.oracle.judge, rubric)
        except ValueError as exc:
            raise EvaluationPreflightError(
                "JUDGE_RUBRIC_INVALID",
                str(exc),
                evidence_path=config.judge.rubric_path,
            ) from exc
    started_at = _now()
    started = monotonic()
    evaluator_run_id = f"eval_run_{uuid4().hex}"
    if dataset.provider_id not in {"unknown", provider.provider_id}:
        raise EvaluationPreflightError(
            "CAPABILITY_CONTRACT_MISMATCH",
            f"dataset provider {dataset.provider_id!r} != {provider.provider_id!r}",
            evidence_path=dataset.manifest_path,
        )
    validation = validate_dataset(
        dataset,
        capabilities=provider.capabilities,
        tools=provider.tools,
        environment_state_available=getattr(
            provider, "environment_state_available", False
        ),
    )
    if not validation.valid:
        raise EvaluationPreflightError(
            "DATASET_VALIDATION_FAILED",
            "; ".join(item.message for item in validation.issues),
            evidence_path=dataset.path,
        )
    execution_validator = getattr(provider, "validate_execution", None)
    if callable(execution_validator):
        for case in dataset.cases:
            execution_validator(case.execution, case.test_scope)
    from .inspect_engine import backend_metadata, execute_cases

    conversation_client = None
    diagnostic_metadata = {}
    if config.conversation_completeness is not None:
        from .diagnostic_metrics import METRIC_ID
        from .judges.conversation import ConversationMetricClient

        try:
            conversation_client = ConversationMetricClient.from_env(
                config.conversation_completeness
            )
            diagnostic_metadata[METRIC_ID] = conversation_client.metadata()
        except ValueError as exc:
            raise EvaluationPreflightError(
                "DIAGNOSTIC_CONFIGURATION_INVALID", str(exc)
            ) from exc

    execution_type = config.execution_type
    if execution_type == "auto":
        execution_type = (
            "full" if len(dataset.cases) == dataset.total_count else "filtered_subset"
        )
    resolved_config = config.model_copy(update={"execution_type": execution_type})
    root = (
        Path(output_dir)
        if output_dir is not None
        else Path(tempfile.mkdtemp(prefix="agent-evaluation-"))
    ) / evaluator_run_id
    root.mkdir(parents=True, exist_ok=False)
    (root / "evidence").mkdir()
    atomic_json(
        root / "execution.json",
        {
            "evaluator_run_id": evaluator_run_id,
            "started_at": started_at,
        },
    )
    execution = execute_cases(
        dataset.cases,
        resolved_config,
        provider,
        root,
        evaluator_run_id=evaluator_run_id,
        judge_client=judge_client,
        rubric=rubric,
        dataset=dataset,
        conversation_client=conversation_client,
    )
    results = execution.cases
    duration = round((monotonic() - started) * 1000)
    return EvaluationRunResult(
        run_directory=str(root.resolve()),
        evaluator_run_id=evaluator_run_id,
        started_at=started_at,
        finished_at=_now(),
        dataset_path=dataset.path,
        dataset_version=dataset.dataset_version,
        dataset_hash=dataset.sha256,
        dataset_total_cases=dataset.total_count,
        dataset_lifecycle_state=dataset.lifecycle_state,
        dataset_manifest_path=dataset.manifest_path,
        onboarding=deepcopy(dataset.onboarding),
        agent_version=provider.provider_version,
        provider_id=provider.provider_id,
        provider_version=provider.provider_version,
        capability_bundle_sha256=(
            provider.capabilities.bundle.capability_bundle_sha256
        ),
        model_metadata=execution.model_metadata,
        assertion_registry_version=ASSERTION_REGISTRY_VERSION,
        run_config=resolved_config,
        cases=results,
        summary=execution.summary,
        trials_per_case=resolved_config.trials_per_case,
        total_duration_ms=duration,
        stability=execution.stability,
        judge_metadata=judge_metadata,
        diagnostic_metadata=diagnostic_metadata,
        evaluation_backend=backend_metadata(),
        native_artifacts=execution.artifacts,
    )


def _run_case(
    case: Any,
    config: RunConfig,
    provider: EvaluationProvider,
    *,
    evaluator_run_id: str,
    trial_id: str,
    run_directory: Path,
    pending: list[TrialEvaluation] | None = None,
) -> tuple[CaseResult, dict[str, Any] | None]:
    started_at = _now()
    started = monotonic()
    session_id = f"session_{uuid4().hex}"
    runtime = None
    metadata = None
    output = AdapterOutput(None, [], None, [], None)
    execution_status = "COMPLETED"
    exception = None
    cleanup_status = "NOT_STARTED"
    evaluation_issues = []
    sink = None
    context = TraceContext()
    manifest = {"status": "UNAVAILABLE", "issues": []}
    validity = "VALID"
    observed = callable(getattr(provider, "create_observed_runtime", None))
    association = {
        "evaluator_run_id": evaluator_run_id,
        "case_id": case.case_id,
        "trial_id": trial_id,
        "trace_id": context.trace_id,
        "session_id": session_id,
    }
    try:
        if observed:
            directory = run_directory / "evidence" / context.trace_id
            sink = InspectEvidenceSink(
                directory,
                context,
                event_rules_version=getattr(
                    provider, "evidence_rules_version", "events-v1"
                ),
            )
            atomic_json(
                directory / "association.json",
                association,
            )
            runtime = provider.create_observed_runtime(
                case.execution,
                session_id,
                case.test_scope,
                sink,
            )
        else:
            runtime = provider.create_runtime(
                case.execution,
                session_id,
                case.test_scope,
            )
        metadata = provider.runtime_metadata(runtime)
    except Exception as exc:
        execution_status = "INITIALIZATION_ERROR"
        exception = {"type": type(exc).__name__, "message": str(exc)}
        validity = "INVALID"
        evaluation_issues.append({"code": "INITIALIZATION_ERROR"})
        if observed and sink is None:
            manifest = {
                "status": "EXPORT_FAILED",
                "issues": [
                    {"kind": "export", "code": "EVIDENCE_INITIALIZATION_FAILED"}
                ],
            }
    if runtime is not None and execution_status == "COMPLETED":
        try:
            output = (
                provider.run_module(runtime, case.execution)
                if case.test_scope == "module"
                else provider.run_full(runtime, case.execution, case.test_scope)
            )
            elapsed = monotonic() - started
            if elapsed > case.execution.timeout_seconds:
                execution_status = "OUTER_TIMEOUT"
        except Exception as exc:
            execution_status = "AGENT_EXCEPTION"
            exception = {"type": type(exc).__name__, "message": str(exc)}
            try:
                info = provider.classify_exception(exc)
                execution_status = info.execution_status
                exception = info.exception
                if execution_status == "EVALUATOR_ERROR":
                    validity = "INVALID"
                    evaluation_issues.append({"code": "EVALUATOR_EXECUTION_FAILED"})
                if info.output is not None:
                    output = info.output
            except Exception:
                validity = "INVALID"
                evaluation_issues.append({"code": "EXCEPTION_CLASSIFICATION_FAILED"})
    if sink is not None:
        events, manifest = finish_evidence(
            sink,
            execution_completed=execution_status == "COMPLETED",
            association=association,
        )
        try:
            check_evidence = getattr(provider, "evidence_issues", None)
            if callable(check_evidence):
                manifest["issues"].extend(check_evidence(output, events))
            if any(
                t.get("trace_id") not in {None, context.trace_id} for t in output.turns
            ):
                manifest["issues"].append(
                    {
                        "kind": "export",
                        "code": "RESULT_TRACE_ASSOCIATION_MISMATCH",
                    }
                )
        except Exception:
            manifest["issues"].append(
                {"kind": "export", "code": "EVIDENCE_VALIDATION_FAILED"}
            )
        manifest["status"] = status_for(
            manifest["issues"],
            completed=manifest.get("execution_completed", False)
            and manifest.get("collection_closed", False),
        )
        output = replace(
            output,
            trace_events=events,
            evidence_status=manifest["status"],
            execution_completed=execution_status == "COMPLETED",
            evidence_manifest=manifest,
        )
        if manifest["status"] == "EXPORT_FAILED":
            validity = "INVALID"
    observation_available = any(
        check.name == "observations_match"
        and (
            output.snapshot is not None
            if check.config.get("channel", "returned") == "independent"
            else output.observations is not None
        )
        for check in case.oracle.evaluation.checks
    )
    if observation_available and execution_status != "COMPLETED":
        output = replace(output, execution_completed=False)
    assessable = (runtime is not None or sink is not None) and (
        execution_status == "COMPLETED" or sink is not None or observation_available
    )
    try:
        # Metrics run after cleanup; detach observations from runtime-owned data.
        output = deepcopy(output)
    except Exception as exc:
        assessable = False
        validity = "INVALID"
        evaluation_issues.append(
            {"code": "OBSERVATION_SNAPSHOT_FAILED", "type": type(exc).__name__}
        )
    if runtime is not None:
        try:
            provider.cleanup(runtime)
            cleanup_status = "CLEANED"
        except Exception as exc:
            evaluation_issues.append(
                {"code": "CLEANUP_FAILED", "type": type(exc).__name__}
            )
            cleanup_status = "CLEANUP_FAILED"
            validity = "INVALID"
    try:
        tool_version = provider.tool_version(runtime) if runtime else "unavailable"
    except Exception:
        tool_version = "unavailable"
        validity = "INVALID"
        evaluation_issues.append({"code": "TOOL_METADATA_FAILED"})
    latency = round((monotonic() - started) * 1000)
    turns = output.turns
    calls = [call for turn in turns for call in turn.get("tool_calls", [])]
    events = (
        output.trace_events
        if output.trace_events is not None
        else [event for turn in turns for event in turn.get("events", [])]
    )
    if not observed:
        manifest = {
            "status": "PARTIAL" if events else "UNAVAILABLE",
            "source": "legacy_embedded_trace",
            "issues": (
                [{"kind": "partial", "code": "LEGACY_COMPLETENESS_UNKNOWN"}]
                if events
                else []
            ),
        }
    case_result = CaseResult(
        execution_started_at=started_at,
        execution_finished_at=_now(),
        trace_id=context.trace_id if observed else None,
        evidence_status=manifest["status"],
        evidence_manifest=manifest,
        evaluation_validity=validity,
        evaluation_issues=manifest["issues"] + evaluation_issues,
        evaluator_run_id=evaluator_run_id,
        case_id=case.case_id,
        task_id=case.task_id,
        scenario_type=case.scenario_type,
        test_scope=case.test_scope,
        user_input=case.execution.user_input,
        trial_id=trial_id,
        run_mode=config.run_mode,
        tool_profile=case.execution.tool_profile,
        tool_version=tool_version,
        max_steps=case.execution.max_steps,
        timeout_seconds=case.execution.timeout_seconds,
        session_id=None if case.test_scope == "module" else session_id,
        agent_run_ids=list(
            dict.fromkeys(
                [turn["run_id"] for turn in turns]
                + [e["run_id"] for e in events if e.get("run_id")]
            )
        ),
        execution_status=execution_status,
        quality_conclusion="INCONCLUSIVE",
        score=None,
        module_output=output.module_output,
        observations=output.observations,
        turn_results=turns,
        tool_calls=calls,
        trace_events=events,
        turn_snapshots=output.turn_snapshots,
        before_snapshot=output.before_snapshot,
        system_snapshot=output.snapshot,
        assertion_results=[],
        first_failed_assertion=None,
        latency_ms=latency,
        evidence_refs=[],
        cleanup_status=cleanup_status,
        exception=exception,
        labels=case.labels,
    )
    trial = TrialEvaluation(case, case_result, output, assessable)
    if pending is not None:
        pending.append(trial)
    else:
        from .evaluation_policy import assess_trial

        case_result = assess_trial(trial, config, provider)
    return case_result, metadata
