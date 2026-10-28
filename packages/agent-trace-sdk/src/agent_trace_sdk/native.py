"""Business evidence policy backed by public Inspect Transcript / EvalLog APIs."""

import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from inspect_ai.log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalSample,
    EvalSpec,
    Transcript,
    write_eval_log,
)

from .protocol import EventRule, TraceContext, status_for

TRACE_FILE = "trace.inspect.json"
_SECRET = re.compile(
    r"authorization|password|passwd|secret|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|credential|cookie|reasoning_content|chain_of_thought",
    re.I,
)
_TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]+|Bearer\s+[A-Za-z0-9._~-]+)", re.I)


class InspectEvidenceSink:
    """Trial policy adapter; Inspect owns collection and durable atomic storage.

    A lock serializes validation, sequence allocation and the native snapshot
    because multiple Agent worker threads can share a Trial's sink.
    """

    def __init__(
        self,
        directory: str | Path,
        context: TraceContext,
        *,
        max_string: int = 4096,
        max_items: int = 128,
        event_rules_version: str = "events-v1",
        max_record_bytes: int = 65536,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.context = context
        self.max_string = max_string
        self.max_items = max_items
        self.max_record_bytes = max_record_bytes
        self._lock = RLock()
        self.transcript = Transcript()
        self._state = dict(
            protocol_version="1.0",
            storage_backend="inspect-eval-log",
            event_rules_version=event_rules_version,
            trace_id=context.trace_id,
            attempted_count=0,
            written_count=0,
            last_sequence=0,
            execution_completed=False,
            collection_closed=False,
            issues=[],
        )
        self._spec = EvalSpec(
            created=datetime.now(UTC).isoformat(),
            task="agent_business_evidence",
            eval_id=context.trace_id,
            run_id=context.trace_id,
            dataset=EvalDataset(samples=1),
            model="external-agent",
            config=EvalConfig(),
        )
        self._persist()

    def _issue(self, kind, code, sequence=None):
        self._state["issues"].append(dict(kind=kind, code=code, sequence=sequence))

    def manifest(self) -> dict[str, Any]:
        with self._lock:
            state = deepcopy(self._state)
            state["status"] = status_for(
                state["issues"],
                completed=state["execution_completed"] and state["collection_closed"],
            )
            return state

    def _persist(self) -> None:
        sample = EvalSample(
            id=self.context.trace_id,
            epoch=1,
            input="",
            target="",
            events=list(self.transcript.events),
            metadata={"evidence": self.manifest()},
        )
        # This is an evidence artifact, not an additional evaluation/score run.
        # Native JSON writes atomically and fsyncs before returning.
        write_eval_log(
            EvalLog(eval=self._spec, samples=[sample]),
            self.directory / TRACE_FILE,
            format="json",
        )

    def _checkpoint(self) -> None:
        try:
            self._persist()
        except Exception:
            self._issue("export", "MANIFEST_WRITE_FAILED")

    def _sanitize(self, value, redacted, truncated, path="payload", depth=0):
        if depth > 10:
            truncated.append(path)
            return "[TRUNCATED]"
        if isinstance(value, dict):
            result = {}
            for index, (key, child) in enumerate(value.items()):
                if index >= self.max_items:
                    truncated.append(path)
                    break
                if not isinstance(key, str):
                    truncated.append(path)
                    continue
                if _SECRET.search(key):
                    redacted.append(f"{path}.{key}")
                    continue
                result[key] = self._sanitize(
                    child, redacted, truncated, f"{path}.{key}", depth + 1
                )
            return result
        if isinstance(value, (tuple, list)):
            if len(value) > self.max_items:
                truncated.append(path)
            return [
                self._sanitize(v, redacted, truncated, path, depth + 1)
                for v in value[: self.max_items]
            ]
        if isinstance(value, str):
            clean = _TOKEN.sub("[REDACTED]", value)
            if clean != value:
                redacted.append(path)
            if len(clean) > self.max_string:
                truncated.append(path)
                clean = clean[: self.max_string] + "[TRUNCATED]"
            return clean
        if value is None or isinstance(value, (bool, int, float)):
            return value
        truncated.append(path)
        return "[UNSERIALIZABLE]"

    def record(
        self,
        event: dict[str, Any],
        *,
        context: TraceContext,
        rule: EventRule | None = None,
    ) -> None:
        with self._lock:
            self._state["attempted_count"] += 1
            sequence = self._state["attempted_count"]
            self._state["last_sequence"] = sequence
            previous = list(self.transcript.events)
            written = self._state["written_count"]
            try:
                if self._state["collection_closed"]:
                    raise RuntimeError("evidence collection is closed")
                if context.trace_id != self.context.trace_id:
                    self._issue("export", "TRACE_ASSOCIATION_MISMATCH", sequence)
                    self._checkpoint()
                    return
                payload = event.get("payload", {})
                redacted, truncated = [], []
                errors = []
                if rule is None:
                    errors.append("UNKNOWN_EVENT_TYPE")
                    # Unknown fields have no allowlist: retain the envelope only.
                    redacted.extend(f"payload.{key}" for key in payload)
                    payload = {}
                else:
                    errors.extend(
                        f"MISSING_FIELD:{key}"
                        for key in rule.required
                        if key not in payload
                    )
                    errors.extend(
                        f"INVALID_TYPE:{key}"
                        for key, kind in rule.field_types
                        if key in payload and not isinstance(payload[key], kind)
                    )
                    redacted.extend(
                        f"payload.{key}" for key in payload if key not in rule.fields
                    )
                    payload = {k: v for k, v in payload.items() if k in rule.fields}
                safe = self._sanitize(payload, redacted, truncated)
                record = {
                    k: event[k]
                    for k in (
                        "event_id",
                        "run_id",
                        "session_id",
                        "event_type",
                        "timestamp",
                    )
                    if k in event
                }
                record.update(
                    protocol_version="1.0",
                    event_rules_version=self._state["event_rules_version"],
                    trace_id=context.trace_id,
                    turn_index=context.turn_index,
                    sequence=sequence,
                    capability_layer=rule.layer if rule else None,
                    source="sdk",
                    payload=safe,
                    validation_status=(
                        "VALID"
                        if not errors and not truncated and not redacted
                        else "INVALID"
                    ),
                    validation_issues=errors,
                    redacted_fields=redacted,
                    truncated=bool(truncated),
                    truncated_fields=truncated,
                )
                if errors or truncated or redacted:
                    self._issue("partial", "INVALID_OR_TRUNCATED_EVENT", sequence)
                encoded = json.dumps(record, ensure_ascii=False, allow_nan=False)
                if len(encoded.encode("utf-8")) > self.max_record_bytes:
                    record.update(
                        payload={},
                        validation_status="INVALID",
                        truncated=True,
                        truncated_fields=["payload"],
                        redacted_fields=[],
                    )
                    self._issue("partial", "RECORD_SIZE_EXCEEDED", sequence)
                    encoded = json.dumps(record, ensure_ascii=False, allow_nan=False)
                    if len(encoded.encode("utf-8")) > self.max_record_bytes:
                        self._issue("partial", "ENVELOPE_SIZE_EXCEEDED", sequence)
                        self._checkpoint()
                        return
                self.transcript.info(record, source="agent_evidence")
                self._state["written_count"] += 1
                self._persist()
            except Exception:
                self.transcript = Transcript(events=previous)
                self._state["written_count"] = written
                self._issue("export", "EVENT_WRITE_FAILED", sequence)
                self._checkpoint()

    def finish(self, *, execution_completed: bool) -> dict[str, Any]:
        with self._lock:
            if not self._state["collection_closed"]:
                self._state["execution_completed"] = bool(execution_completed)
                self._state["collection_closed"] = True
                self._checkpoint()
            return self.manifest()
