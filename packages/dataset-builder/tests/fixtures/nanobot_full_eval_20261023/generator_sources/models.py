"Candidate protocol: schema checks are distinct from unexecuted behavior."

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pointer: str | None = None
    anchor: str | None = None


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    dataset_format: Literal["nanobot_candidate"] = "nanobot_candidate"
    agent_id: Literal["nanobot"] = "nanobot"
    case_id: str
    target_id: str
    layer: Literal["modules", "tools", "critical_links", "end_to_end", "contracts"]
    kind: Literal[
        "schema_contract", "contract_check", "behavior_candidate", "blocked_obligation"
    ]
    category: str
    title: str
    support_status: Literal["supported", "unknown", "unsupported"]
    source_basis: Literal["snapshot", "implementation_derived", "missing_contract"]
    execution_readiness: Literal["static_only", "needs_runner", "blocked"]
    runtime_execution: Literal["NOT_RUN"] = "NOT_RUN"
    approval: Literal["PENDING"] = "PENDING"
    preconditions: list[dict[str, Any]] = Field(default_factory=list)
    input: dict[str, Any]
    oracle: dict[str, Any]
    source_refs: list[SourceRef] = Field(min_length=1)
    runner_requirements: list[str] = Field(default_factory=list)
    blocker_ids: list[str] = Field(default_factory=list)
