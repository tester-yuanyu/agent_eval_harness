"""Fetch a known attempt's artifacts even when the worker never returns stdout."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .runner import save_json


class WorkerEvidence:
    def __init__(self, output: Path, case_id: str):
        self.output = output
        self.attempt_id = uuid4().hex
        self.directory = output / "evidence" / self.attempt_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.remote = "/sample/evidence/" + self.attempt_id
        self.binding = {
            "version": "worker-evidence-v1",
            "attempt_id": self.attempt_id,
            "case_id": case_id,
        }
        save_json(self.directory / "request.json", self.binding)
        self.receipt = {
            **self.binding,
            "files": {},
            "errors": [],
            "status": "PARTIAL",
            "path": str((self.directory / "receipt.json").relative_to(self.output)),
        }
        save_json(self.directory / "receipt.json", self.receipt)

    async def collect(
        self,
        environment,
        *,
        complete: bool = False,
        require_business_trace: bool = False,
    ) -> dict:
        files, errors = {}, []
        case_hash = hashlib.sha256(self.binding["case_id"].encode()).hexdigest()[:24]
        names = [
            "attempt.json",
            "observation.json",
            "worker-error.json",
            case_hash + "/trace.inspect.json",
        ]
        for name in names:
            try:
                raw = await environment.read_file(self.remote + "/" + name)
                target = self.directory / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(raw)
                files[name] = hashlib.sha256(raw.encode()).hexdigest()
            except FileNotFoundError:
                continue
            except Exception as exc:
                errors.append({"file": name, "code": type(exc).__name__})
        try:
            if (
                json.loads((self.directory / "attempt.json").read_text())
                != self.binding
            ):
                errors.append({"code": "ATTEMPT_MISMATCH"})
        except (OSError, ValueError):
            errors.append({"code": "ATTEMPT_MISSING_OR_INVALID"})
        if require_business_trace and case_hash + "/trace.inspect.json" not in files:
            errors.append({"code": "BUSINESS_TRACE_MISSING"})
        if complete and require_business_trace:
            from agent_trace_sdk import EvidenceReader

            try:
                row = json.loads((self.directory / "observation.json").read_text())
                observed = row["observations"]
                events, manifest = EvidenceReader().read(
                    self.directory / case_hash,
                    memory_manifest=observed["evidence_manifest"],
                )
                if manifest["status"] != "COMPLETE" or events != observed["events"]:
                    errors.append({"code": "BUSINESS_TRACE_INVALID"})
            except (OSError, ValueError, KeyError, TypeError):
                errors.append({"code": "BUSINESS_TRACE_INVALID"})
        receipt = {
            **self.binding,
            "files": files,
            "errors": errors,
            "status": "COMPLETE"
            if complete and not errors and "observation.json" in files
            else "PARTIAL",
            "path": str((self.directory / "receipt.json").relative_to(self.output)),
        }
        save_json(self.directory / "receipt.json", receipt)
        return receipt
