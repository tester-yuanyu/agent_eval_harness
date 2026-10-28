"""Export immutable results via Langfuse's SDK; never execute or score here."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from langfuse.api import (
    CreateScoreRequest,
    OtelAttribute,
    OtelAttributeValue,
    OtelResourceSpan,
    OtelScope,
    OtelScopeSpan,
    OtelSpan,
)
from langfuse.api.client import LangfuseAPI

from .evidence import atomic_json
from .result_loader import load_run_result

EXPORT_VERSION = "langfuse-export-v1"
RECEIPT = "langfuse_export.json"


def destination_fingerprint() -> str:
    """Project identity without persisting credentials; injected clients are tests."""
    return stable_id(
        os.getenv("LANGFUSE_BASE_URL", "injected-client").rstrip("/"),
        os.getenv("LANGFUSE_PUBLIC_KEY", "injected-client"),
    )


def stable_id(*parts: str, length: int = 32) -> str:
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:length]


def client_from_env() -> LangfuseAPI:
    values = {
        key: os.getenv(key, "").strip()
        for key in ("LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    }
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise ValueError("Missing local configuration: " + ", ".join(missing))
    return LangfuseAPI(
        base_url=values["LANGFUSE_BASE_URL"].rstrip("/"),
        username=values["LANGFUSE_PUBLIC_KEY"],
        password=values["LANGFUSE_SECRET_KEY"],
        headers={"x-langfuse-ingestion-version": "4"},
        timeout=30,
        follow_redirects=False,
    )


def _nanos(value: str) -> str:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("Observation timestamp must include a timezone")
    delta = instant.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return str((delta.days * 86400 + delta.seconds) * 10**9 + delta.microseconds * 1000)


def _span(
    trace_id: str,
    span_id: str,
    name: str,
    start: str,
    end: str,
    attributes: dict[str, Any],
    parent: str | None = None,
) -> OtelSpan:
    return OtelSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent,
        name=name,
        kind=1,
        start_time_unix_nano=_nanos(start),
        end_time_unix_nano=_nanos(end),
        attributes=[
            OtelAttribute(
                key=key,
                value=OtelAttributeValue(
                    string_value=value if isinstance(value, str) else json.dumps(value)
                ),
            )
            for key, value in attributes.items()
        ],
    )


def export_run(
    run_dir: str | Path,
    *,
    include_content: bool = False,
    client: LangfuseAPI | None = None,
    target_identity: str | None = None,
    receipt_path: str | Path | None = None,
    expected_results_sha256: str | None = None,
    refresh_scores: bool = True,
) -> dict[str, Any]:
    """Explicit, replayable export. ACCEPTED means ingestion, not UI verification."""
    root = Path(run_dir).expanduser().resolve()
    loaded = load_run_result(root)
    if expected_results_sha256 is not None and loaded.sha256 != expected_results_sha256:
        raise ValueError("Export source changed during delivery")
    run = loaded.result
    path = Path(receipt_path).resolve() if receipt_path else root / RECEIPT
    path.parent.mkdir(parents=True, exist_ok=True)
    destination = target_identity or destination_fingerprint()
    previous: dict[str, Any] = {}
    if path.exists():
        previous = json.loads(path.read_text())
        if previous["results_sha256"] != loaded.sha256:
            raise ValueError("Export source must remain immutable")
        if previous["include_content"] != include_content:
            raise ValueError("Export content mode must remain immutable")
        if previous["destination"] != destination:
            raise ValueError("Export destination must match the original project")
        if previous.get("inflight_observation_ids"):
            raise ValueError(
                "Observation acceptance is uncertain; reconcile the recorded "
                "inflight IDs with Langfuse before resuming. Do not resend blindly."
            )
        if (
            previous["status"] != "ACCEPTED"
            and "accepted_observation_ids" not in previous
        ):
            raise ValueError(
                "Legacy partial export has no observation checkpoint; reconcile "
                "Langfuse observations before resuming."
            )
    client = client or client_from_env()
    experiment_id = stable_id(EXPORT_VERSION, run.evaluator_run_id)
    spans: list[OtelSpan] = []
    scores: list[CreateScoreRequest] = []
    trials: list[dict[str, str]] = []
    omitted_events: list[dict[str, str]] = []
    common = {
        "run_id": run.evaluator_run_id,
        "results_sha256": loaded.sha256,
        "dataset_hash": run.dataset_hash,
        "agent_version": run.agent_version,
        "provider_id": run.provider_id,
        "compiled_suite_sha256": run.compiled_suite_sha256,
        "formal_score_owner": "Inspect AI",
        "diagnostic_metadata": run.diagnostic_metadata,
        "export_version": EXPORT_VERSION,
    }

    def add_score(
        trace_id: str,
        observation_id: str,
        name: str,
        value: str | float | None,
        *,
        evidence_refs: list[str] | None = None,
    ) -> None:
        if value is None:
            return
        scores.append(
            CreateScoreRequest(
                id=stable_id(EXPORT_VERSION, trace_id, name),
                trace_id=trace_id,
                observation_id=observation_id,
                name=name,
                value=value,
                data_type="CATEGORICAL" if isinstance(value, str) else "NUMERIC",
                timestamp=datetime.fromisoformat(
                    run.finished_at.replace("Z", "+00:00")
                ),
                metadata={
                    **common,
                    "evidence_refs": evidence_refs or [],
                    "authority": "immutable_results",
                },
            )
        )

    for case in run.cases:
        trace_id = stable_id(
            EXPORT_VERSION, run.evaluator_run_id, case.case_id, case.trial_id
        )
        observation_id = stable_id(trace_id, "root", length=16)
        trials.append(
            {
                "case_id": case.case_id,
                "trial_id": case.trial_id,
                "scenario_type": case.scenario_type,
                "test_scope": case.test_scope,
                "task_id": case.task_id,
                "trace_id": trace_id,
                "observation_id": observation_id,
            }
        )
        attrs: dict[str, Any] = {
            "langfuse.observation.type": "agent",
            "langfuse.observation.metadata": {
                **common,
                "case_id": case.case_id,
                "trial_id": case.trial_id,
                "scenario_type": case.scenario_type,
                "test_scope": case.test_scope,
                "task_id": case.task_id,
                "execution_status": case.execution_status,
                "evaluation_validity": case.evaluation_validity,
                "quality_conclusion": case.quality_conclusion,
                "evidence_trace_id": case.trace_id,
                "timing_source": "trial" if case.execution_started_at else "run_bounds",
                "trial_latency_ms": case.latency_ms,
            },
            "langfuse.experiment.id": experiment_id,
            "langfuse.experiment.name": run.evaluator_run_id,
            "langfuse.experiment.metadata": common,
            "langfuse.experiment.item.id": stable_id(
                run.dataset_hash, case.case_id, case.trial_id
            ),
            "langfuse.experiment.item.metadata": {
                "case_id": case.case_id,
                "trial_id": case.trial_id,
            },
            "langfuse.experiment.item.root_observation_id": observation_id,
        }
        if include_content:
            attrs["langfuse.observation.input"] = case.user_input
            attrs["langfuse.observation.output"] = (
                case.turn_results[-1].get("final_response", "")
                if case.turn_results
                else case.module_output
            )
        spans.append(
            _span(
                trace_id,
                observation_id,
                case.case_id,
                case.execution_started_at or run.started_at,
                case.execution_finished_at or run.finished_at,
                attrs,
            )
        )
        # Evidence events are points, not fabricated LLM/tool durations.
        evidence_observations = {}
        for index, event in enumerate(case.trace_events):
            timestamp = event.get("timestamp")
            event_id = str(event.get("event_id", index))
            try:
                _nanos(timestamp)
            except (ValueError, TypeError, AttributeError):
                omitted_events.append(
                    {
                        "trace_id": trace_id,
                        "event_id": event_id,
                        "reason": "missing_or_invalid_timestamp",
                    }
                )
                continue
            event_span = stable_id(trace_id, event_id, str(index), length=16)
            evidence_observations.setdefault(f"event:{event_id}", []).append(event_span)
            event_attrs = {
                "langfuse.observation.type": "event",
                "langfuse.observation.metadata": {
                    "evidence_event_id": event_id,
                    "results_sha256": loaded.sha256,
                },
            }
            spans.append(
                _span(
                    trace_id,
                    event_span,
                    str(event.get("event_type", "evidence")),
                    timestamp,
                    timestamp,
                    event_attrs,
                    observation_id,
                )
            )
        # A categorical source label enables native coverage charts, including for
        # already-ingested immutable observations. It is not a quality judgment.
        add_score(trace_id, observation_id, "context.scenario_type", case.scenario_type)
        for name, value in {
            "execution.status": case.execution_status,
            "evaluation.validity": case.evaluation_validity,
            "quality.conclusion": case.quality_conclusion,
            "quality.deterministic_score": (
                case.score if case.evaluation_validity == "VALID" else None
            ),
            "execution.latency_ms": case.latency_ms,
        }.items():
            add_score(
                trace_id, observation_id, name, value, evidence_refs=case.evidence_refs
            )
        for index, assertion in enumerate(case.assertion_results):
            # A contract can apply the same assertion to different tools/turns.
            # Preserve distinct scores, including their original name in metadata.
            add_score(
                trace_id,
                observation_id,
                f"assertion.{index}.{assertion.name}",
                "UNKNOWN"
                if assertion.passed is None
                else ("PASS" if assertion.passed else "FAIL"),
                evidence_refs=assertion.evidence_refs,
            )
        for name, diagnostic in case.diagnostic_metrics.items():
            prefix = f"diagnostic.{name}"
            add_score(trace_id, observation_id, f"{prefix}.status", diagnostic.status)
            add_score(trace_id, observation_id, f"{prefix}.score", diagnostic.score)
        if case.judge_result:
            add_score(
                trace_id, observation_id, "judge.status", case.judge_result.status
            )
            if case.evaluation_validity == "VALID":
                add_score(
                    trace_id, observation_id, "judge.score", case.judge_result.score
                )
                for dimension in case.judge_result.dimensions:
                    add_score(
                        trace_id,
                        observation_id,
                        f"judge.{dimension.name}",
                        dimension.score,
                        evidence_refs=dimension.evidence_refs,
                    )
        for score in scores:
            if score.trace_id == trace_id and score.metadata is not None:
                score.metadata["evidence_observations"] = {
                    ref: evidence_observations[ref]
                    for ref in score.metadata["evidence_refs"]
                    if ref in evidence_observations
                }

    summary_trace = stable_id(EXPORT_VERSION, run.evaluator_run_id, "summary")
    summary_span = stable_id(summary_trace, "root", length=16)
    spans.append(
        _span(
            summary_trace,
            summary_span,
            "evaluation_summary",
            run.started_at,
            run.finished_at,
            {
                "langfuse.observation.type": "evaluator",
                "langfuse.observation.metadata": {**common, "role": "run_summary"},
            },
        )
    )
    # Only scalar snapshots; never recalculate rates from traces in this adapter.
    for prefix, model in (("run", run.summary), ("stability", run.stability)):
        if model is not None:
            for key, value in model.model_dump().items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    add_score(summary_trace, summary_span, f"{prefix}.{key}", value)

    for name, diagnostic in run.summary.diagnostic_metrics.items():
        prefix = f"diagnostic.{name}"
        add_score(
            summary_trace, summary_span, f"{prefix}.mean_score", diagnostic.mean_score
        )
        add_score(
            summary_trace, summary_span, f"{prefix}.scored_trials",
            diagnostic.scored_trials,
        )
        for status, count in diagnostic.status_counts.items():
            add_score(summary_trace, summary_span, f"{prefix}.{status}", count)

    # Explicit exports retain their historical successful-score refresh behavior.
    # Partial deliveries always resume confirmed batches. Automatic delivery opts
    # out of refreshing already-complete scores so its time budget can progress.
    accepted_scores = previous.get(
        "accepted_score_ids",
        previous.get("score_ids", []) if previous.get("status") == "ACCEPTED" else [],
    )
    if refresh_scores and previous.get("status") == "ACCEPTED":
        accepted_scores = []
    receipt = {
        "version": EXPORT_VERSION,
        "status": "PENDING",
        "destination": destination,
        "results_sha256": loaded.sha256,
        "include_content": include_content,
        "experiment_id": experiment_id,
        "trials": trials,
        "summary_trace_id": summary_trace,
        "omitted_events": omitted_events,
        "score_ids": [score.id for score in scores],
        "accepted_score_ids": list(accepted_scores),
        "accepted_observation_ids": (
            [span.span_id for span in spans]
            if previous.get("status") == "ACCEPTED"
            else previous.get("accepted_observation_ids", [])
        ),
        "inflight_observation_ids": [],
    }

    def save_receipt() -> None:
        atomic_json(path, receipt)

    # Bind identity before the first request, including interrupted/partial uploads.
    save_receipt()
    # Langfuse v4 does not deduplicate immutable observations by ID. Scores
    # support upserts; confirmed observations must never be sent again.
    accepted = set(receipt["accepted_observation_ids"])
    pending_spans = [span for span in spans if span.span_id not in accepted]
    for offset in range(0, len(pending_spans), 100):
        batch = pending_spans[offset : offset + 100]
        receipt["inflight_observation_ids"] = [span.span_id for span in batch]
        save_receipt()
        try:
            response = client.opentelemetry.export_traces(
                resource_spans=[
                    OtelResourceSpan(
                        scope_spans=[
                            OtelScopeSpan(
                                scope=OtelScope(name="agent_evaluator"),
                                spans=batch,
                            )
                        ]
                    )
                ],
                request_options={"max_retries": 0},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # No connection was established, so nothing could have been accepted.
            receipt["inflight_observation_ids"] = []
            save_receipt()
            raise
        partial = response.model_dump(by_alias=True).get("partialSuccess")
        if partial and (partial.get("rejectedSpans") or partial.get("errorMessage")):
            raise ValueError(
                "Langfuse rejected observations; reconcile before resuming"
            )
        receipt["accepted_observation_ids"].extend(receipt["inflight_observation_ids"])
        receipt["inflight_observation_ids"] = []
        save_receipt()
    confirmed_scores = set(receipt["accepted_score_ids"])
    pending_scores = [score for score in scores if score.id not in confirmed_scores]
    for offset in range(0, len(pending_scores), 100):
        batch = pending_scores[offset : offset + 100]
        response = client.scores.create(
            request=batch,
            request_options={"max_retries": 0},
        )
        if (
            getattr(response, "rejected", 0)
            or getattr(response, "errors", [])
            or getattr(response, "accepted", len(batch)) != len(batch)
        ):
            raise ValueError("Langfuse rejected scores; retry after correction")
        # Scores are stable-ID upserts, so an uncertain/partial batch is safe to
        # retry as a whole. Only an entirely confirmed batch advances the cursor.
        receipt["accepted_score_ids"].extend(score.id for score in batch)
        save_receipt()
    receipt["status"] = "ACCEPTED"
    save_receipt()
    return receipt
