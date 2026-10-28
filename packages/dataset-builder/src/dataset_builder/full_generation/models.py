"""Versioned authoring protocols; runtime readiness is never a test result."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRef(StrictModel):
    snapshot_id: str
    relative_path: str
    snapshot_sha256: str
    pointer: str


class FullInventory(StrictModel):
    bundle_sha256: str
    bundle_path: str
    delivery_root: str
    targets: list[dict[str, Any]]
    artifacts: dict[str, dict[str, Any]]
    external_bindings: dict[str, str]
    gaps: list[dict[str, Any]]


class CoverageSlot(StrictModel):
    slot_id: str
    target_id: str
    layer: Literal["modules", "tools", "critical_links", "end_to_end"]
    dimension: str
    source_refs: list[SourceRef]
    support_status: Literal["supported", "unsupported", "unknown"]
    case_kind: str
    blocker_ids: list[str] = Field(default_factory=list)


class Blocker(StrictModel):
    blocker_id: str
    affected_slot_ids: list[str]
    reason: str
    source_refs: list[SourceRef]
    required_action: str


class ContractCase(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_format: Literal["capability_contract_case"] = "capability_contract_case"
    case_id: str
    slot_id: str
    target_id: str
    layer: str
    preconditions: list[dict[str, Any]]
    input: dict[str, Any]
    oracle: dict[str, Any]
    source_refs: list[SourceRef]
    runner_requirements: list[str]


class CompiledCase(StrictModel):
    slot_id: str
    dataset_format: Literal["eval_case", "capability_contract_case"]
    payload: dict[str, Any]
    validation_status: Literal["pending", "valid"] = "pending"
    execution_readiness: Literal["not_run", "needs_runner", "blocked"]
    coverage_mode: Literal["direct", "indirect", "contract"]
    blocker_ids: list[str] = Field(default_factory=list)


class GenerationResult(StrictModel):
    inventory: FullInventory
    slots: list[CoverageSlot]
    cases: list[CompiledCase]
    blockers: list[Blocker]


class DeliveryReport(StrictModel):
    output_path: str
    file_count: int
    case_counts: dict[str, int]
    blocker_count: int
    valid: bool
