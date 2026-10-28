"""Inspect owns sample dispatch and scoring; Providers own business resources."""

from __future__ import annotations

import json
import sys
from contextlib import redirect_stdout
from importlib.metadata import version
from pathlib import Path
from typing import Any, NamedTuple

import anyio
from inspect_ai import Epochs, Task
from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import Sample
from inspect_ai.log import transcript
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, ModelOutput
from inspect_ai.scorer import Metric, SampleScore, Score, Scorer, Target, metric, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver

from .diagnostic_metrics import METRIC_ID, evaluate_conversation
from .evaluation_policy import TrialEvaluation, assess_trial
from .inspect_metrics import summarize
from .phase2_schemas import RunStability
from .schemas import CaseResult, DatasetBundle, EvalCase, RunConfig, SummaryStats
from .source_identity import runtime_identity
from .stability import aggregate_stability

ADAPTER_VERSION = "inspect-domain-v3"


def backend_metadata() -> dict[str, Any]:
    """Describe the evaluation implementation for baseline compatibility."""
    return {
        "name": "inspect_ai",
        "version": version("inspect_ai"),
        "adapter_version": ADAPTER_VERSION,
        "scorer": "agent_policy",
        "storage": "inspect-eval-log",
        "cache": False,
        "execution": "solver-provider",
        **runtime_identity(),
    }


def trial_messages(trial: TrialEvaluation) -> list[Any]:
    """Export only actual turns; keep scoring references outside agent state."""
    case, result = trial.case, trial.result
    if result.module_output is not None:
        return [
            ChatMessageUser(content=case.execution.user_input),
            ChatMessageAssistant(
                content=json.dumps(result.module_output, ensure_ascii=False)
            ),
        ]
    messages = []
    inputs = [case.execution.user_input, *case.execution.user_responses]
    for index, turn in enumerate(result.turn_results):
        if index < len(inputs):
            messages.append(ChatMessageUser(content=inputs[index]))
        if turn.get("final_response") is not None:
            messages.append(ChatMessageAssistant(content=turn["final_response"]))
    return messages or [ChatMessageUser(content=case.execution.user_input)]


def domain_score(result: CaseResult) -> Score:
    """Map verdicts without representing unknown numeric scores as zero."""
    passed = (
        result.evaluation_validity == "VALID" and result.quality_conclusion == "PASS"
    )
    return Score(
        value="C" if passed else ("I" if result.quality_conclusion == "FAIL" else "N"),
        explanation=f"{result.evaluation_validity}/{result.quality_conclusion}",
        metadata={
            "score": result.score,
            "quality_conclusion": result.quality_conclusion,
            "evaluation_validity": result.evaluation_validity,
            "execution_status": result.execution_status,
            "cleanup_status": result.cleanup_status,
            "issues": result.evaluation_issues,
            "assertions": [a.model_dump(mode="json") for a in result.assertion_results],
            "judge": result.judge_result.model_dump(mode="json")
            if result.judge_result
            else None,
            "diagnostic_metrics": {
                name: value.model_dump(mode="json")
                for name, value in result.diagnostic_metrics.items()
            },
        },
    )


class ExecutionResults(NamedTuple):
    cases: list[CaseResult]
    artifacts: dict[str, str]
    model_metadata: dict[str, Any]
    summary: SummaryStats
    stability: RunStability


def execute_cases(
    cases: list[EvalCase],
    config: RunConfig,
    provider: Any,
    root: Path,
    *,
    evaluator_run_id: str,
    dataset: DatasetBundle,
    judge_client: Any = None,
    rubric: Any = None,
    conversation_client: Any = None,
) -> ExecutionResults:
    """Execute real Provider trials inside Inspect Solver, then score snapshots.

    Samples carry execution inputs and IDs only. Oracle remains in this trusted
    adapter's private case mapping. Sync Providers run in a joined worker:
    cancellation cannot detach cleanup or manufacture an early success.
    """
    from .runner import _run_case

    by_id = {case.case_id: case for case in cases}
    pending: dict[tuple[str, int], TrialEvaluation] = {}
    results: dict[tuple[str, int], CaseResult] = {}
    model_metadata: dict[str, Any] = {"client_type": "uninitialized"}
    aggregates: dict[str, Any] = {}

    @metric
    def business_metrics() -> Metric:
        def calculate(scores: list[SampleScore]) -> dict[str, float]:
            if len(scores) != len(cases) * config.trials_per_case:
                # Inspect may request live display metrics before completion.
                # A partial denominator is not an authoritative business result.
                return {}
            if aggregates:
                return aggregates["metrics"]
            ordered = [
                results[(c.case_id, epoch)]
                for c in cases
                for epoch in range(1, config.trials_per_case + 1)
            ]
            aggregates["summary"] = summary = summarize(
                ordered, dataset, config.run_mode
            )
            aggregates["stability"] = stability = aggregate_stability(
                ordered, planned_trials=config.trials_per_case,
                performance=summary.performance,
            )
            aggregates["metrics"] = {
                key: value
                for key, value in {
                    "trial_pass_rate": stability.trial_pass_rate,
                    "pass_at_k_rate": stability.pass_at_k_rate,
                    "pass_power_k_rate": stability.pass_power_k_rate,
                    "framework_completion_rate": summary.framework_completion_rate,
                    "strict_assertion_pass_rate": summary.strict_assertion_pass_rate,
                    "average_score": summary.average_score,
                }.items()
                if value is not None
            }
            for name, diagnostic in summary.diagnostic_metrics.items():
                if diagnostic.mean_score is not None:
                    aggregates["metrics"][f"diagnostic.{name}.mean_score"] = (
                        diagnostic.mean_score
                    )
                for status, count in diagnostic.status_counts.items():
                    aggregates["metrics"][f"diagnostic.{name}.{status}"] = count
            return aggregates["metrics"]

        return calculate

    @solver
    def agent_execution() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            case = by_id[str(state.sample_id)]
            collected: list[TrialEvaluation] = []

            def execute() -> tuple[CaseResult, dict[str, Any]]:
                return _run_case(
                    case,
                    config,
                    provider,
                    evaluator_run_id=evaluator_run_id,
                    trial_id=f"trial_{state.epoch:03d}",
                    run_directory=root,
                    pending=collected,
                )

            _, metadata = await anyio.to_thread.run_sync(execute)
            if metadata:
                model_metadata.update(metadata)
            trial = collected[0]
            pending[(case.case_id, state.epoch)] = trial
            state.messages = trial_messages(trial)
            completion = next(
                (m.text for m in reversed(state.messages) if m.role == "assistant"), ""
            )
            state.output = ModelOutput.from_content(
                model="provider", content=completion
            )
            state.metadata.update(
                {
                    "trace_id": trial.result.trace_id,
                    "trial_id": trial.result.trial_id,
                    "evidence_status": trial.result.evidence_status,
                    "cleanup_status": trial.result.cleanup_status,
                }
            )
            if (
                trial.result.evidence_manifest.get("storage_backend")
                == "inspect-eval-log"
            ):
                transcript().info(
                    {
                        "trace_id": trial.result.trace_id,
                        "path": f"evidence/{trial.result.trace_id}/trace.inspect.json",
                        "evidence_status": trial.result.evidence_status,
                        "event_count": len(trial.result.trace_events),
                    },
                    source="business_evidence_reference",
                )
            else:
                for event in trial.result.trace_events:
                    transcript().info(event, source="agent_trace_sdk")
            transcript().info(
                {
                    "tool_calls": trial.result.tool_calls,
                    "before_snapshot": trial.result.before_snapshot,
                    "turn_snapshots": trial.result.turn_snapshots,
                    "system_snapshot": trial.result.system_snapshot,
                },
                source="provider_observation",
            )
            state.completed = True
            return state

        return solve

    @scorer(metrics=[business_metrics()])
    def agent_policy() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            key = (str(state.sample_id), state.epoch)
            trial = pending.pop(key)

            def assess() -> CaseResult:
                return assess_trial(
                    trial, config, provider, judge_client=judge_client, rubric=rubric
                )

            result = await anyio.to_thread.run_sync(assess)
            if conversation_client is not None:
                diagnostic = await evaluate_conversation(
                    trial, result, conversation_client
                )
                result = result.model_copy(update={
                    "diagnostic_metrics": {METRIC_ID: diagnostic},
                })
            results[key] = result
            return domain_score(result)

        return score

    task = Task(
        name="agent_evaluator",
        version=ADAPTER_VERSION,
        dataset=[
            Sample(
                id=c.case_id,
                input=c.execution.user_input,
                target="",
                metadata={"test_scope": c.test_scope},
            )
            for c in cases
        ],
        solver=agent_execution(),
        scorer=agent_policy(),
        epochs=Epochs(config.trials_per_case, []),
        metadata={"evaluation_backend": backend_metadata(), "model_owner": "provider"},
    )
    with redirect_stdout(sys.stderr):
        logs = inspect_eval(
            task,
            model="mockllm/model",
            display="none",
            ctl_server=False,
            notification=False,
            log_dir=str(root / "inspect"),
            log_format="eval",
            max_samples=1,
            fail_on_error=True,
            retry_on_error=0,
            log_realtime=False,
            log_samples=True,
        )
    if len(logs) != 1 or logs[0].status != "success":
        detail = str(logs[0].error) if logs else "no log returned"
        raise RuntimeError(f"Inspect evaluation failed: {detail}")
    expected = [
        (c.case_id, epoch)
        for c in cases
        for epoch in range(1, config.trials_per_case + 1)
    ]
    if set(results) != set(expected) or pending:
        raise RuntimeError("Inspect did not evaluate every planned Trial")
    log_path = Path(logs[0].location).resolve()
    return ExecutionResults(
        cases=[results[key] for key in expected],
        artifacts={"test_run": str(log_path.relative_to(root.resolve()))},
        model_metadata=model_metadata,
        summary=aggregates["summary"],
        stability=aggregates["stability"],
    )
