"""Frozen predicates over observations; expectation data stays in the Scorer."""

from __future__ import annotations

import re
from typing import Any

from eval_contracts.observation_assertions import (
    ObservationCheckConfig as ObservationCheckConfig,
)
from eval_contracts.observation_assertions import (
    ObservationPredicate as ObservationPredicate,
)
from eval_contracts.observation_assertions import _local_references as _local_references
from eval_contracts.observation_assertions import (
    validate_schema_references as validate_schema_references,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry

from .native_scoring import contains_text, exact_value

_MISSING = object()


def _resolve(value: Any, pointer: str) -> Any:
    if not pointer:
        return value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value.get(token, _MISSING)
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
            index = int(token)
            value = value[index] if index < len(value) else _MISSING
        else:
            return _MISSING
        if value is _MISSING:
            return _MISSING
    return value


def _matches(actual: Any, predicate: ObservationPredicate) -> bool:
    expected = predicate.expected
    if predicate.operator == "equals":
        return exact_value(actual, expected)
    if predicate.operator == "schema_valid":
        try:
            Draft202012Validator(expected, registry=Registry()).validate(actual)
        except ValidationError:
            return False
        return True
    if not isinstance(actual, str):
        return False
    if predicate.operator == "contains":
        return contains_text(actual, expected)
    if predicate.operator == "not_contains":
        return not contains_text(actual, expected)
    # Empty suffix matches every string; native exact_value still records the check.
    suffix = actual[-len(expected) :] if expected else ""
    return exact_value(suffix, expected)


def evaluate_observations(
    observations: dict[str, Any] | None,
    config: ObservationCheckConfig | dict[str, Any],
) -> tuple[bool | None, Any, Any, list[str], str]:
    """Evaluate all available values; missing values cannot erase a known failure.

    The caller chooses the trusted channel. This function cannot turn returned
    Agent claims into independent evidence by inspecting the values themselves.
    """
    parsed = ObservationCheckConfig.model_validate(config)
    missing, mismatches, actual, refs = [], [], [], []
    for predicate in parsed.checks:
        value = (
            _resolve(observations, predicate.path)
            if observations is not None
            else _MISSING
        )
        if value is _MISSING:
            missing.append(predicate.path)
            actual.append({"path": predicate.path, "available": False})
            continue
        actual.append({"path": predicate.path, "available": True, "value": value})
        refs.append(f"observations:{parsed.channel}:{predicate.path}")
        if not _matches(value, predicate):
            mismatches.append(predicate.path)
    passed = False if mismatches else (None if missing else True)
    messages = []
    if mismatches:
        messages.append(f"Observation mismatch: {mismatches}")
    if missing:
        messages.append(f"Observations unavailable: {missing}")
    return passed, parsed.model_dump(mode="json"), actual, refs, "; ".join(messages)
