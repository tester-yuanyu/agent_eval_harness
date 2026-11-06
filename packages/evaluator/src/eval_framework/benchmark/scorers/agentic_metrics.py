"""通过 DeepEval 公共 tracing API 回放已保存的 Agent 证据。"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import os
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable
from importlib.metadata import version
from pathlib import Path
from typing import Any

from deepeval.dataset import EvaluationDataset, Golden
from deepeval.evaluate.configs import (
    AsyncConfig,
    CacheConfig,
    DisplayConfig,
    ErrorConfig,
)
from deepeval.metrics import (
    ArgumentCorrectnessMetric,
    StepEfficiencyMetric,
    TaskCompletionMetric,
)
from deepeval.test_case import ToolCall
from deepeval.tracing import observe, update_current_span, update_current_trace

NATIVE_METRICS_VERSION = "trajectory-native-v1"
NATIVE_DIMENSIONS = (
    "step_efficiency",
    "task_completion",
    "argument_correctness",
)
_REQUESTS_PER_METRIC = 2
_PUBLIC_EVENT_FIELDS = (
    "id",
    "type",
    "parent_id",
    "turn",
    "name",
    "input",
    "normalized_input",
    "output",
    "error",
    "snapshot",
    "incomplete",
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _requests(task: dict[str, Any]) -> list[str]:
    return [task.get("prompt", ""), *task.get("followups", [])]


def _public_event(event: dict[str, Any]) -> dict[str, Any]:
    return {key: event[key] for key in _PUBLIC_EVENT_FIELDS if key in event}


def _events_by_turn(observation: dict[str, Any]) -> list[tuple[dict, list[dict]]]:
    events = observation.get("events", [])
    turns = []
    summaries = observation.get("turns", [])
    for index, event in enumerate(
        event for event in events if event.get("type") == "turn"
    ):
        turn = dict(event)
        if index < len(summaries) and "snapshot" not in turn:
            turn["snapshot"] = summaries[index].get("snapshot")
        turns.append(turn)
    children: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        parent_id = event.get("parent_id")
        if isinstance(parent_id, str):
            children[parent_id].append(event)
    return [(turn, children.get(turn["id"], [])) for turn in turns]


def _trace_problem(observation: dict[str, Any]) -> str | None:
    if observation.get("evidence_complete") is not True:
        return "Saved execution does not declare complete evidence."
    events = observation.get("events")
    turns = observation.get("turns")
    if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
        return "Saved execution has no complete event list."
    if not isinstance(turns, list) or not all(isinstance(t, dict) for t in turns):
        return "Saved execution has no complete turn list."
    ids = [event.get("id") for event in events]
    if any(not isinstance(value, str) or not value for value in ids):
        return "Saved events require nonempty IDs."
    if len(ids) != len(set(ids)):
        return "Saved event IDs are not unique."
    turn_events = [event for event in events if event.get("type") == "turn"]
    if len(turn_events) != len(turns):
        return "Saved turn summaries and turn events are not aligned."
    turn_ids = {event["id"] for event in turn_events}
    turn_numbers = {
        event["id"]: index for index, event in enumerate(turn_events, start=1)
    }
    for index, (event, summary) in enumerate(
        zip(turn_events, turns, strict=True), start=1
    ):
        if event.get("turn", index) != index:
            return "Saved turn numbering does not match event order."
        if not isinstance(summary.get("input"), str) or not isinstance(
            summary.get("output"), str
        ):
            return "Saved turn summary lacks its input or output."
        if (
            event.get("input") != summary["input"]
            or event.get("output") != summary["output"]
        ):
            return "Saved turn summaries do not match turn events."
        if (
            event.get("snapshot") is not None
            and summary.get("snapshot") is not None
            and event["snapshot"] != summary["snapshot"]
        ):
            return "Saved turn snapshots do not match turn events."
    for event in events:
        if event.get("incomplete") is True:
            return f"Saved event {event['id']} is incomplete."
        kind = event.get("type")
        if kind not in {"turn", "tool", "generation"}:
            continue
        if kind != "turn":
            parent_id = event.get("parent_id")
            if parent_id not in turn_ids:
                return f"Saved event {event['id']} is not attached to a turn."
            expected_turn = turn_numbers[parent_id]
            if event.get("turn", expected_turn) != expected_turn:
                return f"Saved event {event['id']} has inconsistent turn numbering."
        if kind == "tool":
            if not isinstance(event.get("name"), str) or not isinstance(
                event.get("input"), dict
            ):
                return f"Saved tool event {event['id']} lacks name or arguments."
            if "output" not in event and not event.get("error"):
                return f"Saved tool event {event['id']} lacks a result."
        if kind == "generation" and ("input" not in event or "output" not in event):
            return f"Saved generation event {event['id']} is incomplete."
        if kind == "turn" and (
            not isinstance(event.get("input"), str)
            or not isinstance(event.get("output"), str)
        ):
            return f"Saved turn event {event['id']} is incomplete."
    return None


def _span_output(event: dict[str, Any]) -> Any:
    if not event.get("error"):
        return event.get("output")
    return {"output": event.get("output"), "recorded_error": event["error"]}


@observe(type="tool")
def _replay_tool(event: dict[str, Any]) -> Any:
    output = _span_output(event)
    update_current_span(
        name=event.get("name") or "recorded_tool",
        input=event.get("normalized_input", event.get("input")),
        output=output,
        metadata={"evidence_id": event["id"], "saved_evidence_replay": True},
    )
    return output


@observe(type="llm")
def _replay_generation(event: dict[str, Any]) -> Any:
    output = _span_output(event)
    update_current_span(
        name="recorded_generation",
        input=event.get("input"),
        output=output,
        metadata={"evidence_id": event["id"], "saved_evidence_replay": True},
    )
    return output


@observe(type="agent")
def _replay_turn(
    turn: dict[str, Any],
    children: list[dict[str, Any]],
    requests: list[str],
    index: int,
    prior_turns: list[dict[str, Any]],
    argument_metric: ArgumentCorrectnessMetric | None,
) -> dict[str, Any]:
    tool_events = [event for event in children if event.get("type") == "tool"]
    tools_called = [
        ToolCall(
            name=event["name"],
            input_parameters=event.get("normalized_input", event["input"]),
            output=_span_output(event),
        )
        for event in tool_events
    ]
    output = {
        "response": turn.get("output"),
        "workspace_snapshot": turn.get("snapshot"),
    }
    span_update: dict[str, Any] = {
        "name": f"recorded_turn_{index + 1}",
        "input": {
            "requests_so_far": requests[: index + 1],
            "prior_observed_turns": prior_turns,
        },
        "output": output,
        "metadata": {
            "evidence_id": turn["id"],
            "saved_evidence_replay": True,
        },
    }
    if tools_called:
        span_update["tools_called"] = tools_called
    if argument_metric is not None:
        span_update["metrics"] = [argument_metric]
    update_current_span(**span_update)
    for child in children:
        if child.get("type") == "tool":
            _replay_tool(child)
        elif child.get("type") == "generation":
            _replay_generation(child)
    return output


@observe(type="agent")
def _replay_saved_execution(
    task: dict[str, Any],
    observation: dict[str, Any],
    argument_metric: ArgumentCorrectnessMetric | None = None,
    argument_event_id: str | None = None,
) -> dict[str, Any]:
    requests = _requests(task)
    output = {
        "status": observation.get("status"),
        "last_response": (
            observation.get("turns", [])[-1].get("output")
            if observation.get("turns")
            else None
        ),
        "final_files": observation.get("final_files"),
    }
    update_current_span(
        name="recorded_agent_execution",
        input={"requests": requests},
        output=output,
        metadata={"task_id": task.get("id"), "saved_evidence_replay": True},
    )
    update_current_trace(
        name="recorded_agent_execution",
        input={"requests": requests},
        output=output,
        metadata={"task_id": task.get("id"), "saved_evidence_replay": True},
    )
    prior_turns = []
    for index, (turn, children) in enumerate(_events_by_turn(observation)):
        metric = argument_metric if turn["id"] == argument_event_id else None
        _replay_turn(turn, children, requests, index, list(prior_turns), metric)
        prior_turns.append(
            {
                "request": turn.get("input"),
                "response": turn.get("output"),
                "workspace_snapshot": turn.get("snapshot"),
            }
        )
    return output


def _measure(
    task: dict[str, Any],
    observation: dict[str, Any],
    metric: Any,
    *,
    work_dir: Path,
    argument_event_id: str | None = None,
) -> None:
    dataset = EvaluationDataset(
        goldens=[Golden(input=task.get("prompt", ""), name=task.get("id"))]
    )
    trace_metrics = None if argument_event_id is not None else [metric]
    display = DisplayConfig(
        show_indicator=False,
        print_results=False,
        inspect_after_run=False,
        results_folder=str(work_dir / "results"),
    )
    previous = Path.cwd()
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chdir(work_dir)
        with contextlib.redirect_stdout(io.StringIO()):
            for _golden in dataset.evals_iterator(
                metrics=trace_metrics,
                display_config=display,
                cache_config=CacheConfig(write_cache=False, use_cache=False),
                error_config=ErrorConfig(
                    ignore_errors=False, skip_on_missing_params=False
                ),
                async_config=AsyncConfig(run_async=False),
            ):
                _replay_saved_execution(
                    task,
                    observation,
                    argument_metric=metric if argument_event_id is not None else None,
                    argument_event_id=argument_event_id,
                )
    finally:
        os.chdir(previous)


def _call_events(calls: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    events = []
    for call in calls:
        events.append(
            {
                "type": call.get("type", "generation"),
                "name": call.get("name", "deepeval_native_judge"),
                "model": call.get("model"),
                "start_time": call.get("start_time"),
                "end_time": call.get("end_time"),
                "input": call.get("input"),
                "output": call.get("output"),
                "error": call.get("error"),
                "usage": call.get(
                    "usage",
                    {
                        "input_tokens": None,
                        "output_tokens": None,
                        "cost_usd": None,
                    },
                ),
            }
        )
    return events


def _record(
    task: dict[str, Any],
    name: str,
    *,
    implementation: str,
    scope: str,
    event_id: str | None,
    evidence_ids: list[str],
    status: str = "MISSING",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "metric_id": _digest([task.get("id"), NATIVE_METRICS_VERSION, name, event_id])[
            :24
        ],
        "name": name,
        "backend": "deepeval",
        "library_version": version("deepeval"),
        "version": NATIVE_METRICS_VERSION,
        "implementation": implementation,
        "scope": scope,
        "event_id": event_id,
        "evidence_ids": evidence_ids,
        "score": None,
        "success": None,
        "threshold": None,
        "formal": False,
        "calibration": "not_calibrated",
        "status": status,
        "reason": reason,
        "events": [],
        "errors": [],
    }


def _record_specs(
    task: dict[str, Any], observation: dict[str, Any], dimensions: list[str]
) -> list[tuple[dict[str, Any], str | None]]:
    events = observation.get("events", [])
    ids = [event.get("id") for event in events if isinstance(event.get("id"), str)]
    specs: list[tuple[dict[str, Any], str | None]] = []
    if "step_efficiency" in dimensions:
        specs.append(
            (
                _record(
                    task,
                    "step_efficiency",
                    implementation="StepEfficiencyMetric",
                    scope="chain",
                    event_id=None,
                    evidence_ids=ids,
                ),
                None,
            )
        )
    if "task_completion" in dimensions:
        specs.append(
            (
                _record(
                    task,
                    "task_completion",
                    implementation="TaskCompletionMetric",
                    scope="task",
                    event_id=None,
                    evidence_ids=ids,
                ),
                None,
            )
        )
    if "argument_correctness" in dimensions:
        for turn, children in _events_by_turn(observation):
            tools = [event for event in children if event.get("type") == "tool"]
            if not tools:
                continue
            evidence_ids = [turn["id"], *[event["id"] for event in tools]]
            specs.append(
                (
                    _record(
                        task,
                        "argument_correctness",
                        implementation="ArgumentCorrectnessMetric",
                        scope="turn",
                        event_id=turn["id"],
                        evidence_ids=evidence_ids,
                    ),
                    turn["id"],
                )
            )
        if not any(record["name"] == "argument_correctness" for record, _ in specs):
            specs.append(
                (
                    _record(
                        task,
                        "argument_correctness",
                        implementation="ArgumentCorrectnessMetric",
                        scope="task",
                        event_id=None,
                        evidence_ids=[],
                        status="NOT_APPLICABLE",
                        reason="No recorded tool arguments are available to evaluate.",
                    ),
                    None,
                )
            )
    return specs


def unscored_agentic_metric_records(
    task: dict[str, Any],
    observation: dict[str, Any],
    dimensions: list[str],
    *,
    status: str,
    reason: str,
) -> list[dict[str, Any]]:
    """Create empty native records when isolation or applicability blocks scoring."""
    records = [record for record, _ in _record_specs(task, observation, dimensions)]
    for record in records:
        record.update(
            status=status,
            reason=reason,
            score=None,
            success=None,
            threshold=None,
            events=[],
        )
        if status == "ERROR":
            record["errors"] = [{"kind": "judge", "message": reason}]
    return records


def score_saved_agentic_metrics(
    task: dict[str, Any],
    observation: dict[str, Any],
    model: Any,
    *,
    dimensions: list[str] | None = None,
    max_model_requests: int | None = None,
    work_dir: str | Path,
) -> list[dict[str, Any]]:
    """Score saved evidence without re-running the Agent.

    Each native metric currently uses two judge requests in DeepEval 4.2.9. A
    metric is not started unless both requests remain in the caller's budget.
    """
    selected = list(dimensions or NATIVE_DIMENSIONS)
    unknown = sorted(set(selected) - set(NATIVE_DIMENSIONS))
    if unknown:
        raise ValueError(f"Unknown native dimensions: {', '.join(unknown)}")
    if max_model_requests is not None and max_model_requests < 0:
        raise ValueError("max_model_requests must be nonnegative")
    if not isinstance(getattr(model, "calls", None), list):
        raise TypeError("Native metric model must expose an auditable calls list")
    specs = _record_specs(task, observation, selected)
    if observation.get("execution_kind") in {
        "real_module",
        "deterministic_reference_not_agent",
    }:
        for record, _ in specs:
            record.update(
                status="NOT_APPLICABLE",
                reason="No real Agent execution exists in this execution mode.",
            )
        return [record for record, _ in specs]
    problem = _trace_problem(observation)
    if problem:
        for record, _ in specs:
            record.update(status="MISSING", reason=problem)
        return [record for record, _ in specs]

    start_calls = len(model.calls)
    for record, argument_event_id in specs:
        if record["status"] == "NOT_APPLICABLE":
            continue
        consumed = len(model.calls) - start_calls
        if (
            max_model_requests is not None
            and max_model_requests - consumed < _REQUESTS_PER_METRIC
        ):
            record.update(
                status="MISSING",
                reason="Judge request budget cannot start this two-request metric.",
            )
            continue
        call_start = len(model.calls)
        try:
            if record["name"] == "step_efficiency":
                metric = StepEfficiencyMetric(
                    model=model, eval_mode="llm", async_mode=False
                )
            elif record["name"] == "task_completion":
                metric = TaskCompletionMetric(
                    task=_json({"requests": _requests(task)}),
                    model=model,
                    eval_mode="llm",
                    async_mode=False,
                )
            else:
                metric = ArgumentCorrectnessMetric(
                    model=model, eval_mode="llm", async_mode=False
                )
            _measure(
                task,
                observation,
                metric,
                work_dir=Path(work_dir),
                argument_event_id=argument_event_id,
            )
            score = metric.score
            if not isinstance(score, (int, float)) or not math.isfinite(score):
                raise ValueError("Native metric returned a non-finite score")
            if not 0 <= score <= 1:
                raise ValueError("Native metric returned a score outside [0, 1]")
            record.update(
                score=float(score),
                status="SCORED",
                reason=metric.reason or "",
            )
        except Exception as exc:
            record.update(
                score=None,
                success=None,
                threshold=None,
                status="ERROR",
                reason=f"Native metric failed: {type(exc).__name__}: {exc}",
            )
            record["errors"] = [
                {"kind": "judge", "type": type(exc).__name__, "message": str(exc)}
            ]
        record["events"] = _call_events(model.calls[call_start:])
    return [record for record, _ in specs]


def run_agentic_metrics_worker(
    task: dict[str, Any],
    observation: dict[str, Any],
    model_config: dict[str, Any],
    *,
    dimensions: list[str],
    max_model_requests: int | None,
) -> list[dict[str, Any]]:
    """Run native trace metrics in an upload-disabled subprocess.

    Model credentials are moved through the worker environment. The stdin
    payload contains only public task requests and saved execution evidence.
    """
    worker_key_name = "AGENT_EVAL_NATIVE_JUDGE_API_KEY"
    source_key_name = model_config.get("api_key_env", "OPENAI_API_KEY")
    api_key = model_config.get("api_key") or os.environ.get(source_key_name)
    worker_config = {
        key: model_config[key]
        for key in ("model", "base_url", "timeout", "max_tokens", "extra_body")
        if key in model_config
    }
    worker_config["api_key_env"] = worker_key_name
    public_task = {
        key: task[key] for key in ("id", "prompt", "followups") if key in task
    }
    public_observation = {
        key: observation[key]
        for key in (
            "status",
            "evidence_complete",
            "execution_kind",
            "final_files",
        )
        if key in observation
    }
    public_observation["events"] = [
        _public_event(event) for event in observation.get("events", [])
    ]
    public_observation["turns"] = [
        {key: turn[key] for key in ("input", "output", "snapshot") if key in turn}
        for turn in observation.get("turns", [])
    ]
    payload = {
        "task": public_task,
        "observation": public_observation,
        "model_config": worker_config,
        "dimensions": dimensions,
        "max_model_requests": max_model_requests,
    }
    env = dict(os.environ)
    env.update(
        {
            "CONFIDENT_API_KEY": "",
            "CONFIDENT_TRACING_ENABLED": "NO",
            "DEEPEVAL_DISABLE_DOTENV": "1",
            "DEEPEVAL_TELEMETRY_OPT_OUT": "1",
            "DEEPEVAL_NO_INSPECT_PROMPT": "1",
        }
    )
    if api_key:
        env[worker_key_name] = str(api_key)
    else:
        env.pop(worker_key_name, None)
    timeout = float(model_config.get("timeout", 45))
    request_count = max_model_requests if max_model_requests is not None else 12
    process = subprocess.run(
        [sys.executable, "-m", "eval_framework.benchmark.agentic_metrics_worker"],
        input=_json(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=max(60.0, timeout * max(request_count, 1) + 15.0),
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"DeepEval native metric worker failed with exit code {process.returncode}"
        )
    try:
        records = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "DeepEval native metric worker returned invalid JSON"
        ) from exc
    if not isinstance(records, list) or not all(
        isinstance(record, dict) for record in records
    ):
        raise RuntimeError("DeepEval native metric worker returned invalid records")
    return records
