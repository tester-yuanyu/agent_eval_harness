"""Benchmark 源码闭包；保留历史标签与 JSON 摘要算法。"""

from __future__ import annotations

import hashlib
from importlib.metadata import version
from pathlib import Path

from capability_snapshot_kit.hashing import sha256_json as digest


def code_identity(names: list[str]) -> str:
    from .layer_sources import layer_source_paths

    root = Path(__file__).parent
    sources = {name: root / name for name in names}
    sources.update(layer_source_paths())
    return digest(
        {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in sources.items()
        }
    )


def scoring_identity() -> dict:
    from .metrics import METRICS_VERSION
    from .tasks import GRADER_VERSION

    return {
        "version": METRICS_VERSION,
        "deepeval": version("deepeval"),
        "oracle": GRADER_VERSION,
        "source_sha256": code_identity(
            [
                "metrics.py",
                "oracle.py",
                "tasks.py",
                "trajectory.py",
                "module_oracle.py",
                "recovery_scoring.py",
                "repetition.py",
                "agentic_metrics.py",
                "agentic_metrics_worker.py",
            ]
        ),
    }
