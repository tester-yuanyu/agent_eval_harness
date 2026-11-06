"""Isolated-process adapter for the real nanobot SDK.

Only execution inputs cross the process boundary. Filesystem containment is an
application policy, not an operating-system sandbox.
"""

from __future__ import annotations

import hashlib
import json
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
    if __package__:
        from ...benchmark.inspect_docker import source_digest, source_files
    else:  # Optional workers import this module under their own interpreter.
        from inspect_docker import source_digest, source_files

    source_hash = source_digest(source_files(root))
    return {
        "agent": "nanobot",
        "source_commit": commit,
        "working_tree_sha256": source_hash,
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
        "adapter_version": "nanobot-inspect-bridge-v2",
        "isolation": "docker"
        if config.get("sandbox", "docker") == "docker"
        else "local-no-os-isolation",
        "tokenizer_mode": config.get("tokenizer_mode", "cl100k_base"),
        "tokenizer_sha256": TOKENIZER_SHA256
        if config.get("tokenizer_mode", "cl100k_base") == "cl100k_base"
        else None,
        "extra_body": config.get("extra_body", {}),
    }
