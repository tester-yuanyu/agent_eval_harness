"""Compatible, read-only loading for saved evaluation results."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .schema_base import StrictModel
from .schemas import EvaluationRunResult


class LoadedRunResult(StrictModel):
    result: EvaluationRunResult
    source_path: str
    sha256: str


def load_run_result(path: str | Path) -> LoadedRunResult:
    source = Path(path).expanduser().resolve()
    if source.is_dir():
        source = source / "results.json"
    raw = source.read_bytes()
    result = EvaluationRunResult.model_validate_json(raw)
    if (source.parent / "execution.json").is_file() and (
        source.parent / "evidence"
    ).is_dir():
        result = result.model_copy(update={"run_directory": str(source.parent)})
    return LoadedRunResult(
        result=result,
        source_path=str(source),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
