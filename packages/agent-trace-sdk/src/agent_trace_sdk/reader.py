"""Independent evidence reads through Inspect, plus read-only legacy support."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from inspect_ai.event import InfoEvent
from inspect_ai.log import read_eval_log

from .legacy import LegacyEvidenceReader
from .native import TRACE_FILE
from .validation import validate_evidence


class EvidenceReader:
    def read(
        self,
        directory: str | Path,
        *,
        memory_manifest: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        directory = Path(directory)
        path = directory / TRACE_FILE
        if (
            not path.exists()
            and (directory / "collection.json").exists()
            and (memory_manifest or {}).get("storage_backend") != "inspect-eval-log"
        ):
            return LegacyEvidenceReader().read(
                directory, memory_manifest=memory_manifest
            )
        issues, events = [], []
        state = dict(issues=[], execution_completed=False, collection_closed=False)
        try:
            log = read_eval_log(path, format="json")
            if (
                log.eval.task != "agent_business_evidence"
                or len(log.samples or []) != 1
            ):
                raise ValueError("not a business evidence log")
            sample = log.samples[0]
            state = deepcopy(sample.metadata["evidence"])
            if (
                not isinstance(state, dict)
                or not isinstance(state.get("issues"), list)
                or not all(
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
                or sample.id != state.get("trace_id")
                or log.eval.eval_id != state.get("trace_id")
                or state.get("storage_backend") != "inspect-eval-log"
            ):
                raise ValueError("invalid evidence metadata or association")
            for item in sample.events:
                if not isinstance(item, InfoEvent) or item.source != "agent_evidence":
                    raise ValueError("unexpected evidence event")
                event = deepcopy(item.data)
                if (
                    not isinstance(event, dict)
                    or type(event.get("sequence")) is not int
                ):
                    raise ValueError("invalid evidence envelope")
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
        except Exception:
            # A corrupt native log must never be rescued by old files or Agent
            # memory. Only persisted, independently readable events are proof.
            events = []
            state = dict(issues=[], execution_completed=False, collection_closed=False)
            issues.append(dict(kind="export", code="NATIVE_LOG_READ_FAILED"))

        state["storage_backend"] = "inspect-eval-log"
        if memory_manifest is not None:
            # Memory may downgrade a persisted snapshot (e.g. final write failed),
            # never upgrade its completion flags or replace missing events.
            memory = deepcopy(memory_manifest)
            for issue in memory.get("issues", []):
                if issue not in state["issues"] and issue not in issues:
                    issues.append(issue)
            if any(
                memory.get(key) != state.get(key)
                for key in (
                    "attempted_count",
                    "written_count",
                    "last_sequence",
                    "trace_id",
                )
            ):
                issues.append(dict(kind="export", code="SEQUENCE_OR_COUNT_MISMATCH"))
            for key in ("attempted_count", "last_sequence"):
                state[key] = max(state.get(key, 0), memory.get(key, 0))
            for key in ("execution_completed", "collection_closed"):
                state[key] = state.get(key, False) and memory.get(key, False)
        return validate_evidence(events, state, issues)
