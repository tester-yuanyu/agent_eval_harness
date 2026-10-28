"""Content identities for the actual local runtime, independent of checkout path."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

UPSTREAM_COMMIT = "dfcb169e1cb170a8fbe2c37a0e3befc45c2c2b85"
_RUNTIME_SUFFIXES = {
    ".py",
    ".json",
    ".jsonl",
    ".txt",
    ".yaml",
    ".yml",
    ".jinja",
    ".j2",
    ".toml",
}


def content_identity(root: Path) -> str:
    """Hash runtime sources and templates, including uncommitted changes."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if (
            path.is_file()
            and path.suffix in _RUNTIME_SUFFIXES
            and "__pycache__" not in path.parts
        ):
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def runtime_identity() -> dict[str, Any]:
    """Identify installed Inspect and extension sources without exposing paths."""
    import agent_trace_sdk
    import inspect_ai

    inspect_root = Path(inspect_ai.__file__).resolve().parent
    repo = inspect_root.parent.parent
    head = None
    if (repo / ".git").exists():
        completed = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        head = completed.stdout.strip()
    return {
        "source": {
            "upstream_commit": UPSTREAM_COMMIT,
            "checkout_commit": head,
            "runtime_sha256": content_identity(inspect_root),
        },
        "extension_sha256": content_identity(Path(__file__).resolve().parent),
        "evidence_sdk_sha256": content_identity(
            Path(agent_trace_sdk.__file__).resolve().parent
        ),
    }
