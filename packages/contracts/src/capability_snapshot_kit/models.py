"""Strict, Agent-independent models for Capability Snapshot Protocol v3."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from capability_snapshot_kit.base import ProtocolModel

SHA256_PATTERN = r"^[0-9a-f]{64}$"
TYPED_ID_PATTERN_V3 = (
    r"^(agent|module|intent|tool|scope|chain|evidence|boundary)\."
    r"[a-z][a-z0-9_]*$"
)
CAPABILITY_KEY_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"
LOCAL_ID_PATTERN = r"^[a-z][a-z0-9_]*$"


class SnapshotTypeV3(StrEnum):
    AGENT = "agent"
    MODULE = "module"
    INTENT = "intent"
    TOOL = "tool"
    SCOPE = "scope"
    CHAIN = "chain"
    EVIDENCE = "evidence"
    BOUNDARY = "boundary"


class SupportStatusV3(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class StrictCapabilityModelV3(ProtocolModel):
    model_config = ConfigDict(extra="forbid")


class SnapshotReferenceV3(StrictCapabilityModelV3):
    snapshot_id: str = Field(pattern=TYPED_ID_PATTERN_V3)
    snapshot_type: SnapshotTypeV3
    snapshot_format_version: Literal["3.0"]
    contract_version: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=SHA256_PATTERN)
    path: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def validate_relative_posix_json_path(cls, value: str) -> str:
        if "\\" in value or "//" in value:
            raise ValueError("path must use non-empty POSIX segments")
        path = PurePosixPath(value)
        if path.is_absolute() or any(
            part in {"", ".", ".."} for part in value.split("/")
        ):
            raise ValueError("path must be relative without dot segments")
        if path.suffix != ".json":
            raise ValueError("path must identify a JSON file")
        return value

    @model_validator(mode="after")
    def validate_id_matches_type(self) -> Self:
        if self.snapshot_id.split(".", 1)[0] != self.snapshot_type.value:
            raise ValueError("snapshot_id prefix must match snapshot_type")
        return self


class CapabilityProviderV3(StrictCapabilityModelV3):
    role: Literal["selected_intent", "selected_tool", "snapshot"]
    snapshot_id: str | None

    @model_validator(mode="after")
    def validate_role_binding(self) -> Self:
        if self.role == "snapshot" and self.snapshot_id is None:
            raise ValueError("snapshot provider requires snapshot_id")
        if self.role != "snapshot" and self.snapshot_id is not None:
            raise ValueError("selected providers must be bound during resolution")
        return self


class CapabilityRequirementV3(StrictCapabilityModelV3):
    requirement_id: str = Field(pattern=LOCAL_ID_PATTERN)
    capability_key: str = Field(pattern=CAPABILITY_KEY_PATTERN)
    provider: CapabilityProviderV3
    mandatory: bool
    evidence_ids: list[str]

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: list[str]) -> list[str]:
        return _validate_typed_ids(value, "evidence")


class CapabilityClaimV3(StrictCapabilityModelV3):
    capability_key: str = Field(pattern=CAPABILITY_KEY_PATTERN)
    support_status: SupportStatusV3
    evidence_ids: list[str]
    reason: str | None

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: list[str]) -> list[str]:
        return _validate_typed_ids(value, "evidence")

    @model_validator(mode="after")
    def validate_status_evidence_and_reason(self) -> Self:
        if self.support_status == SupportStatusV3.SUPPORTED:
            if not self.evidence_ids:
                raise ValueError("supported capability requires Evidence")
            if self.reason is not None:
                raise ValueError("supported capability reason must be null")
        elif self.reason is None or not self.reason.strip():
            raise ValueError(
                f"{self.support_status.value} capability requires a reason"
            )
        return self


def _validate_typed_ids(values: list[str], prefix: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{prefix} IDs must be unique")
    expected = f"{prefix}."
    for value in values:
        if not value.startswith(expected):
            raise ValueError(f"IDs must use the {expected} prefix")
    return values


def _validate_references(
    values: list[SnapshotReferenceV3],
    expected_type: SnapshotTypeV3,
) -> list[SnapshotReferenceV3]:
    ids = [value.snapshot_id for value in values]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{expected_type.value} references must be unique")
    if any(value.snapshot_type != expected_type for value in values):
        raise ValueError(f"references must target {expected_type.value} snapshots")
    return values


class SnapshotBaseV3(StrictCapabilityModelV3):
    snapshot_id: str = Field(pattern=TYPED_ID_PATTERN_V3)
    snapshot_type: SnapshotTypeV3
    snapshot_format_version: Literal["3.0"]
    contract_version: str = Field(min_length=1)
    source_hashes: dict[str, str] = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("source_hashes")
    @classmethod
    def validate_source_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if any(not name or not _is_sha256(digest) for name, digest in value.items()):
            raise ValueError("source_hashes must contain named SHA-256 values")
        return value

    @model_validator(mode="after")
    def validate_envelope_type(self) -> Self:
        if self.snapshot_id.split(".", 1)[0] != self.snapshot_type.value:
            raise ValueError("snapshot_id prefix must match snapshot_type")
        return self


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


class AgentSnapshotV3(SnapshotBaseV3):
    snapshot_type: Literal[SnapshotTypeV3.AGENT]
    agent_id: str = Field(pattern=LOCAL_ID_PATTERN)
    agent_version: str = Field(min_length=1)
    entrypoints: list[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    capabilities: list[CapabilityClaimV3]
    module_refs: list[SnapshotReferenceV3]
    intent_refs: list[SnapshotReferenceV3]
    tool_refs: list[SnapshotReferenceV3]
    scope_refs: list[SnapshotReferenceV3]
    chain_refs: list[SnapshotReferenceV3]
    evidence_refs: list[SnapshotReferenceV3]
    boundary_refs: list[SnapshotReferenceV3]
    runtime_versions: dict[str, str]
    capability_bundle_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_agent_identity(self) -> Self:
        if self.snapshot_id != f"agent.{self.agent_id}":
            raise ValueError("agent snapshot_id must match agent_id")
        return self

    @field_validator("module_refs")
    @classmethod
    def validate_module_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.MODULE)

    @field_validator("intent_refs")
    @classmethod
    def validate_intent_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.INTENT)

    @field_validator("tool_refs")
    @classmethod
    def validate_tool_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.TOOL)

    @field_validator("scope_refs")
    @classmethod
    def validate_scope_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.SCOPE)

    @field_validator("chain_refs")
    @classmethod
    def validate_chain_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.CHAIN)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.EVIDENCE)

    @field_validator("boundary_refs")
    @classmethod
    def validate_boundary_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.BOUNDARY)


class ModuleSnapshotV3(SnapshotBaseV3):
    snapshot_type: Literal[SnapshotTypeV3.MODULE]
    module_id: str = Field(pattern=LOCAL_ID_PATTERN)
    responsibility: str = Field(min_length=1)
    component_versions: dict[str, str] = Field(min_length=1)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    capabilities: list[CapabilityClaimV3]
    module_refs: list[SnapshotReferenceV3]
    intent_refs: list[SnapshotReferenceV3]
    tool_refs: list[SnapshotReferenceV3]
    execution_boundary_ids: list[str]
    trace_event_types: list[str]

    @field_validator("module_refs")
    @classmethod
    def validate_module_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.MODULE)

    @field_validator("intent_refs")
    @classmethod
    def validate_intent_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.INTENT)

    @field_validator("tool_refs")
    @classmethod
    def validate_tool_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.TOOL)

    @field_validator("execution_boundary_ids")
    @classmethod
    def validate_boundary_ids(cls, value: list[str]) -> list[str]:
        return _validate_typed_ids(value, "boundary")


class IntentSnapshotV3(SnapshotBaseV3):
    snapshot_type: Literal[SnapshotTypeV3.INTENT]
    capability_id: str = Field(pattern=LOCAL_ID_PATTERN)
    module_id: str = Field(pattern=r"^module\.[a-z][a-z0-9_]*$")
    parameters_schema: dict[str, Any]
    parameter_semantics: dict[str, Any]
    decision_rules: dict[str, Any]
    semantic_rules: dict[str, Any]
    required_tool_name: str | None
    capabilities: list[CapabilityClaimV3]
    tool_refs: list[SnapshotReferenceV3]

    @field_validator("tool_refs")
    @classmethod
    def validate_tool_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.TOOL)


class ToolSnapshotV3(SnapshotBaseV3):
    snapshot_type: Literal[SnapshotTypeV3.TOOL]
    tool_name: str = Field(pattern=LOCAL_ID_PATTERN)
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
    capabilities: list[CapabilityClaimV3]


class EvidenceSnapshotV3(SnapshotBaseV3):
    snapshot_type: Literal[SnapshotTypeV3.EVIDENCE]
    evidence_id: str = Field(pattern=LOCAL_ID_PATTERN)
    description: str = Field(min_length=1)
    producer_module_ids: list[str]
    consumer_roles: list[str]
    production_timing: str = Field(min_length=1)
    payload_schema: dict[str, Any]
    observation_interface: str = Field(min_length=1)
    event_types: list[str]
    required: bool
    applicable_result_paths: list[str]
    availability: CapabilityClaimV3

    @field_validator("producer_module_ids")
    @classmethod
    def validate_producer_ids(cls, value: list[str]) -> list[str]:
        return _validate_typed_ids(value, "module")


class BoundarySnapshotV3(SnapshotBaseV3):
    snapshot_type: Literal[SnapshotTypeV3.BOUNDARY]
    boundary_id: str = Field(pattern=LOCAL_ID_PATTERN)
    description: str = Field(min_length=1)
    entry_node: str = Field(min_length=1)
    stop_node: str = Field(min_length=1)
    allowed_module_ids: list[str]
    prohibited_module_ids: list[str]
    terminal_condition: str = Field(min_length=1)
    evidence_ids: list[str]
    no_overrun_rule: str = Field(min_length=1)

    @field_validator("allowed_module_ids", "prohibited_module_ids")
    @classmethod
    def validate_module_ids(cls, value: list[str]) -> list[str]:
        return _validate_typed_ids(value, "module")

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: list[str]) -> list[str]:
        return _validate_typed_ids(value, "evidence")


class ScopeSnapshotV3(SnapshotBaseV3):
    snapshot_type: Literal[SnapshotTypeV3.SCOPE]
    scope_id: str = Field(pattern=LOCAL_ID_PATTERN)
    description: str = Field(min_length=1)
    inputs: list[str]
    outputs: list[str]
    entrypoint: str = Field(min_length=1)
    stop_boundary: str = Field(min_length=1)
    allowed_module_ids: list[str]
    prohibited_module_ids: list[str]
    module_refs: list[SnapshotReferenceV3]
    evidence_refs: list[SnapshotReferenceV3]
    boundary_refs: list[SnapshotReferenceV3]
    requirements: list[CapabilityRequirementV3]
    completion_condition: str = Field(min_length=1)
    unresolved_behavior: str = Field(min_length=1)

    @field_validator("allowed_module_ids", "prohibited_module_ids")
    @classmethod
    def validate_module_ids(cls, value: list[str]) -> list[str]:
        return _validate_typed_ids(value, "module")

    @field_validator("module_refs")
    @classmethod
    def validate_module_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.MODULE)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.EVIDENCE)

    @field_validator("boundary_refs")
    @classmethod
    def validate_boundary_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.BOUNDARY)


class ChainNodeV3(StrictCapabilityModelV3):
    node_id: str = Field(pattern=LOCAL_ID_PATTERN)
    capability_key: str = Field(pattern=CAPABILITY_KEY_PATTERN)
    provider: CapabilityProviderV3
    depends_on: list[str]
    inputs: list[str]
    outputs: list[str]
    stop_conditions: list[str]
    state_reads: list[str]
    state_writes: list[str]


class ChainSnapshotV3(SnapshotBaseV3):
    snapshot_type: Literal[SnapshotTypeV3.CHAIN]
    chain_id: str = Field(pattern=LOCAL_ID_PATTERN)
    description: str = Field(min_length=1)
    nodes: list[ChainNodeV3]
    module_refs: list[SnapshotReferenceV3]
    evidence_refs: list[SnapshotReferenceV3]
    boundary_refs: list[SnapshotReferenceV3]
    requirements: list[CapabilityRequirementV3]
    branches: list[dict[str, Any]]
    completion_condition: str = Field(min_length=1)

    @field_validator("module_refs")
    @classmethod
    def validate_module_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.MODULE)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.EVIDENCE)

    @field_validator("boundary_refs")
    @classmethod
    def validate_boundary_refs(
        cls, value: list[SnapshotReferenceV3]
    ) -> list[SnapshotReferenceV3]:
        return _validate_references(value, SnapshotTypeV3.BOUNDARY)


SnapshotV3 = (
    AgentSnapshotV3
    | ModuleSnapshotV3
    | IntentSnapshotV3
    | ToolSnapshotV3
    | ScopeSnapshotV3
    | ChainSnapshotV3
    | EvidenceSnapshotV3
    | BoundarySnapshotV3
)


def snapshot_schema_v3(snapshot_type: SnapshotTypeV3) -> dict[str, Any]:
    models = {
        SnapshotTypeV3.AGENT: AgentSnapshotV3,
        SnapshotTypeV3.MODULE: ModuleSnapshotV3,
        SnapshotTypeV3.INTENT: IntentSnapshotV3,
        SnapshotTypeV3.TOOL: ToolSnapshotV3,
        SnapshotTypeV3.SCOPE: ScopeSnapshotV3,
        SnapshotTypeV3.CHAIN: ChainSnapshotV3,
        SnapshotTypeV3.EVIDENCE: EvidenceSnapshotV3,
        SnapshotTypeV3.BOUNDARY: BoundarySnapshotV3,
    }
    return models[snapshot_type].model_json_schema()
