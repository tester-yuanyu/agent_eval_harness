"""显式、不可变的执行补测：只重试已知临时传输错误，保留有效FAIL。"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

from .runner import digest, now, save_json

_TRANSIENT = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "TimeoutError",
    "ConnectionError",
    "RateLimitError",
}
_CONFIG = {
    "MissingSessionID",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "invalid_api_key",
    "model_not_found",
}


def observation_failure_kind(observation: dict) -> str | None:
    kinds = set()
    for error in observation.get("errors", []):
        if not isinstance(error, dict):
            continue
        code = error.get("code") or error.get("type")
        if code == "WORKER_ERROR":
            # Existing workers serialize the outer exception class as a strict prefix.
            # Never search arbitrary tool/business text for a transient keyword.
            code = str(error.get("message", "")).partition(":")[0]
        status = error.get("status_code")
        if code in _CONFIG or status in (401, 403, 404):
            kinds.add("configuration")
        elif code in _TRANSIENT or status in (408, 429, 500, 502, 503, 504):
            kinds.add("transient")
    # Agent wrappers may erase the exception class. Inspect's native ModelEvent
    # still records the provider error; restrict parsing to that trusted source.
    for event in observation.get("events", []):
        if (
            event.get("source") != "inspect_ai.ModelEvent"
            or event.get("type") != "generation"
        ):
            continue
        message = event.get("error")
        if not isinstance(message, str):
            continue
        if message.strip() in {
            "Connection error.",
            "Request timed out.",
            "Request timed out",
        }:
            kinds.add("transient")
        match = re.match(r"^Error code: (\d{3})(?: -|$)", message)
        if match:
            status = int(match[1])
            if status in (401, 403, 404):
                kinds.add("configuration")
            elif status in (408, 429, 500, 502, 503, 504):
                kinds.add("transient")
            elif status == 400 and len(message) < 65536:
                body = message.partition(" - ")[2]
                try:
                    payload = ast.literal_eval(body)
                except (ValueError, SyntaxError, RecursionError):
                    try:
                        payload = json.loads(body)
                    except (ValueError, RecursionError):
                        payload = None
                if isinstance(payload, dict):
                    error = payload.get("error", payload)
                    if isinstance(error, dict) and any(
                        error.get(key) in _CONFIG | {"unsupported_model"}
                        for key in ("code", "type")
                        if isinstance(error.get(key), str)
                    ):
                        kinds.add("configuration")
    return (
        "configuration"
        if "configuration" in kinds
        else "transient"
        if "transient" in kinds
        else None
    )


def prepare_recovery(source: Path, output: Path) -> dict:
    source, output = Path(source).resolve(), Path(output).resolve()
    if (
        source == output
        or output.is_relative_to(source)
        or (output.exists() and any(output.iterdir()))
    ):
        raise ValueError("Recovery output must be a new empty directory")
    raw = (source / "results.json").read_bytes()
    saved = json.loads(raw)
    identity_hash = saved["identity_hash"]
    if digest(saved["identity"]) != identity_hash:
        raise ValueError("Source identity Hash mismatch")
    if saved.get("provenance", {}).get("operation") == "judge_saved_evidence":
        raise ValueError("Recovery requires original execution, not Judge output")
    cases, repeats = saved["planned_case_ids"], saved["trials_per_case"]
    expected = {(case, trial) for case in cases for trial in range(1, repeats + 1)}
    seen, retained, retry = set(), {}, []
    for row in saved["trials"]:
        key = row["case_id"], row["trial"]
        if key in seen or key not in expected or type(row["trial"]) is not int:
            raise ValueError("Source duplicate or invalid trial")
        if row["identity_hash"] != identity_hash:
            raise ValueError("Source trial identity mismatch")
        seen.add(key)
        invalid = (
            row["assessment"].get("validity") == "INVALID"
            and row["assessment"].get("verdict") == "INVALID"
        )
        if invalid and observation_failure_kind(row["observation"]) == "transient":
            retry.append({"case_id": key[0], "trial": key[1]})
        else:
            name = f"{cases.index(key[0]) + 1:04d}-t{key[1]}.json"
            retained[name] = row
    if seen != expected:
        raise ValueError(
            "Source is incomplete; resume original run before preparing recovery"
        )
    evidence_files = {}
    for row in retained.values():
        evidence = row["observation"].get("native_evidence")
        if not evidence:
            continue
        relative = Path(evidence["path"])
        path = (source / relative).resolve()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not path.is_relative_to(source)
        ):
            raise ValueError("Native evidence path escapes source run")
        if hashlib.sha256(path.read_bytes()).hexdigest() != evidence["sha256"]:
            raise ValueError("Native evidence Hash mismatch")
        evidence_files[relative.as_posix()] = path
    manifest = {
        "operation": "retry_execution",
        "source": str(source),
        "source_results_sha256": hashlib.sha256(raw).hexdigest(),
        "source_identity_hash": identity_hash,
        "retry_trials": retry,
        "retained_trials": {name: digest(row) for name, row in retained.items()},
    }
    meta = {
        k: copy.deepcopy(v)
        for k, v in saved.items()
        if k not in ("trials", "summary", "finished_at")
    }
    meta.update(
        run_id=output.name + "-" + uuid.uuid4().hex[:16],
        started_at=now(),
        provenance=manifest,
    )
    output.mkdir(parents=True, exist_ok=True)
    for name, path in evidence_files.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    for name, row in retained.items():
        save_json(output / "trials" / name, row)
    save_json(output / "run.json", meta)
    save_json(output / "recovery.json", manifest)
    return manifest
