"""Isolated single-model decision adapter; generated tool calls are never executed."""

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
    _redact,
    _terminate,
    runtime_identity,
    snapshot_files,
    utc_now,
)


def decision_execution_projection(task: dict[str, Any]) -> dict[str, Any]:
    unexpected = set(task) - EXECUTION_KEYS - {"decision_context"}
    if unexpected:
        raise ValueError(f"non-execution decision fields: {sorted(unexpected)}")
    allowed = task.get("allowed_tools", list(FILE_TOOLS))
    if (
        not isinstance(allowed, list)
        or not allowed
        or any(name not in FILE_TOOLS for name in allowed)
    ):
        raise ValueError("decision execution permits only filesystem tool schemas")
    if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
        raise ValueError("decision prompt must be nonempty text")
    if not isinstance(task.get("decision_context", ""), str) or task.get("followups"):
        raise ValueError("decision execution requires public text context and one turn")
    return json.loads(json.dumps(task, ensure_ascii=False))


def decision_identity(config: dict[str, Any]) -> dict[str, Any]:
    identity = runtime_identity(config)
    identity.update(
        adapter_version="nanobot-decision-v1",
        execution_kind="real_model_decision",
        decision_boundary="one-provider-chat-call; no AgentLoop or tool execution",
        decision_system_version="next-action-v1",
    )
    return identity


async def execute_decision_task(
    task: dict[str, Any], *, config: dict[str, Any], workspace: Path
) -> dict[str, Any]:
    task = decision_execution_projection(task)
    workspace = workspace.resolve(strict=True)
    root = Path(config["nanobot_root"]).expanduser().resolve(strict=True)
    identity = decision_identity(config)
    before = snapshot_files(workspace)
    result: dict[str, Any] = {
        "status": "error",
        "execution_kind": "real_model_decision",
        "turns": [],
        "events": [],
        "before_files": before,
        "final_files": before,
        "usage": {},
        "errors": [],
        "evidence_complete": False,
        "runtime_identity": identity,
        "decision": None,
    }
    api_key_env = str(config.get("api_key_env", "DEEPSEEK_API_KEY"))
    secret = os.environ.get(api_key_env, "")
    if not secret:
        result["errors"] = [
            {
                "kind": "environment",
                "code": "missing_api_key",
                "message": f"missing {api_key_env}",
            }
        ]
        return result
    with tempfile.TemporaryDirectory(
        prefix="nanobot-decision-", dir=workspace.parent
    ) as private:
        payload = {
            "task": task,
            "config": config,
            "workspace": str(workspace),
            "runtime_dir": private,
        }
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
        env[api_key_env] = secret
        env["NANOBOT_LLM_TIMEOUT_S"] = str(
            min(float(config.get("timeout_seconds", 90)), 120)
        )
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                str(config.get("python") or root / ".venv/bin/python"),
                str(Path(__file__).with_name("decision_worker.py")),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=private,
                env=env,
                start_new_session=True,
            )
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(json.dumps(payload).encode()),
                timeout=float(config.get("timeout_seconds", 90)),
            )
            if process.returncode == 0:
                result.update(json.loads(stdout))
            else:
                result["errors"].append(
                    {
                        "kind": "environment",
                        "code": "decision_worker_exit",
                        "message": f"decision worker exited {process.returncode}",
                    }
                )
        except TimeoutError:
            if process is not None:
                await _terminate(process)
            result.update(status="timeout", stop_reason="timeout")
            result["errors"].append(
                {
                    "kind": "provider",
                    "code": "decision_timeout",
                    "message": "single model request deadline exceeded",
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
                    error="decision request interrupted",
                )
        try:
            result["final_files"] = snapshot_files(workspace)
            generations = [
                event for event in result["events"] if event["type"] == "generation"
            ]
            result["evidence_complete"] = (
                result["status"] == "completed"
                and len(generations) == 1
                and all(not event.get("incomplete") for event in result["events"])
            )
            result["usage"] = (
                dict(generations[0].get("usage", {})) if len(generations) == 1 else {}
            )
        except (OSError, ValueError, UnicodeError) as exc:
            result["errors"].append(
                {"kind": "environment", "code": "snapshot_failed", "message": str(exc)}
            )
            result["evidence_complete"] = False
    result.update(
        before_files=before,
        runtime_identity=identity,
        execution_kind="real_model_decision",
    )
    return _redact(result, secret)
