"""Shared business completeness rules for current and historical evidence."""

from eval_contracts.trace import associations_match, duplicate_event_ids

from .protocol import status_for


def valid_manifest(state) -> bool:
    """Check shared counters and flags without imposing a storage backend."""
    return (
        isinstance(state, dict)
        and isinstance(state.get("issues"), list)
        and all(
            type(state.get(key)) is int and state[key] >= 0
            for key in ("attempted_count", "written_count", "last_sequence")
        )
        and all(
            type(state.get(key)) is bool
            for key in ("execution_completed", "collection_closed")
        )
        and all(
            isinstance(issue, dict) and issue.get("kind") in {"partial", "export"}
            for issue in state["issues"]
        )
    )


def valid_event_envelope(event) -> bool:
    """Raise for unreadable records; return False for diagnosable field damage."""
    if not isinstance(event, dict) or type(event.get("sequence")) is not int:
        raise ValueError("invalid evidence envelope")
    return all(
        isinstance(event.get(key), str)
        for key in ("event_id", "event_type", "trace_id", "run_id", "timestamp")
    ) and isinstance(event.get("payload"), dict)


def validate_evidence(events, state, issues):
    events.sort(key=lambda e: e["sequence"])
    sequences = [e["sequence"] for e in events]
    attempts = state.get("attempted_count", len(events))
    ids = [e["event_id"] for e in events if isinstance(e.get("event_id"), str)]
    if duplicate_event_ids(ids):
        issues.append(dict(kind="partial", code="DUPLICATE_EVENT_ID"))
    if (
        len(events) != attempts
        or any(value != index for index, value in enumerate(sequences, 1))
        or len(events) != state.get("written_count", len(events))
        or state.get("last_sequence", attempts) != attempts
    ):
        issues.append(dict(kind="partial", code="SEQUENCE_OR_COUNT_MISMATCH"))
    if not associations_match(
        (e.get("trace_id") for e in events), state.get("trace_id")
    ):
        issues.append(dict(kind="export", code="TRACE_ASSOCIATION_MISMATCH"))
    state.setdefault("issues", []).extend(issues)
    state["status"] = status_for(
        state["issues"],
        completed=state.get("execution_completed", False)
        and state.get("collection_closed", False),
    )
    return events, state
