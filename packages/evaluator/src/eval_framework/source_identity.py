"""Content identities for the actual local runtime, independent of checkout path."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from importlib.metadata import version
from pathlib import Path
from typing import Any

from capability_snapshot_kit import hashing
from eval_contracts import benchmark as task_contract
from eval_contracts import observation_assertions
from eval_contracts import trace as trace_contract

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
    ".md",
}

_checkpoint: ContextVar[tuple | None] = ContextVar("identity_checkpoint", default=None)


def _owner() -> tuple:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return threading.get_ident(), task


@contextmanager
def identity_checkpoint():
    """Capture bytes once within ONE synchronous identity validation boundary.

    Never span execution/await or reuse between pre/post checks. No path/mtime
    cache survives this scope; each new checkpoint rereads the current bytes.
    Child tasks/threads cannot inherit the parent's captured view.
    """
    token = _checkpoint.set((_owner(), {}))
    try:
        yield
    finally:
        _checkpoint.reset(token)


def source_bytes(path: Path) -> bytes:
    path = Path(path)
    snapshot = _checkpoint.get()
    if snapshot is None or snapshot[0] != _owner():
        return path.read_bytes()
    key = path.absolute()
    if key not in snapshot[1]:
        snapshot[1][key] = path.read_bytes()
    return snapshot[1][key]


def capture_identity(function):
    """Share an enclosing checkpoint or make a fresh snapshot for a direct call."""

    @wraps(function)
    def capture(*args, **kwargs):
        snapshot = _checkpoint.get()
        if snapshot is not None and snapshot[0] == _owner():
            return function(*args, **kwargs)
        with identity_checkpoint():
            return function(*args, **kwargs)

    return capture


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
            digest.update(hashlib.sha256(source_bytes(path)).digest())
    return digest.hexdigest()


@capture_identity
def runtime_identity() -> dict[str, Any]:
    """Identify installed Inspect and extension sources without exposing paths."""
    import agent_trace_sdk
    import capability_snapshot_kit
    import eval_contracts
    import inspect_ai

    inspect_root = Path(inspect_ai.__file__).resolve().parent
    return {
        "source": {
            "distribution": "inspect_ai",
            "distribution_version": version("inspect_ai"),
            "runtime_sha256": content_identity(inspect_root),
        },
        "extension_sha256": content_identity(Path(__file__).resolve().parent),
        "contracts_sha256": content_identity(
            Path(eval_contracts.__file__).resolve().parent
        ),
        "capability_protocol_sha256": content_identity(
            Path(capability_snapshot_kit.__file__).resolve().parent
        ),
        "evidence_sdk_sha256": content_identity(
            Path(agent_trace_sdk.__file__).resolve().parent
        ),
    }


def layer_source_paths() -> dict[str, Path]:
    root = Path(__file__).resolve().parent
    paths = [
        root / "benchmark" / "layer_sources.py",
        root / "benchmark" / "schema.py",
        root / "benchmark" / "identity.py",
        root / "benchmark" / "run_context.py",
        root / "plugins" / "protocols.py",
        root / "plugins" / "models.py",
    ]
    for directory in (
        "environments",
        "harness",
        "aggregator",
        "orchestration",
        "benchmark/scorers",
        "benchmark/domains",
        "benchmark/datasets",
        "integrations",
    ):
        paths.extend(sorted((root / directory).rglob("*.py")))
    result = {
        "eval_framework/" + path.relative_to(root).as_posix(): path for path in paths
    }
    result["eval_contracts/benchmark.py"] = Path(task_contract.__file__)
    result["eval_contracts/trace.py"] = Path(trace_contract.__file__)
    result["eval_contracts/observation_assertions.py"] = Path(
        observation_assertions.__file__
    )
    result["capability_snapshot_kit/hashing.py"] = Path(hashing.__file__)
    return result


def runtime_layer_source_paths() -> dict[str, dict[str, Path]]:
    """Versioned execution-only source closure, separate from historical closure."""
    root = Path(__file__).resolve().parent
    groups = {
        "harness": [root / "harness"],
        "environment": [root / "environments", root / "integrations"],
        "model": [root / "runtime_model.py", root / "source_identity.py"],
        "contracts": [Path(task_contract.__file__), Path(trace_contract.__file__)],
    }
    result = {}
    for group, locations in groups.items():
        paths = [
            path
            for location in locations
            for path in (
                sorted(location.rglob("*.py")) if location.is_dir() else [location]
            )
        ]
        result[group] = {
            (
                ("eval_framework/" + path.relative_to(root).as_posix())
                if path.is_relative_to(root)
                else "eval_contracts/" + path.name
            ): path
            for path in paths
        }
    return result


def runtime_layer_identity() -> dict[str, Any]:
    return {
        "version": "execution-layers-v1",
        "layers": {
            group: {
                name: hashlib.sha256(source_bytes(path)).hexdigest()
                for name, path in paths.items()
            }
            for group, paths in runtime_layer_source_paths().items()
        },
    }
