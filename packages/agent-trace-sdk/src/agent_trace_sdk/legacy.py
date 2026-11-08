"""Read-only compatibility for historical JSONL evidence. Never writes."""

import json
from copy import deepcopy
from pathlib import Path

from .validation import valid_event_envelope, valid_manifest, validate_evidence


class LegacyEvidenceReader:
    def read(self, directory, *, memory_manifest=None):
        directory = Path(directory)
        issues, events = [], []
        if memory_manifest is not None:
            state = deepcopy(memory_manifest)
        else:
            try:
                state = json.loads((directory / "collection.json").read_text())
                if not valid_manifest(state):
                    raise ValueError("invalid collection manifest")
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
                        if not valid_event_envelope(event):
                            event["validation_status"] = "INVALID"
                            issues.append(dict(kind="partial", code="INVALID_ENVELOPE"))
                        events.append(event)
                    except ValueError:
                        issues.append(dict(kind="partial", code="DAMAGED_RECORD"))
        except OSError:
            issues.append(dict(kind="export", code="EVENT_READ_FAILED"))
        return validate_evidence(events, state, issues)
