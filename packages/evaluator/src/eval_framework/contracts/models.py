"""Strict models for Suite authoring, resolution, and frozen compilation."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator

from ..plugins.models import PluginKind, PluginReference
from ..schema_base import StrictModel
from ..schemas import DatasetBundle, DatasetLifecycle, RunConfig

SHA256_PATTERN = r"^[0-9a-f]{64}$"


def _relative_posix_path(value: str) -> str:
    if not value or "\\" in value:
        raise ValueError("path must be a non-empty relative POSIX path")
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("path must remain inside the Suite root")
    return value


class DatasetSource(StrictModel):
    path: str
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        return _relative_posix_path(value)


class ContractReference(StrictModel):
    contract_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    path: str
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        return _relative_posix_path(value)


class SuiteDefinition(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    suite_id: str = Field(min_length=1)
    suite_version: str = Field(min_length=1)
    lifecycle_state: DatasetLifecycle = "UNKNOWN"
    dataset_loader: PluginReference
    dataset_sources: list[DatasetSource] = Field(min_length=1)
    provider: PluginReference
    capability_bundle: ContractReference | None = None
    assertion_profile: ContractReference | None = None
    trace_profile: ContractReference | None = None
    judge_profile: ContractReference | None = None
    report_profile: ContractReference | None = None
    gate_policy: ContractReference | None = None
    run_config: RunConfig = Field(default_factory=RunConfig)


class ResolvedSource(StrictModel):
    logical_path: str
    filesystem_path: Path
    sha256: str = Field(pattern=SHA256_PATTERN)
    content: bytes


class SourceFingerprint(StrictModel):
    logical_path: str
    sha256: str = Field(pattern=SHA256_PATTERN)


class ResolvedContract(StrictModel):
    contract_id: str
    version: str
    logical_path: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    content: dict[str, Any]


class ResolvedPluginSnapshot(StrictModel):
    kind: PluginKind
    plugin_id: str
    version: str
    implementation_fingerprint: str = Field(pattern=SHA256_PATTERN)
    config: dict[str, Any] = Field(default_factory=dict)


class CompilationIssue(StrictModel):
    code: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    message: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class LoadedSuiteDefinition(StrictModel):
    definition: SuiteDefinition
    source_path: Path | None = None
    root: Path
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    origin: Literal["file", "legacy_compatibility"] = "file"
    runtime_provider_config: dict[str, Any] = Field(default_factory=dict)


class CompiledSuite(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    suite_id: str
    suite_version: str
    lifecycle_state: DatasetLifecycle
    definition: dict[str, Any]
    dataset: DatasetBundle
    run_config: RunConfig
    plugins: list[ResolvedPluginSnapshot]
    contracts: list[ResolvedContract]
    sources: list[SourceFingerprint]
    compiled_suite_snapshot: dict[str, Any]
    compiled_suite_sha256: str = Field(pattern=SHA256_PATTERN)
    runtime_provider_config: dict[str, Any] = Field(default_factory=dict)
