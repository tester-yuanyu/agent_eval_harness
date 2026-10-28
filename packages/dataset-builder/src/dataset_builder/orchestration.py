"""Deterministic stage execution and append-only provenance records."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .capability_profiles import canonical_sha256
from .plugins import PluginKey


class StageError(ValueError):
    """A pipeline stage could not be recorded or reused."""


class StageExecutionError(StageError):
    """A stage operation failed after its inputs were bound."""


class StageInputMismatchError(StageError):
    """A recorded stage was requested with different bound inputs."""


@dataclass(frozen=True, order=True)
class StageInput:
    name: str
    sha256: str


@dataclass(frozen=True, order=True)
class PolicyBinding:
    kind: str
    version: str
    path: str
    sha256: str
    schema_sha256: str


@dataclass(frozen=True)
class StageOutput:
    value: Any
    sha256: str


@dataclass(frozen=True)
class StageRecord:
    stage_id: str
    plugin: PluginKey
    inputs: tuple[StageInput, ...]
    policy_bindings: tuple[PolicyBinding, ...]
    input_fingerprint: str
    status: Literal["succeeded", "failed"]
    output_sha256: str | None
    error_type: str | None
    error_message: str | None
    created_at: str

    def as_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["plugin"] = asdict(self.plugin)
        return payload

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> StageRecord:
        return cls(
            stage_id=payload["stage_id"],
            plugin=PluginKey(**payload["plugin"]),
            inputs=tuple(StageInput(**item) for item in payload["inputs"]),
            policy_bindings=tuple(
                PolicyBinding(**item) for item in payload["policy_bindings"]
            ),
            input_fingerprint=payload["input_fingerprint"],
            status=payload["status"],
            output_sha256=payload["output_sha256"],
            error_type=payload["error_type"],
            error_message=payload["error_message"],
            created_at=payload["created_at"],
        )


def stage_input_fingerprint(
    stage_id: str,
    plugin: PluginKey,
    inputs: tuple[StageInput, ...],
    policy_bindings: tuple[PolicyBinding, ...],
) -> str:
    return canonical_sha256(
        {
            "stage_id": stage_id,
            "plugin": asdict(plugin),
            "inputs": [asdict(item) for item in sorted(inputs)],
            "policy_bindings": [
                asdict(item) for item in sorted(policy_bindings)
            ],
        }
    )


class StageLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.records = self._load()

    def _load(self) -> list[StageRecord]:
        if not self.path.is_file():
            return []
        return [
            StageRecord.from_json(json.loads(line))
            for line in self.path.read_text().splitlines()
            if line.strip()
        ]

    def append(self, record: StageRecord) -> None:
        if any(item.stage_id == record.stage_id for item in self.records):
            raise ValueError(f"stage already recorded: {record.stage_id}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(record.as_json(), ensure_ascii=False, sort_keys=True)
                + "\n"
            )
        self.records.append(record)

    def assert_reusable(
        self,
        stage_id: str,
        plugin: PluginKey,
        inputs: tuple[StageInput, ...],
        policy_bindings: tuple[PolicyBinding, ...],
    ) -> StageRecord:
        record = next(
            (item for item in self.records if item.stage_id == stage_id), None
        )
        if record is None:
            raise StageInputMismatchError(f"stage is not recorded: {stage_id}")
        expected = stage_input_fingerprint(
            stage_id, plugin, inputs, policy_bindings
        )
        if record.input_fingerprint != expected:
            raise StageInputMismatchError(
                f"stage input fingerprint changed: {stage_id}"
            )
        if record.status != "succeeded":
            raise StageInputMismatchError(f"stage did not succeed: {stage_id}")
        return record


class PipelineEngine:
    def __init__(self, ledger: StageLedger) -> None:
        self.ledger = ledger

    def run_stage(
        self,
        stage_id: str,
        plugin: PluginKey,
        inputs: tuple[StageInput, ...],
        policy_bindings: tuple[PolicyBinding, ...],
        operation: Callable[[], Any],
    ) -> StageOutput:
        if any(item.stage_id == stage_id for item in self.ledger.records):
            raise ValueError(f"stage already recorded: {stage_id}")
        fingerprint = stage_input_fingerprint(
            stage_id, plugin, inputs, policy_bindings
        )
        created_at = datetime.now(UTC).isoformat()
        try:
            value = operation()
            output = StageOutput(value=value, sha256=canonical_sha256(value))
        except Exception as exc:
            self.ledger.append(
                StageRecord(
                    stage_id=stage_id,
                    plugin=plugin,
                    inputs=inputs,
                    policy_bindings=policy_bindings,
                    input_fingerprint=fingerprint,
                    status="failed",
                    output_sha256=None,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    created_at=created_at,
                )
            )
            raise StageExecutionError(
                f"stage {stage_id!r} failed: {exc}"
            ) from exc
        self.ledger.append(
            StageRecord(
                stage_id=stage_id,
                plugin=plugin,
                inputs=inputs,
                policy_bindings=policy_bindings,
                input_fingerprint=fingerprint,
                status="succeeded",
                output_sha256=output.sha256,
                error_type=None,
                error_message=None,
                created_at=created_at,
            )
        )
        return output
