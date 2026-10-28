"""Versioned candidate input models; executable bindings are separate inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from ..schema_base import StrictModel

CandidateFormat = Literal["agent_candidate", "nanobot_candidate"]
CandidateKind = Literal[
    "schema_contract", "contract_check", "behavior_candidate", "blocked_obligation"
]


class SourceReference(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pointer: str | None = None
    anchor: str | None = None


class CandidateCheck(StrictModel):
    subject: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    expected: Any


class CandidateOracle(StrictModel):
    checks: list[CandidateCheck]


class CandidateCase(StrictModel):
    schema_version: Literal["1.0"]
    dataset_format: CandidateFormat
    agent_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    layer: str = Field(min_length=1)
    kind: CandidateKind
    category: str = Field(min_length=1)
    title: str
    support_status: Literal["supported", "unsupported", "unknown"]
    source_basis: str
    execution_readiness: str
    runtime_execution: str
    approval: str
    preconditions: list[dict[str, Any]]
    input: dict[str, Any]
    oracle: CandidateOracle
    source_refs: list[SourceReference] = Field(min_length=1)
    runner_requirements: list[str]
    blocker_ids: list[str]


class CandidateDataset(StrictModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_count: int = Field(ge=0)
    kind: CandidateKind
    layer: str
    target_id: str
    dataset_format: CandidateFormat


class CandidateManifest(StrictModel):
    schema_version: Literal["1.0"]
    dataset_format: CandidateFormat
    agent_id: str = Field(min_length=1)
    agent_version: str
    state: str
    runtime_execution: str
    approval: str
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_count: int = Field(ge=0)
    counts_by_kind: dict[str, int]
    datasets: list[CandidateDataset]
    files_sha256: dict[str, str]


@dataclass(frozen=True)
class PreparedInput:
    root: Path
    suite_paths: list[Path]
    report: dict[str, Any]
    report_path: Path
