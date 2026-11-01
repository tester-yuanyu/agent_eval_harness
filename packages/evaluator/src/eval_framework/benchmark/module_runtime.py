"""Execute isolated real nanobot ToolRegistry boundaries without a model provider."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .nanobot_runtime import (
    EXECUTION_KEYS,
    FILE_TOOLS,
    _journal_events,
    _terminate,
    runtime_identity,
    snapshot_files,
    utc_now,
)


def module_execution_projection(task: dict[str, Any]) -> dict[str, Any]:
    unexpected = set(task) - EXECUTION_KEYS - {"module_calls"}
    if unexpected:
        raise ValueError(f"non-execution module fields: {sorted(unexpected)}")
    calls = task.get("module_calls")
    allowed = task.get("allowed_tools", list(FILE_TOOLS))
    if not isinstance(allowed, list) or not allowed or not set(allowed) <= FILE_TOOLS:
        raise ValueError("module execution permits only filesystem tools")
    if not isinstance(calls, list) or not calls or len(calls) > 40:
        raise ValueError("module execution requires 1 to 40 calls")
    for call in calls:
        if (
            not isinstance(call, dict)
            or set(call) != {"name", "arguments"}
            or call["name"] not in allowed
            or not isinstance(call["arguments"], dict)
        ):
            raise ValueError(
                "module calls require supported names and argument objects"
            )
    if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
        raise ValueError("module prompt must be nonempty")
    if task.get("followups"):
        raise ValueError("module execution is a single fixed request")
    return json.loads(json.dumps(task, ensure_ascii=False))


def module_identity(config: dict[str, Any]) -> dict[str, Any]:
    identity = runtime_identity({**config, "model": None})
    identity.update(
        adapter_version="nanobot-module-v1", model=None, execution_kind="real_module"
    )
    return identity


async def execute_module_task(
    task: dict[str, Any], *, config: dict[str, Any], workspace: Path
) -> dict[str, Any]:
    """No provider credentials or evaluator-private assertions enter the worker."""
    task = module_execution_projection(task)
    workspace = workspace.resolve(strict=True)
    before = snapshot_files(workspace)
    root = Path(config["nanobot_root"]).expanduser().resolve(strict=True)
    identity = module_identity(config)
    result: dict[str, Any] = {
        "status": "error",
        "execution_kind": "real_module",
        "turns": [],
        "events": [],
        "before_files": before,
        "final_files": {},
        "usage": {},
        "errors": [],
        "evidence_complete": False,
        "runtime_identity": identity,
    }
    with tempfile.TemporaryDirectory(
        prefix="nanobot-module-", dir=workspace.parent
    ) as private:
        payload = {"task": task, "workspace": str(workspace), "runtime_dir": private}
        env = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "PATH",
                "LANG",
                "LC_ALL",
                "SYSTEMROOT",
                "TMPDIR",
                "SSL_CERT_FILE",
                "SSL_CERT_DIR",
            }
        }
        env.update(PYTHONPATH=str(root), PYTHONUNBUFFERED="1")
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                str(config.get("python") or root / ".venv/bin/python"),
                str(Path(__file__).with_name("module_worker.py")),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=private,
                env=env,
                start_new_session=True,
            )
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(json.dumps(payload).encode()),
                timeout=float(config.get("module_timeout_seconds", 30)),
            )
            if process.returncode == 0:
                result.update(json.loads(stdout))
            else:
                result["errors"].append(
                    {
                        "kind": "environment",
                        "code": "module_worker_exit",
                        "message": f"module worker exited {process.returncode}",
                    }
                )
        except TimeoutError:
            if process is not None:
                await _terminate(process)
            result.update(status="timeout", stop_reason="timeout")
            result["errors"].append(
                {
                    "kind": "agent",
                    "code": "module_timeout",
                    "message": "module deadline exceeded",
                }
            )
        except asyncio.CancelledError:
            if process is not None:
                await _terminate(process)
            raise
        except (ValueError, OSError) as exc:
            if process is not None:
                await _terminate(process)
            result["errors"].append(
                {"kind": "environment", "code": type(exc).__name__, "message": str(exc)}
            )
        result["events"] = _journal_events(Path(private) / "events.jsonl")
        for event in result["events"]:
            if not event.get("end_time"):
                event.update(
                    end_time=utc_now(),
                    incomplete=True,
                    error="module execution interrupted",
                )
        try:
            result["final_files"] = snapshot_files(workspace)
            result["evidence_complete"] = (
                result["status"] == "completed"
                and len(
                    [event for event in result["events"] if event["type"] == "tool"]
                )
                == len(task["module_calls"])
                and all(not event.get("incomplete") for event in result["events"])
            )
        except (OSError, ValueError, UnicodeError) as exc:
            result["errors"].append(
                {"kind": "environment", "code": "snapshot_failed", "message": str(exc)}
            )
            result["evidence_complete"] = False
    result.update(
        before_files=before,
        runtime_identity=identity,
        execution_kind="real_module",
        usage={},
    )
    return result
