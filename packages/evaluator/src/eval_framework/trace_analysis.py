"""Read-only normalization and structural analysis of Agent traces."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from eval_contracts.trace import duplicate_event_ids

from .phase2_schemas import (
    AnalysisPaths,
    NormalizedTraceEvent,
    RunAnalysis,
    TraceAnalysis,
    TraceIssue,
)
from .provider import TraceRule
from .schemas import CaseResult, EvaluationRunResult

ANALYSIS_VERSION = "trace-analysis-v1"
_TERMINAL_SUFFIXES = (
    "finished",
    "decided",
    "accepted",
    "rejected",
    "completed",
    "succeeded",
    "failed",
    "timeout",
    "cancelled",
)


def _normalize(case: CaseResult) -> list[NormalizedTraceEvent]:
    sources: list[tuple[int, str | None, dict]] = []
    if case.trace_id is not None:
        sources.extend(
            (
                event.get("turn_index", 0)
                if type(event.get("turn_index", 0)) is int
                and event.get("turn_index", 0) >= 0
                else 0,
                event.get("run_id"),
                event,
            )
            for event in sorted(case.trace_events, key=lambda e: e.get("sequence", 0))
        )
    turns_with_events = case.trace_id is None and any(
        turn.get("events") for turn in case.turn_results
    )
    if turns_with_events:
        for turn_index, turn in enumerate(case.turn_results):
            run_id = turn.get("run_id")
            for event in turn.get("events", []):
                sources.append((turn_index, run_id, event))
    elif case.trace_id is None:
        sources.extend((0, None, event) for event in case.trace_events)

    timeline = []
    for source_index, (turn_index, run_id, raw) in enumerate(sources):
        event_id = str(raw.get("event_id") or f"missing-event-{source_index}")
        timeline.append(
            NormalizedTraceEvent(
                event_id=event_id,
                event_type=str(raw.get("event_type") or "unknown"),
                turn_index=turn_index,
                agent_run_id=str(run_id) if run_id is not None else None,
                timestamp=(
                    str(raw["timestamp"]) if raw.get("timestamp") is not None else None
                ),
                evidence_ref=f"event:{event_id}",
                source_index=source_index,
                payload=dict(raw),
            )
        )
    return timeline


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _structural_issues(
    case: CaseResult, timeline: Sequence[NormalizedTraceEvent]
) -> list[TraceIssue]:
    issues: list[TraceIssue] = []
    counts = duplicate_event_ids(event.event_id for event in timeline)
    for event_id, count in sorted(counts.items()):
        issues.append(
            TraceIssue(
                code="OBSERVED_DUPLICATE_EVENT_ID",
                message=f"Observed event ID {event_id!r} {count} times.",
                evidence_refs=[f"event:{event_id}"],
            )
        )

    previous: tuple[datetime, NormalizedTraceEvent] | None = None
    for event in timeline:
        current = _parse_timestamp(event.timestamp)
        if (
            current is not None
            and previous is not None
            and (current.tzinfo is None) == (previous[0].tzinfo is None)
            and current < previous[0]
        ):
            issues.append(
                TraceIssue(
                    code="OBSERVED_TIMESTAMP_REVERSAL",
                    message=(
                        "Observed a timestamp earlier than the preceding trace event."
                    ),
                    evidence_refs=[previous[1].evidence_ref, event.evidence_ref],
                )
            )
        if current is not None:
            previous = (current, event)

    declared_runs = set(case.agent_run_ids)
    for event in timeline:
        if event.agent_run_id is not None and event.agent_run_id not in declared_runs:
            issues.append(
                TraceIssue(
                    code="OBSERVED_RUN_ASSOCIATION_MISMATCH",
                    message=(
                        f"Observed trace run {event.agent_run_id!r} outside the Case "
                        "run list."
                    ),
                    evidence_refs=[event.evidence_ref],
                )
            )

    for event in timeline:
        payload = event.payload.get("payload")
        call_id = payload.get("call_id") if isinstance(payload, dict) else None
        event_types = {
            candidate.event_type
            for candidate in timeline
            if candidate.agent_run_id == event.agent_run_id
            and isinstance(candidate.payload.get("payload", {}), dict)
            and candidate.payload.get("payload", {}).get("call_id") == call_id
        }
        if event.event_type.endswith("_requested"):
            base = event.event_type.removesuffix("_requested")
        elif event.event_type.endswith("_started"):
            base = event.event_type.removesuffix("_started")
        else:
            continue
        if not any(f"{base}_{suffix}" in event_types for suffix in _TERMINAL_SUFFIXES):
            issues.append(
                TraceIssue(
                    code="OBSERVED_UNCLOSED_LIFECYCLE",
                    message=(
                        f"Observed {event.event_type!r} without a terminal partner."
                    ),
                    evidence_refs=[event.evidence_ref],
                )
            )
    return issues


def _evidence_refs(case: CaseResult) -> list[str]:
    refs = [ref for item in case.assertion_results for ref in item.evidence_refs]
    if case.judge_result is not None:
        refs.extend(
            ref
            for dimension in case.judge_result.dimensions
            for ref in dimension.evidence_refs
        )
    return refs


def _evidence_issues(
    case: CaseResult, timeline: Sequence[NormalizedTraceEvent]
) -> list[TraceIssue]:
    event_ids = {event.event_id for event in timeline}
    call_ids = {str(call.get("call_id")) for call in case.tool_calls}
    issues = []
    for ref in dict.fromkeys(_evidence_refs(case)):
        resolved = (
            (ref.startswith("event:") and ref.removeprefix("event:") in event_ids)
            or (
                ref.startswith("trace:") and ref.removeprefix("trace:") == case.trace_id
            )
            or (
                ref.startswith("tool_call:call:")
                and ref.removeprefix("tool_call:call:") in call_ids
            )
            or ref.startswith("module_output:")
            or ref.startswith("snapshot:")
            or ref.startswith("turn:")
        )
        if not resolved:
            issues.append(
                TraceIssue(
                    code="EVIDENCE_REF_UNRESOLVED",
                    message=(
                        f"Evidence reference {ref!r} does not resolve in this Trial."
                    ),
                    severity="ERROR",
                    evidence_refs=[ref],
                )
            )
    return issues


def analyze_case_trace(
    case: CaseResult, rules: Sequence[TraceRule] = ()
) -> TraceAnalysis:
    timeline = _normalize(case)
    issues = _structural_issues(case, timeline)
    issues.extend(_evidence_issues(case, timeline))
    for issue in case.evaluation_issues:
        issues.append(
            TraceIssue(
                code=issue.get("code", "EVIDENCE_ISSUE"),
                message=issue.get("code", "Evidence issue"),
                severity="ERROR" if issue.get("kind") == "export" else "WARNING",
                evidence_refs=[f"trace:{case.trace_id}"] if case.trace_id else [],
            )
        )
    valid_timeline = [
        event
        for event in timeline
        if case.trace_id is None or event.payload.get("validation_status") == "VALID"
    ]
    for rule in rules:
        issues.extend(rule.analyze(valid_timeline, case))
    first = next((issue for issue in issues if issue.severity != "INFO"), None)
    suggested = list(
        dict.fromkeys(
            issue.message for issue in issues if issue.code.startswith("SUGGESTED_")
        )
    )
    return TraceAnalysis(
        timeline=timeline,
        issues=issues,
        first_observed_deviation=first,
        suggested_investigation_areas=suggested,
    )


def analyze_run(
    result: EvaluationRunResult,
    rules: Sequence[TraceRule] = (),
    *,
    source_results_sha256: str,
) -> RunAnalysis:
    return RunAnalysis(
        analysis_version=ANALYSIS_VERSION,
        source_results_sha256=source_results_sha256,
        traces={
            f"{case.case_id}/{case.trial_id}": analyze_case_trace(case, rules)
            for case in result.cases
        },
    )


def write_run_analysis(analysis: RunAnalysis, run_dir: str | Path) -> AnalysisPaths:
    root = Path(run_dir).resolve()
    trace_root = root / "trace_analysis"
    trace_files = []
    for key, trace in analysis.traces.items():
        case_id, trial_id = key.split("/", 1)
        case_dir = trace_root / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        path = case_dir / f"{trial_id}.json"
        path.write_text(trace.model_dump_json(indent=2), encoding="utf-8")
        trace_files.append(str(path))
    analysis_path = root / "analysis.json"
    analysis_path.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
    return AnalysisPaths(analysis=str(analysis_path), trace_files=trace_files)
