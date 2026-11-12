"""Persist Inspect events at execution boundaries, without a second event format."""

from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from inspect_ai.log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalSample,
    EvalSpec,
    transcript,
    write_eval_log,
)

_active: ContextVar[NativeCheckpoint | None] = ContextVar(
    "native_checkpoint", default=None
)


def checkpoint_business_event() -> None:
    if checkpoint := _active.get():
        checkpoint.capture()


class NativeCheckpoint:
    """One attempt's immutable identity; each native snapshot is atomically replaced.

    This is durable corroboration of the same execution, not an independent oracle.
    An unfinished checkpoint remains partial even if its last model call succeeded.
    """

    def __init__(self, directory: Path, task_id: str):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.task_id = task_id
        self.start = len(transcript().events)
        self.errors: list[str] = []
        self.receipt: dict[str, Any] = {}
        self.spec = EvalSpec(
            created=datetime.now(UTC).isoformat(),
            task="harness_checkpoint",
            eval_id=self.directory.name,
            run_id=self.directory.name,
            dataset=EvalDataset(samples=1),
            model="harness",
            config=EvalConfig(),
        )

    def __enter__(self) -> NativeCheckpoint:
        self.token = _active.set(self)
        self.capture()
        return self

    def __exit__(self, *exc: Any) -> None:
        _active.reset(self.token)

    def capture(self, complete: bool = False) -> None:
        try:
            events = list(transcript().events[self.start :])
            native = self.directory / "trace.inspect.json"
            metadata = {
                "version": "harness-checkpoint-v1",
                "task_id": self.task_id,
                "attempt_id": self.directory.name,
                "evidence_complete": complete and not self.errors,
            }
            write_eval_log(
                EvalLog(
                    eval=self.spec,
                    samples=[
                        EvalSample(
                            id=self.task_id,
                            epoch=1,
                            input="",
                            target="",
                            events=events,
                            metadata=metadata,
                        )
                    ],
                ),
                native,
                format="json",
            )
            receipt = {
                **metadata,
                "path": str(native),
                "event_count": len(events),
                "sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
                "errors": list(self.errors),
            }
            temporary = self.directory / "checkpoint.json.tmp"
            temporary.write_text(json.dumps(receipt, indent=2) + "\n")
            temporary.replace(self.directory / "checkpoint.json")
            self.receipt = receipt
        except Exception as exc:
            self.errors.append(type(exc).__name__)

    def finish(self, observation: dict | None) -> None:
        self.capture(bool(observation and observation.get("evidence_complete")))
        if observation is not None:
            observation["native_evidence"] = dict(self.receipt)
            if self.errors:
                observation["evidence_complete"] = False
                if isinstance(observation.get("trace"), dict):
                    observation["trace"]["evidence_complete"] = False
                observation["native_evidence"]["evidence_complete"] = False
                observation["native_evidence"]["errors"] = list(self.errors)
                observation.setdefault("errors", []).append(
                    {
                        "kind": "evidence",
                        "code": "CHECKPOINT_WRITE_FAILED",
                        "message": ", ".join(self.errors),
                    }
                )
