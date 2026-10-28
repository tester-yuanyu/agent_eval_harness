"""Strict domain value adapters backed by Inspect's native Scorers."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from inspect_ai.model import ModelName, ModelOutput
from inspect_ai.scorer import CORRECT, Target, includes, pattern
from inspect_ai.solver import TaskState

_scores: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "native_scores", default=None
)


@contextmanager
def capture_scores():
    """Collect native metric identities for one domain assertion."""
    values: list[dict[str, Any]] = []
    token = _scores.set(values)
    try:
        yield values
    finally:
        _scores.reset(token)


def canonical_value(value: Any) -> str:
    """Encode structured values without losing types or string whitespace."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _measure(metric: Any, actual: str, expected: str, name: str) -> bool:
    state = TaskState(
        model=ModelName("mockllm/model"),
        sample_id="assertion",
        epoch=1,
        input="",
        messages=[],
        output=ModelOutput.from_content(model="provider", content=actual),
    )
    result = asyncio.run(metric(state, Target(expected)))
    recorded = _scores.get()
    if recorded is not None:
        recorded.append(
            {"scorer": name, "value": result.value, "config": {"ignore_case": False}}
        )
    return result.value == CORRECT


def exact_value(actual: Any, expected: Any) -> bool:
    """Use native pattern scoring; Inspect exact/match normalize punctuation."""
    return _measure(
        pattern(r"\A([\s\S]*)\Z", ignore_case=False),
        canonical_value(actual),
        canonical_value(expected),
        "inspect_ai/pattern",
    )


def contains_text(actual: str, expected: str) -> bool:
    """Check literal, case-sensitive containment with the native scorer."""
    return _measure(
        includes(ignore_case=False), actual, expected, "inspect_ai/includes"
    )


def subset_value(actual: Any, expected: Any) -> bool:
    """Project only requested dictionary keys; native scoring compares values."""
    missing = object()

    def project(value: Any, reference: Any) -> Any:
        if isinstance(reference, dict) and isinstance(value, dict):
            return {k: project(value.get(k, missing), v) for k, v in reference.items()}
        if isinstance(reference, list) and isinstance(value, list):
            return [
                project(v, reference[i]) if i < len(reference) else v
                for i, v in enumerate(value)
            ]
        if value is missing:
            # This key is omitted below instead of using a collidable sentinel value.
            return missing
        return value

    def omit_missing(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: omit_missing(v) for k, v in value.items() if v is not missing}
        if isinstance(value, list):
            return [omit_missing(v) for v in value]
        return value

    return exact_value(omit_missing(project(actual, expected)), expected)
