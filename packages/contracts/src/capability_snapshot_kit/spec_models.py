"""Strict models for portable Markdown Capability Specs."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from capability_snapshot_kit.models import (
    CAPABILITY_KEY_PATTERN,
    LOCAL_ID_PATTERN,
    StrictCapabilityModelV3,
)

MODULE_ROLE_PATTERN = r"^[a-z][a-z0-9_]*$"
BINDING_KEY_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"


class SpecProviderV3(StrictCapabilityModelV3):
    role: Literal["selected_intent", "selected_tool", "module_role"]
    module_role: str | None = Field(default=None, pattern=MODULE_ROLE_PATTERN)

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.role == "module_role" and self.module_role is None:
            raise ValueError("module_role provider requires module_role")
        if self.role != "module_role" and self.module_role is not None:
            raise ValueError("selected provider cannot declare module_role")
        return self


class RequirementSpecV3(StrictCapabilityModelV3):
    requirement_id: str = Field(pattern=LOCAL_ID_PATTERN)
    capability_key: str = Field(pattern=CAPABILITY_KEY_PATTERN)
    provider: SpecProviderV3
    mandatory: bool = True
    evidence_ids: list[str]

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: list[str]) -> list[str]:
        return _typed_ids(value, "evidence")


class ChainNodeSpecV3(StrictCapabilityModelV3):
    node_id: str = Field(pattern=LOCAL_ID_PATTERN)
    capability_key: str = Field(pattern=CAPABILITY_KEY_PATTERN)
    provider: SpecProviderV3
    depends_on: list[str]
    inputs: list[str]
    outputs: list[str]
    stop_conditions: list[str]
    state_reads: list[str]
    state_writes: list[str]


class ProtocolSpecV3(StrictCapabilityModelV3):
    spec_id: Literal["protocol.capability_v3"]
    version: str = Field(min_length=1)
    snapshot_format_version: Literal["3.0"]
    agent_capability_groups: dict[str, list[str]]
    documentation: str = Field(min_length=1, exclude=True)

    @field_validator("agent_capability_groups")
    @classmethod
    def validate_capability_groups(
        cls, value: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        for parent, children in value.items():
            _capability_key(parent)
            if not children:
                raise ValueError(f"{parent} must contain child capabilities")
            if len(children) != len(set(children)):
                raise ValueError(f"{parent} child capabilities must be unique")
            for child in children:
                _capability_key(child)
        return value


class ScopeSpecV3(StrictCapabilityModelV3):
    snapshot_id: str = Field(pattern=r"^scope\.[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1)
    inputs: list[str]
    outputs: list[str]
    entrypoint_binding: str = Field(pattern=BINDING_KEY_PATTERN)
    stop_binding: str = Field(pattern=BINDING_KEY_PATTERN)
    module_roles: list[str]
    evidence_ids: list[str]
    boundary_id: str = Field(pattern=r"^boundary\.[a-z][a-z0-9_]*$")
    requirements: list[RequirementSpecV3]
    completion_condition: str = Field(min_length=1)
    unresolved_behavior: str = Field(min_length=1)
    documentation: str = Field(min_length=1, exclude=True)

    @field_validator("module_roles")
    @classmethod
    def validate_module_roles(cls, value: list[str]) -> list[str]:
        return _local_ids(value, "module role")

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: list[str]) -> list[str]:
        return _typed_ids(value, "evidence")


class ChainSpecV3(StrictCapabilityModelV3):
    snapshot_id: str = Field(pattern=r"^chain\.[a-z][a-z0-9_]*$")
    category: Literal["critical", "end_to_end"]
    description: str = Field(min_length=1)
    nodes: list[ChainNodeSpecV3]
    module_roles: list[str]
    evidence_ids: list[str]
    boundary_id: str = Field(pattern=r"^boundary\.[a-z][a-z0-9_]*$")
    requirements: list[RequirementSpecV3]
    branches: list[dict[str, str]]
    completion_condition: str = Field(min_length=1)
    documentation: str = Field(min_length=1, exclude=True)

    @field_validator("module_roles")
    @classmethod
    def validate_module_roles(cls, value: list[str]) -> list[str]:
        return _local_ids(value, "module role")

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: list[str]) -> list[str]:
        return _typed_ids(value, "evidence")


class EvidenceSpecV3(StrictCapabilityModelV3):
    snapshot_id: str = Field(pattern=r"^evidence\.[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1)
    consumer_roles: list[str]
    required: bool
    applicable_result_paths: list[str]
    documentation: str = Field(min_length=1, exclude=True)


class BoundarySpecV3(StrictCapabilityModelV3):
    snapshot_id: str = Field(pattern=r"^boundary\.[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1)
    entry_binding: str = Field(pattern=BINDING_KEY_PATTERN)
    stop_binding: str = Field(pattern=BINDING_KEY_PATTERN)
    module_roles: list[str]
    evidence_ids: list[str]
    terminal_condition_template: str = Field(min_length=1)
    no_overrun_rule_template: str = Field(min_length=1)
    documentation: str = Field(min_length=1, exclude=True)

    @field_validator("module_roles")
    @classmethod
    def validate_module_roles(cls, value: list[str]) -> list[str]:
        return _local_ids(value, "module role")

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: list[str]) -> list[str]:
        return _typed_ids(value, "evidence")


class CapabilitySpecPackV3(StrictCapabilityModelV3):
    protocol: ProtocolSpecV3
    scopes: dict[str, ScopeSpecV3]
    chains: dict[str, ChainSpecV3]
    evidence: dict[str, EvidenceSpecV3]
    boundaries: dict[str, BoundarySpecV3]


def _local_ids(values: list[str], label: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} values must be unique")
    for value in values:
        if not value or not value[0].isalpha() or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
            for character in value
        ):
            raise ValueError(f"invalid {label}: {value}")
    return values


def _typed_ids(values: list[str], prefix: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{prefix} IDs must be unique")
    for value in values:
        if not value.startswith(f"{prefix}."):
            raise ValueError(f"IDs must use the {prefix}. prefix")
    return values


def _capability_key(value: str) -> str:
    import re

    if re.fullmatch(CAPABILITY_KEY_PATTERN, value) is None:
        raise ValueError(f"invalid capability key: {value}")
    return value
