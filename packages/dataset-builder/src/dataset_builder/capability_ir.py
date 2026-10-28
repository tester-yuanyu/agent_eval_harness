"""Canonical, provider-neutral capability intermediate representation."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IRModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SupportStatus(StrEnum):
    SUPPORTED = "supported"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


class CapabilitySelection(IRModel):
    scope_or_chain_id: str = Field(min_length=1)
    intent_id: str = Field(min_length=1)
    tool_id: str | None = None

    @model_validator(mode="after")
    def selection_types_are_explicit(self) -> CapabilitySelection:
        if not self.scope_or_chain_id.startswith(("scope.", "chain.")):
            raise ValueError("scope_or_chain_id must identify a scope or chain")
        if not self.intent_id.startswith("intent."):
            raise ValueError("intent_id must identify an intent")
        if self.tool_id is not None and not self.tool_id.startswith("tool."):
            raise ValueError("tool_id must identify a tool")
        return self


class CapabilityClaimIR(IRModel):
    capability_key: str
    support_status: SupportStatus
    evidence_ids: tuple[str, ...] = ()
    reason: str | None = None
    source_snapshot_id: str


class EvidenceIR(IRModel):
    snapshot_id: str
    availability: SupportStatus
    observation_interface: str | None = None
    payload_schema: dict[str, Any] = Field(default_factory=dict)
    producer_module_ids: tuple[str, ...] = ()


class RequirementResolutionIR(IRModel):
    requirement_id: str
    capability_key: str
    mandatory: bool
    provider_role: str
    provider_snapshot_id: str | None
    support_status: SupportStatus
    evidence_ids: tuple[str, ...] = ()
    reason: str | None = None


class SourceArtifactBindingIR(IRModel):
    snapshot_id: str
    snapshot_type: str
    snapshot_format_version: str
    contract_version: str
    relative_path: str
    snapshot_sha256: str


class SelectedNodeIR(IRModel):
    snapshot_id: str
    snapshot_type: Literal["scope", "chain"]
    description: str | None = None
    completion_condition: str | None = None
    boundary_ids: tuple[str, ...] = ()


class SelectedIntentIR(IRModel):
    snapshot_id: str
    capability_id: str
    contract_version: str
    module_id: str | None = None
    required_tool_name: str | None = None


class SelectedToolIR(IRModel):
    snapshot_id: str
    tool_name: str
    registered: bool
    function_schema: dict[str, Any]


class CapabilityIR(IRModel):
    schema_version: Literal["1.0"] = "1.0"
    source_protocol_id: str
    source_protocol_version: str
    profile_id: str
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_protocol: str
    adapter_version: str
    agent_snapshot_id: str
    agent_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capability_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection: CapabilitySelection
    selected_node: SelectedNodeIR
    intent: SelectedIntentIR
    tool: SelectedToolIR | None = None
    support_status: SupportStatus
    requirements: tuple[RequirementResolutionIR, ...]
    claims: tuple[CapabilityClaimIR, ...]
    evidence: tuple[EvidenceIR, ...]
    parameters_schema: dict[str, Any]
    decision_rules: dict[str, Any] = Field(default_factory=dict)
    parameter_semantics: dict[str, Any] = Field(default_factory=dict)
    semantic_rules: dict[str, Any] = Field(default_factory=dict)
    source_artifacts: tuple[SourceArtifactBindingIR, ...]
    diagnostics: tuple[str, ...] = ()
    unmapped_facts: tuple[str, ...] = ()
    canonical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def write_capability_ir_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(CapabilityIR.model_json_schema(), ensure_ascii=False, indent=2)
        + "\n"
    )
