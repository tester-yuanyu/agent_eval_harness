"""DeepEval scoring of trusted, independently collected benchmark evidence.

Inspect schedules execution and writes its log. These public DeepEval metrics
own scoring; Langfuse may display their saved outputs but does not rescore them.
The optional G-Eval diagnostic is deliberately excluded from formal verdicts.
"""

from __future__ import annotations

from importlib.metadata import version
from typing import Any

from deepeval.metrics import BaseMetric, ToolCorrectnessMetric
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, ToolCall

from ..oracle import evaluate_oracle as evaluate_oracle
from .diagnostics import diagnostic as _diagnostic
from .executable import ExecutableScorer
from .judge_client import OpenAICompatibleJudge as OpenAICompatibleJudge
from .response import RESPONSE_RUBRIC_VERSION as RESPONSE_RUBRIC_VERSION
from .response import score_response as score_response

METRICS_VERSION = "file-tools-deepeval-v2.3"


class _DeterministicOnlyModel(DeepEvalBaseLLM):
    """Explicitly disable model access in deterministic ToolCorrectness.

    DeepEval 4.2.9 initializes a model even when available_tools is omitted.
    Passing this public custom model avoids credentials and fails closed if a
    future library change tries to introduce an LLM into this formal metric.
    """

    def load_model(self) -> None:
        return None

    def generate(self, *_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("A deterministic metric must not invoke a judge")

    async def a_generate(self, *_args: Any, **_kwargs: Any) -> str:
        raise RuntimeError("A deterministic metric must not invoke a judge")

    def get_model_name(self) -> str:
        return "disabled:deterministic-only"


class _BenchmarkMetric(BaseMetric):
    threshold = 1.0
    async_mode = False
    strict_mode = True
    include_reason = True
    verbose_mode = False
    evaluation_model = "deterministic-file-oracle"

    def measure(self, test_case: LLMTestCase, *args: Any, **kwargs: Any) -> float:
        metadata = test_case.metadata or {}
        task, observation = metadata["task"], metadata["observation"]
        self.score, self.reason = self.evaluate(task, observation)
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(
        self, test_case: LLMTestCase, *args: Any, **kwargs: Any
    ) -> float:
        return self.measure(test_case)

    def evaluate(
        self, task: dict[str, Any], observation: dict[str, Any]
    ) -> tuple[float, str]:
        raise NotImplementedError


class TaskSuccessMetric(_BenchmarkMetric):
    """Recompute the independent oracle from raw file and response evidence."""

    @property
    def __name__(self) -> str:
        return "task_success"

    def evaluate(
        self, task: dict[str, Any], observation: dict[str, Any]
    ) -> tuple[float, str]:
        result = ExecutableScorer().score_observation(task, observation)
        failed = [check["reason"] for check in result["checks"] if not check["passed"]]
        completed = observation.get("status") == "completed"
        if not completed:
            failed.append(
                f"Agent execution ended with status {observation.get('status')!r}"
            )
        return float(result["success"] and completed), "; ".join(
            failed
        ) or "All independent task checks passed"


class DecisionMetric(_BenchmarkMetric):
    def __init__(self, name: str, prefix: str):
        self.name, self.prefix = name, prefix

    @property
    def __name__(self) -> str:
        return self.name

    def evaluate(self, task, observation) -> tuple[float, str]:
        checks = [
            c
            for c in ExecutableScorer().score_observation(task, observation)["checks"]
            if c["name"].startswith(self.prefix)
        ]
        return float(bool(checks) and all(c["passed"] for c in checks)), "; ".join(
            c["reason"] for c in checks
        )


class WorkspacePolicyMetric(_BenchmarkMetric):
    """Critical preservation, unexpected-write and tool-allowlist constraints."""

    @property
    def __name__(self) -> str:
        return "workspace_policy"

    def evaluate(
        self, task: dict[str, Any], observation: dict[str, Any]
    ) -> tuple[float, str]:
        result = ExecutableScorer().score_observation(task, observation)
        violations = list(result["violations"])
        allowed = set(task["allowed_tools"])
        forbidden = sorted(
            {
                event["name"]
                for event in observation["events"]
                if event.get("type") == "tool" and event["name"] not in allowed
            }
        )
        if forbidden:
            violations.append(f"Forbidden tool calls: {', '.join(forbidden)}")
        return float(not violations), "; ".join(
            violations
        ) or "Preservation and tool policy satisfied"


class InteractiveEvidenceMetric(_BenchmarkMetric):
    """Require interaction with the environment without fixing a tool path."""

    @property
    def __name__(self) -> str:
        return "interactive_evidence"

    def evaluate(
        self, task: dict[str, Any], observation: dict[str, Any]
    ) -> tuple[float, str]:
        present = any(event.get("type") == "tool" for event in observation["events"])
        return float(present), (
            "Observed real tool interaction"
            if present
            else "No tool interaction; repeating the requested marker is insufficient"
        )


def _evidence_problem(
    task: dict[str, Any], observation: dict[str, Any]
) -> tuple[str, str] | None:
    """Separate malformed setup and missing measurements from agent failures."""
    if (
        not isinstance(task.get("fixtures"), dict)
        or not isinstance(task.get("oracle"), dict)
        or not task["oracle"]
    ):
        return "INVALID", "Task fixtures and a nonempty oracle are required"
    allowed, required = task.get("allowed_tools"), task.get("required_tools", [])
    if not isinstance(allowed, list) or not isinstance(required, list):
        return "INVALID", "Task tool policy must use lists"
    if not all(isinstance(name, str) for name in allowed + required) or not set(
        required
    ).issubset(allowed):
        return "INVALID", "Required tools must belong to the allowed tool policy"
    if observation.get("status") not in {"completed", "timeout", "error"}:
        return "INVALID", "Unknown execution status"
    errors = observation.get("errors", [])
    if not isinstance(errors, list):
        return "INVALID", "Malformed execution error records"
    if any(
        isinstance(error, dict)
        and error.get("kind") in {"environment", "provider", "harness"}
        for error in errors
    ):
        return (
            "INVALID",
            "Environment, provider, or harness failure prevents a valid agent trial",
        )
    if observation["status"] == "error" and not any(
        isinstance(error, dict) and error.get("kind") == "agent" for error in errors
    ):
        return (
            "INVALID",
            "Unclassified execution error cannot be attributed to the agent",
        )
    completed = observation["status"] == "completed"
    reference = observation.get("execution_kind") == "deterministic_reference_not_agent"
    if completed and not reference and observation.get("evidence_complete") is not True:
        return "INCONCLUSIVE", "Completed execution lacks explicit complete evidence"
    for field in ("before_files", "final_files"):
        value = observation.get(field)
        if not isinstance(value, dict) or not all(
            isinstance(path, str) and isinstance(content, str)
            for path, content in value.items()
        ):
            return "INCONCLUSIVE", f"Missing or malformed {field} evidence"
    if observation["before_files"] != task["fixtures"]:
        return "INVALID", "Initial workspace does not match the frozen task fixtures"
    events, turns = observation.get("events"), observation.get("turns")
    if not isinstance(events, list) or not all(
        isinstance(event, dict) for event in events
    ):
        return "INCONCLUSIVE", "Missing or malformed events evidence"
    for event in events:
        if (
            completed
            and event.get("type") in {"tool", "generation"}
            and event.get("incomplete") is True
        ):
            return (
                "INCONCLUSIVE",
                "Completed execution contains an incomplete critical event",
            )
        if event.get("type") != "tool":
            continue
        if not isinstance(event.get("name"), str) or not isinstance(
            event.get("input"), dict
        ):
            return "INCONCLUSIVE", "Tool event lacks its name or arguments"
        if completed and "output" not in event and not event.get("error"):
            return "INCONCLUSIVE", "Tool event lacks a result or recorded error"
    if not isinstance(turns, list) or not all(
        isinstance(turn, dict) and isinstance(turn.get("output"), str) for turn in turns
    ):
        return "INCONCLUSIVE", "Missing or malformed turns evidence"
    if not turns and observation["status"] == "completed":
        return "INCONCLUSIVE", "Completed execution has no response evidence"
    if task.get("execution_mode") == "decision":
        generations = [
            e for e in events if e.get("type") == "generation" and not e.get("is_judge")
        ]
        if len(generations) != 1 or not isinstance(generations[0].get("output"), dict):
            return "INCONCLUSIVE", "Isolated model decision evidence is missing"
        if not isinstance(generations[0]["output"].get("tool_calls"), list):
            return "INCONCLUSIVE", "Model tool-call decision evidence is missing"
        tools = generations[0].get("input", {}).get("tools")
        if (
            not isinstance(tools, list)
            or not tools
            or not all(
                isinstance(t, dict)
                and isinstance(t.get("function", {}).get("parameters"), dict)
                for t in tools
            )
        ):
            return "INCONCLUSIVE", "Recorded model decision tool schemas are missing"
    expected_inputs = [task["prompt"], *task.get("followups", [])]
    for index, turn in enumerate(turns):
        if index >= len(expected_inputs) or turn.get("input") != expected_inputs[index]:
            return (
                "INVALID",
                "Observed conversation does not match the frozen task inputs",
            )
    return None


def _test_case(task: dict[str, Any], observation: dict[str, Any]) -> LLMTestCase:
    turns = observation.get("turns", [])
    return LLMTestCase(
        name=task["id"],
        input=task["prompt"],
        actual_output=turns[-1]["output"] if turns else "",
        metadata={"task": task, "observation": observation},
        tools_called=[
            ToolCall(
                name=event["name"],
                input_parameters=event["input"],
                output=event.get("output"),
            )
            for event in observation["events"]
            if event.get("type") == "tool"
        ],
        expected_tools=[ToolCall(name=name) for name in task.get("required_tools", [])],
    )


def _metric_record(metric: BaseMetric, *, name: str | None = None) -> dict[str, Any]:
    return {
        "name": name or metric.__name__,
        "score": metric.score,
        "threshold": metric.threshold,
        "success": metric.is_successful(),
        "reason": metric.reason,
        "backend": "deepeval",
        "version": METRICS_VERSION,
        "library_version": version("deepeval"),
        "implementation": type(metric).__name__,
        "formal": not isinstance(metric, ToolCorrectnessMetric),
    }


def score_task(task: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    """Return formal scores without network requests or hosted evaluation.

    An invalid setup/provider call is not an agent failure. Missing evidence is
    inconclusive, not zero. Once evidence is valid, every formal metric must pass;
    there is no average that can conceal a critical workspace policy violation.
    Reference tool-name coverage is diagnostic: an allowed alternative tool path
    must not fail a task whose independently observed final state is correct.
    """
    result: dict[str, Any] = {
        "verdict": "INCONCLUSIVE",
        "validity": "VALID",
        "metrics": [],
        "scoring_backend": "deepeval",
        "metrics_version": METRICS_VERSION,
        "errors": [],
    }
    problem = _evidence_problem(task, observation)
    if problem:
        verdict, reason = problem
        result.update(
            verdict=verdict, validity="INVALID" if verdict == "INVALID" else "VALID"
        )
        result["errors"].append(
            _diagnostic(
                "INVALID_SETUP" if verdict == "INVALID" else "MISSING_EVIDENCE", reason
            )
        )
        return result
    try:
        test_case = _test_case(task, observation)
        metrics: list[BaseMetric] = [TaskSuccessMetric(), WorkspacePolicyMetric()]
        decision_event = None
        if task.get("execution_mode") == "decision":
            decision_event = next(
                e for e in observation["events"] if e["type"] == "generation"
            )
            metrics.append(
                DecisionMetric("decision_call_policy", "decision_call_count")
            )
            if decision_event["output"].get("tool_calls"):
                metrics.extend(
                    [
                        DecisionMetric("decision_tool_selection", "decision_tool:"),
                        DecisionMetric("decision_arguments", "decision_arguments:"),
                        DecisionMetric("decision_schema", "decision_schema:"),
                    ]
                )
        if task.get("required_tools") and task.get("execution_mode") != "decision":
            if observation.get("execution_kind") != "deterministic_reference_not_agent":
                metrics.append(InteractiveEvidenceMetric())
            metrics.append(
                ToolCorrectnessMetric(
                    model=_DeterministicOnlyModel(),
                    eval_mode="llm",
                    threshold=1.0,
                    async_mode=False,
                    should_consider_ordering=False,
                    should_exact_match=False,
                    evaluation_params=[],
                )
            )
        for metric in metrics:
            metric.measure(test_case, _show_indicator=False)
            name = (
                "tool_correctness"
                if isinstance(metric, ToolCorrectnessMetric)
                else None
            )
            record = _metric_record(metric, name=name)
            if isinstance(metric, DecisionMetric):
                record.update(
                    scope="generation", event_id=decision_event["id"], status="SCORED"
                )
            if isinstance(metric, ToolCorrectnessMetric):
                record["semantics"] = (
                    "Reference tool-name coverage; not a unique required execution path"
                )
                record["configuration"] = {
                    "match": "names_only",
                    "consider_order": False,
                    "allow_extra_calls": True,
                }
            result["metrics"].append(record)
        if task.get("evaluation_level") or task.get("checkpoints"):
            from ..trajectory import score_trajectory

            result["metrics"].extend(score_trajectory(task, observation))
            from ..recovery_scoring import score_recovery_policy

            result["metrics"].extend(score_recovery_policy(task, observation))
    except Exception as exc:
        result.update(verdict="INVALID", validity="INVALID", metrics=[])
        result["errors"].append(
            _diagnostic(
                "SCORING_ERROR", f"Metric execution failed: {type(exc).__name__}"
            )
        )
        return result
    formal = [metric for metric in result["metrics"] if metric["formal"]]
    if any(metric.get("success") is False for metric in formal):
        result["verdict"] = "FAIL"
    elif any(
        metric.get("score") is None or metric.get("success") is None
        for metric in formal
    ):
        result["verdict"] = "INCONCLUSIVE"
    else:
        result["verdict"] = "PASS"
    return result
