"""Read-only compatibility for historical JSONL evidence. Never writes."""

import json
from copy import deepcopy
from pathlib import Path

from .validation import validate_evidence


class LegacyEvidenceReader:
    def read(self, directory, *, memory_manifest=None):
        directory = Path(directory)
        issues, events = [], []
        if memory_manifest is not None:
            state = deepcopy(memory_manifest)
        else:
            try:
                state = json.loads((directory / "collection.json").read_text())
                if not isinstance(state, dict) or not isinstance(
                    state.get("issues"), list
                ):
                    raise ValueError("invalid collection manifest")
                if (
                    not all(
                        type(state.get(key)) is int and state[key] >= 0
                        for key in ("attempted_count", "written_count", "last_sequence")
                    )
                    or not all(
                        type(state.get(key)) is bool
                        for key in ("execution_completed", "collection_closed")
                    )
                    or not all(
                        isinstance(issue, dict)
                        and issue.get("kind") in {"partial", "export"}
                        for issue in state["issues"]
                    )
                ):
                    raise ValueError("invalid manifest counters or flags")
            except (OSError, ValueError):
                state = dict(
                    issues=[], execution_completed=False, collection_closed=False
                )
                issues.append(dict(kind="partial", code="MANIFEST_UNAVAILABLE"))
        try:
            with (directory / "events.jsonl").open("rb") as stream:
                for line in stream:
                    try:
                        event = json.loads(line.decode("utf-8"))
                        if (
                            not isinstance(event, dict)
                            or type(event.get("sequence")) is not int
                        ):
                            raise ValueError("invalid envelope")
                        if not all(
                            isinstance(event.get(key), str)
                            for key in (
                                "event_id",
                                "event_type",
                                "trace_id",
                                "run_id",
                                "timestamp",
                            )
                        ) or not isinstance(event.get("payload"), dict):
                            event["validation_status"] = "INVALID"
                            issues.append(dict(kind="partial", code="INVALID_ENVELOPE"))
                        events.append(event)
                    except ValueError:
                        issues.append(dict(kind="partial", code="DAMAGED_RECORD"))
        except OSError:
            issues.append(dict(kind="export", code="EVENT_READ_FAILED"))
        return validate_evidence(events, state, issues)
