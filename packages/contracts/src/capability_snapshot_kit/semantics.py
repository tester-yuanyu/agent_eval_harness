"""Agent 无关的显式语义身份；只接受 JSON 数据，不推测任意对象行为。"""

from __future__ import annotations

import json
import math
from typing import Any, Protocol

from pydantic import ConfigDict, Field, field_validator

from .base import ProtocolModel


class SemanticDescriptor(ProtocolModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    component_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    parameters: dict[str, Any]

    @field_validator("component_id", "version")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("semantic identity must not be blank")
        return value

    @field_validator("parameters", mode="before")
    @classmethod
    def json_parameters(cls, value):
        _check_json(value)
        return value


def _check_json(value):
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _check_json(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _check_json(item)
        return
    raise ValueError("semantic parameters must be finite JSON values with string keys")


class SemanticProvider(Protocol):
    def snapshot_semantics(self) -> dict[str, Any]: ...


def validate_semantics(value: dict[str, Any]) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("semantic description must be a plain JSON dictionary")
    record = SemanticDescriptor.model_validate(value)
    # Independent copy: mutable caller-owned configuration cannot change the record.
    return json.loads(record.model_dump_json())


def describe_semantics(component: SemanticProvider) -> dict[str, Any]:
    describe = getattr(component, "snapshot_semantics", None)
    if not callable(describe):
        raise ValueError(  # noqa: TRY004 - a CLI-reportable contract validation error
            "custom component must provide snapshot_semantics()"
        )
    return validate_semantics(describe())
