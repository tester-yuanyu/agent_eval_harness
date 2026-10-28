"""Shared business completeness rules for current and historical evidence."""

from .protocol import status_for


def validate_evidence(events, state, issues):
    events.sort(key=lambda e: e["sequence"])
    sequences = [e["sequence"] for e in events]
    attempts = state.get("attempted_count", len(events))
    ids = [e["event_id"] for e in events if isinstance(e.get("event_id"), str)]
    if len(ids) != len(set(ids)):
        issues.append(dict(kind="partial", code="DUPLICATE_EVENT_ID"))
    if (
        len(events) != attempts
        or any(value != index for index, value in enumerate(sequences, 1))
        or len(events) != state.get("written_count", len(events))
        or state.get("last_sequence", attempts) != attempts
    ):
        issues.append(dict(kind="partial", code="SEQUENCE_OR_COUNT_MISMATCH"))
    if any(e.get("trace_id") != state.get("trace_id") for e in events):
        issues.append(dict(kind="export", code="TRACE_ASSOCIATION_MISMATCH"))
    state.setdefault("issues", []).extend(issues)
    state["status"] = status_for(
        state["issues"],
        completed=state.get("execution_completed", False)
        and state.get("collection_closed", False),
    )
    return events, state
