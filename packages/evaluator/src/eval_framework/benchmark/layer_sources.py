"""Source closure for new runtime identities after the layered extraction.

Historical saved identities are not rewritten. Package-relative labels work
both in editable checkouts and in a clean wheel installation.
"""

from __future__ import annotations

from pathlib import Path

from eval_contracts import benchmark as task_contract
from eval_contracts import trace as trace_contract


def layer_source_paths() -> dict[str, Path]:
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "benchmark" / "layer_sources.py",
        root / "benchmark" / "schema.py",
        root / "plugins" / "protocols.py",
        root / "plugins" / "models.py",
    ]
    for directory in (
        "environments", "harness", "aggregator", "orchestration", "benchmark/scorers"
    ):
        paths.extend(sorted((root / directory).rglob("*.py")))
    result = {
        "eval_framework/" + path.relative_to(root).as_posix(): path
        for path in paths
    }
    result["eval_contracts/benchmark.py"] = Path(task_contract.__file__)
    result["eval_contracts/trace.py"] = Path(trace_contract.__file__)
    return result
