"""Observation expectation schemas; scoring belongs to the evaluator."""

import json
import re
from typing import Any, Literal, Self

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import Field, field_validator, model_validator
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from .schema_base import StrictModel


def canonical_value(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _local_references(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"$ref", "$dynamicRef"} and (
                not isinstance(child, str) or not child.startswith("#")
            ):
                raise ValueError(
                    "observation schemas cannot resolve external references"
                )
            _local_references(child)
    elif isinstance(value, list):
        for child in value:
            _local_references(child)


def validate_schema_references(schema: dict[str, Any] | bool) -> None:
    """Require every local schema reference to resolve without network access.

    Traverse schema resources, including unused branches, and respect nested
    resource IDs and anchors. Checking only a sample instance misses references
    in branches that the sample does not exercise.
    """
    _local_references(schema)
    resource = Resource.from_contents(schema, default_specification=DRAFT202012)
    base = resource.id() or "urn:agent-evaluator:observation-schema"
    registry = Registry().with_resource(base, resource).crawl()

    def visit(current, resolver) -> None:
        if isinstance(current.contents, dict):
            for key in ("$ref", "$dynamicRef"):
                reference = current.contents.get(key)
                if reference is None:
                    continue
                try:
                    resolved = resolver.lookup(reference)
                except Unresolvable as exc:
                    raise ValueError(
                        f"unresolved local schema reference: {reference}"
                    ) from exc
                if not isinstance(resolved.contents, (dict, bool)):
                    raise ValueError(
                        f"local schema reference must target a schema: {reference}"
                    )
        for child in current.subresources():
            visit(child, resolver.in_subresource(child))

    visit(resource, registry.resolver(base))


class ObservationPredicate(StrictModel):
    path: str
    operator: Literal["equals", "contains", "not_contains", "ends_with", "schema_valid"]
    expected: Any

    @field_validator("path")
    @classmethod
    def valid_pointer(cls, value: str) -> str:
        if (value and not value.startswith("/")) or re.search(r"~(?![01])", value):
            raise ValueError("path must be an RFC 6901 JSON Pointer")
        return value

    @model_validator(mode="after")
    def valid_expected(self) -> Self:
        try:
            canonical_value(self.expected)
        except (ValueError, TypeError) as exc:
            raise ValueError("expected must be a JSON value") from exc
        if self.operator in {"contains", "not_contains", "ends_with"}:
            if not isinstance(self.expected, str):
                raise ValueError("text operators require a string expected value")
        if self.operator == "schema_valid":
            if not isinstance(self.expected, (dict, bool)):
                raise ValueError("schema_valid requires an object or boolean schema")
            try:
                Draft202012Validator.check_schema(self.expected)
            except SchemaError as exc:
                raise ValueError(f"invalid observation schema: {exc.message}") from exc
            validate_schema_references(self.expected)
        return self


class ObservationCheckConfig(StrictModel):
    checks: list[ObservationPredicate] = Field(min_length=1)
    channel: Literal["returned", "independent"] = "returned"
