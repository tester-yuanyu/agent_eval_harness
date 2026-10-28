"""Strict, snapshot-free facts supplied by one concrete Agent adapter."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from capability_snapshot_kit.models import (
    LOCAL_ID_PATTERN,
    CapabilityClaimV3,
    StrictCapabilityModelV3,
)

MODULE_ROLE_PATTERN = r"^[a-z][a-z0-9_]*$"
BINDING_KEY_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"


class AgentFactsV3(StrictCapabilityModelV3):
    agent_id: str = Field(pattern=LOCAL_ID_PATTERN)
    agent_version: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    entrypoints: list[str]
    runtime_bindings: dict[str, str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    runtime_versions: dict[str, str]

    @field_validator("runtime_bindings")
    @classmethod
    def validate_runtime_bindings(cls, value: dict[str, str]) -> dict[str, str]:
        for key, binding in value.items():
            if not _matches_binding_key(key) or not binding:
                raise ValueError("runtime bindings require valid non-empty entries")
        return value


class ModuleFactV3(StrictCapabilityModelV3):
    module_id: str = Field(pattern=LOCAL_ID_PATTERN)
    contract_version: str = Field(min_length=1)
    roles: tuple[str, ...] = Field(min_length=1)
    responsibility: str = Field(min_length=1)
    component_versions: dict[str, str] = Field(min_length=1)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    capabilities: tuple[CapabilityClaimV3, ...]
    module_ids: tuple[str, ...]
    intent_ids: tuple[str, ...]
    tool_ids: tuple[str, ...]
    execution_boundary_ids: tuple[str, ...]
    trace_event_types: tuple[str, ...]

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_local_values(value, "module role")

    @field_validator("module_ids")
    @classmethod
    def validate_module_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _typed_ids(value, "module")

    @field_validator("intent_ids")
    @classmethod
    def validate_intent_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _typed_ids(value, "intent")

    @field_validator("tool_ids")
    @classmethod
    def validate_tool_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _typed_ids(value, "tool")

    @field_validator("execution_boundary_ids")
    @classmethod
    def validate_boundary_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _typed_ids(value, "boundary")


class IntentFactV3(StrictCapabilityModelV3):
    intent_id: str = Field(pattern=LOCAL_ID_PATTERN)
    contract_version: str = Field(min_length=1)
    module_role: str = Field(pattern=MODULE_ROLE_PATTERN)
    parameters_schema: dict[str, Any]
    parameter_semantics: dict[str, Any]
    decision_rules: dict[str, Any]
    semantic_rules: dict[str, Any]
    required_tool_name: str | None = Field(default=None, pattern=LOCAL_ID_PATTERN)
    capabilities: tuple[CapabilityClaimV3, ...]


class ToolFactV3(StrictCapabilityModelV3):
    tool_name: str = Field(pattern=LOCAL_ID_PATTERN)
    contract_version: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    implementation_profile: Literal["production", "evaluation_adapter", "test_fixture"]
    registered: Literal[True]
    function_schema: dict[str, Any]
    parameter_semantics: dict[str, Any]
    combination_rules: dict[str, Any]
    batch_behavior: dict[str, Any]
    preconditions: list[str]
    result_protocols: dict[str, Any]
    permission_requirements: list[str]
    requires_confirmation: bool
    risk_level: Literal["low", "medium", "high"]
    idempotency_rules: dict[str, Any]
    side_effects: list[str]
    retry_policy: dict[str, Any]
    simulation_protocol: dict[str, Any] | None
    simulation_capabilities: list[str]
    observation_interfaces: list[str]
    capabilities: tuple[CapabilityClaimV3, ...]


class EvidenceFactV3(StrictCapabilityModelV3):
    evidence_id: str = Field(pattern=LOCAL_ID_PATTERN)
    producer_module_roles: tuple[str, ...]
    production_timing: str = Field(min_length=1)
    payload_schema: dict[str, Any]
    observation_interface: str = Field(min_length=1)
    event_types: tuple[str, ...]
    applicable_result_paths: tuple[str, ...]
    availability: CapabilityClaimV3

    @field_validator("producer_module_roles")
    @classmethod
    def validate_producer_roles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_local_values(value, "module role")


def _matches_binding_key(value: str) -> bool:
    parts = value.split(".")
    return len(parts) >= 2 and all(
        part
        and part[0].isalpha()
        and all(
            character.islower() or character.isdigit() or character == "_"
            for character in part
        )
        for part in parts
    )


def _unique_local_values(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} values must be unique")
    for value in values:
        if not value or not value[0].isalpha() or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
            for character in value
        ):
            raise ValueError(f"invalid {label}: {value}")
    return values


def _typed_ids(values: tuple[str, ...], prefix: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{prefix} IDs must be unique")
    if any(not value.startswith(f"{prefix}.") for value in values):
        raise ValueError(f"IDs must use the {prefix}. prefix")
    return values
