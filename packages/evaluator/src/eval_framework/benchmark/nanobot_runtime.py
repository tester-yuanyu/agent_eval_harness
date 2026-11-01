"""Isolated-process adapter for the real nanobot SDK.

Only execution inputs cross the process boundary. Filesystem containment is an
application policy, not an operating-system sandbox.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FILE_TOOLS = frozenset({"read_file", "write_file", "edit_file", "list_dir"})
TOKENIZER_URL = (
    "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
)
TOKENIZER_SHA256 = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
EXECUTION_KEYS = frozenset(
    {"id", "prompt", "followups", "fixtures", "allowed_tools", "max_steps"}
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def prepare_tokenizer(config: dict[str, Any]) -> dict[str, str]:
    """Explicit one-time setup; normal Agent runs never download tokenizers."""
    mode = config.get("tokenizer_mode", "cl100k_base")
    if mode == "byte_fallback":
        return {"mode": mode, "source": "nanobot conservative UTF-8 byte fallback"}
    if mode != "cl100k_base":
        raise ValueError("unsupported tokenizer mode")
    cache = Path(
        config.get("tokenizer_cache_dir")
        or Path(tempfile.gettempdir()) / "data-gym-cache"
    )
    path = cache / hashlib.sha1(TOKENIZER_URL.encode()).hexdigest()
    if (
        not path.exists()
        or hashlib.sha256(path.read_bytes()).hexdigest() != TOKENIZER_SHA256
    ):
        # A socket timeout alone resets between reads; a child process gives
        # the complete download a hard wall-clock deadline.
        download = (
            "import sys,urllib.request; "
            "r=urllib.request.urlopen(sys.argv[1],timeout=10); "
            "sys.stdout.buffer.write(r.read(2000001))"
        )
        data = subprocess.check_output(
            [sys.executable, "-c", download, TOKENIZER_URL],
            timeout=25,
        )
        if (
            len(data) > 2_000_000
            or hashlib.sha256(data).hexdigest() != TOKENIZER_SHA256
        ):
            raise ValueError("tokenizer download checksum mismatch")
        cache.mkdir(parents=True, exist_ok=True)
        temporary = cache / (path.name + ".download")
        temporary.write_bytes(data)
        temporary.replace(path)
    return {"mode": mode, "cache_dir": str(cache), "sha256": TOKENIZER_SHA256}


def safe_path(workspace: Path, value: str) -> Path:
    """Reject traversal and every symlink component before touching a file."""
    root = workspace.resolve(strict=True)
    requested = Path(value)
    if ".." in requested.parts:
        raise ValueError("parent traversal is forbidden")
    candidate = requested if requested.is_absolute() else root / requested
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("path is outside the task workspace") from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("symbolic links are forbidden in task workspaces")
    if not candidate.resolve(strict=False).is_relative_to(root):
        raise ValueError("resolved path is outside the task workspace")
    return candidate


def snapshot_files(workspace: Path) -> dict[str, str]:
    """Read the task state independently of the Agent's reported answer."""
    result: dict[str, str] = {}
    for path in sorted(workspace.rglob("*")):
        safe_path(workspace, str(path))
        if path.is_file():
            if path.stat().st_size > 2_000_000:
                raise ValueError("task file exceeds the 2 MB evidence limit")
            result[path.relative_to(workspace).as_posix()] = path.read_text(
                encoding="utf-8"
            )
    return result


def execution_projection(task: dict[str, Any]) -> dict[str, Any]:
    """Fail closed: callers must remove all oracle/reference material first."""
    unexpected = set(task) - EXECUTION_KEYS
    if unexpected:
        raise ValueError(f"non-execution task fields: {', '.join(sorted(unexpected))}")
    allowed = set(task.get("allowed_tools", FILE_TOOLS))
    if not allowed or not allowed <= FILE_TOOLS:
        raise ValueError("only the four benchmark filesystem tools are permitted")
    if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
        raise ValueError("task prompt must be non-empty text")
    return json.loads(json.dumps(task, ensure_ascii=False))


def runtime_identity(config: dict[str, Any]) -> dict[str, Any]:
    root = Path(config["nanobot_root"]).expanduser().resolve(strict=True)
    commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    paths = subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
    ).split(b"\0")
    digest = hashlib.sha256()
    for raw in sorted(set(paths)):
        if not raw:
            continue
        name = os.fsdecode(raw)
        path = root / name
        if not path.is_file() or path.is_symlink():
            continue
        # Runtime code/config templates only, not user logs, credentials or media.
        if not (name.startswith("nanobot/") or name in {"pyproject.toml", "uv.lock"}):
            continue
        if path.suffix not in {
            ".py",
            ".md",
            ".json",
            ".toml",
            ".lock",
            ".yaml",
            ".yml",
            ".j2",
        }:
            continue
        digest.update(raw + b"\0" + path.read_bytes() + b"\0")
    return {
        "agent": "nanobot",
        "source_commit": commit,
        "working_tree_sha256": digest.hexdigest(),
        "source_dirty": bool(
            subprocess.check_output(
                ["git", "-C", str(root), "status", "--porcelain"],
                text=True,
            ).strip()
        ),
        "model": config["model"],
        "base_url": config.get("base_url"),
        "temperature": config.get("temperature", 0),
        "max_tokens": config.get("max_tokens", 2048),
        "max_steps": config.get("max_steps", 12),
        "variant": config.get("variant", "baseline"),
        "adapter_version": "nanobot-file-sdk-v1",
        "isolation": "application-path-policy",
        "tokenizer_mode": config.get("tokenizer_mode", "cl100k_base"),
        "tokenizer_sha256": TOKENIZER_SHA256
        if config.get("tokenizer_mode", "cl100k_base") == "cl100k_base"
        else None,
        "extra_body": config.get("extra_body", {}),
    }


def _journal_events(path: Path) -> list[dict[str, Any]]:
    events: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
                events[event["id"]] = event
            except (ValueError, KeyError):
                continue  # A process can die during the final append.
    return list(events.values())


def _redact(value: Any, secret: str) -> Any:
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]") if secret else value
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()


async def execute_task(
    task: dict[str, Any],
    *,
    config: dict[str, Any],
    workspace: Path,
) -> dict[str, Any]:
    task = execution_projection(task)
    workspace = workspace.resolve(strict=True)
    before = snapshot_files(workspace)
    identity = runtime_identity(config)
    root = Path(config["nanobot_root"]).expanduser().resolve(strict=True)
    python = str(config.get("python") or root / ".venv" / "bin" / "python")
    api_key_env = str(config.get("api_key_env", "DEEPSEEK_API_KEY"))
    secret = os.environ.get(api_key_env, "")
    result: dict[str, Any] = {
        "status": "error",
        "turns": [],
        "before_files": before,
        "final_files": {},
        "events": [],
        "usage": {},
        "errors": [],
        "runtime_identity": identity,
        "evidence_complete": False,
    }
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
        prefix="nanobot-runtime-", dir=workspace.parent
    ) as private:
        runtime_dir = Path(private)
        payload = {
            "task": task,
            "config": config,
            "workspace": str(workspace),
            "runtime_dir": private,
        }
        # Do not inherit ambient provider keys, nanobot configuration, Python
        # startup injection or unrelated connected-service credentials.
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
        env[api_key_env] = secret
        env["PYTHONPATH"] = str(root)
        env["PYTHONUNBUFFERED"] = "1"
        if config.get("tokenizer_cache_dir"):
            env["TIKTOKEN_CACHE_DIR"] = str(config["tokenizer_cache_dir"])
        env["NANOBOT_LLM_TIMEOUT_S"] = str(
            min(float(config.get("timeout_seconds", 180)), 120)
        )
        process = await asyncio.create_subprocess_exec(
            python,
            str(Path(__file__).with_name("nanobot_worker.py")),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=runtime_dir,
            env=env,
            start_new_session=True,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(json.dumps(payload).encode()),
                timeout=float(config.get("timeout_seconds", 180)),
            )
            if process.returncode == 0:
                result.update(json.loads(stdout))
            else:
                result["errors"].append(
                    {
                        "kind": "environment",
                        "code": "worker_exit",
                        "message": f"nanobot worker exited {process.returncode}",
                    }
                )
        except TimeoutError:
            await _terminate(process)
            result["status"] = "timeout"
            result["stop_reason"] = "timeout"
            result["errors"].append(
                {
                    "kind": "agent",
                    "code": "task_timeout",
                    "message": "task deadline exceeded",
                }
            )
        except asyncio.CancelledError:
            await _terminate(process)
            raise
        except (ValueError, OSError) as exc:
            await _terminate(process)
            result["errors"].append(
                {"kind": "environment", "code": type(exc).__name__, "message": str(exc)}
            )
        result["events"] = _journal_events(runtime_dir / "events.jsonl")
        for event in result["events"]:
            if not event.get("end_time"):
                event.update(
                    end_time=utc_now(), error="execution interrupted", incomplete=True
                )
        if not result["turns"]:
            result["turns"] = [
                {
                    "input": event["input"],
                    "output": event.get("output", ""),
                    "snapshot": event.get("snapshot"),
                }
                for event in result["events"]
                if event["type"] == "turn"
            ]
        try:
            result["final_files"] = snapshot_files(workspace)
            result["evidence_complete"] = bool(result["events"])
        except (OSError, ValueError, UnicodeError) as exc:
            result["errors"].append(
                {"kind": "environment", "code": "snapshot_failed", "message": str(exc)}
            )
        result["before_files"] = before
        result["runtime_identity"] = identity
        usage: dict[str, int] = {}
        for event in result["events"]:
            if event["type"] == "generation":
                for key, count in event.get("usage", {}).items():
                    if isinstance(count, (int, float)):
                        usage[key] = usage.get(key, 0) + count
        result["usage"] = usage
    return _redact(result, secret)
