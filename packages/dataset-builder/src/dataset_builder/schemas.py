"""Strict authoring protocols. EvalCase itself remains owned by evaluator."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .suite_config import ExecutionProfileConfig


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Lifecycle = Literal["DRAFT", "VALIDATED", "STALE", "APPROVED", "FROZEN"]


class GenerationRequest(StrictModel):
    request_id: str
    suite_id: str
    prompt_version: str
    prompt_sha256: str
    suite_definition_version: str = "1.0"
    suite_config_sha256: str
    prompt: str
    candidate_schema: dict[str, Any]
    source_manifest: list[dict[str, str]]
    execution_profiles: dict[str, ExecutionProfileConfig]
    profile_binding: dict[str, str]
    trusted_schema_bindings: list[dict[str, str]]
    adapter_binding: dict[str, str]
    capability_ir_binding: dict[str, str]
    capability_selection: dict[str, str | None]
    capability_source_artifacts: list[dict[str, str]]
    capability_bundle_files: list[dict[str, str]] = Field(default_factory=list)
    agent_snapshot_sha256: str
    capability_bundle_sha256: str
    coverage_plan_sha256: str
    policy_bindings: list[dict[str, str]] = Field(default_factory=list)
    plugin_bindings: list[dict[str, str]] = Field(default_factory=list)
    created_at: datetime


class RawGeneration(StrictModel):
    request_id: str
    mode: Literal["scripted", "external", "openai", "deepeval"]
    model: str | None
    prompt_version: str
    created_at: datetime
    attempts: int = Field(ge=1)
    response: Any
    metadata: dict[str, Any] = Field(default_factory=dict)


class GateResult(StrictModel):
    name: str
    passed: bool
    issues: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationSummary(StrictModel):
    state: Lifecycle
    valid: bool
    draft_sha256: str
    case_count: int
    gates: list[GateResult]


class Approval(StrictModel):
    reviewer: str = Field(min_length=1)
    approved_at: datetime
    draft_sha256: str
    review_artifact_sha256: str = Field(min_length=64, max_length=64)
    reviewed_case_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def reviewer_not_blank(self) -> Self:
        if not self.reviewer.strip():
            raise ValueError("reviewer must not be blank")
        if len(set(self.reviewed_case_ids)) != len(self.reviewed_case_ids):
            raise ValueError("reviewed_case_ids must be unique")
        return self
