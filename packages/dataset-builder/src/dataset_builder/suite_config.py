"""Strict machine-readable suite configuration protocol."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _unique(values: list[str], label: str) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    return values


class PathReference(ConfigModel):
    base: Literal["builder_root", "projects_root", "suite_dir"]
    path: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def relative_without_parent_segments(cls, value: str) -> str:
        candidate = PurePosixPath(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("path must be relative and contain no '..'")
        if (
            value.strip() != value
            or not value.strip()
            or candidate == PurePosixPath(".")
        ):
            raise ValueError("path must be a non-empty relative path")
        return value


class PolicyReferences(ConfigModel):
    source: PathReference
    coverage: PathReference
    generation: PathReference
    validation: PathReference
    review: PathReference
    freeze: PathReference


class SuiteMetadata(ConfigModel):
    suite_id: str = Field(min_length=1)
    suite_kind: Literal["module_intent"]
    dataset_version: str = Field(min_length=1)
    target_agent: str = Field(min_length=1)
    test_scope: Literal["module", "critical_path", "end_to_end"]
    target: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)


class SuitePaths(ConfigModel):
    source_files: list[PathReference]
    coverage_plan: PathReference
    seed_catalog: PathReference
    freeze_output: PathReference
    eval_case_schema: PathReference


class CapabilityInputConfig(ConfigModel):
    bundle: PathReference
    bundle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope_or_chain_id: str = Field(min_length=1)
    intent_id: str = Field(min_length=1)
    tool_id: str | None = None

    @model_validator(mode="after")
    def selection_ids_are_typed(self) -> Self:
        if not self.scope_or_chain_id.startswith(("scope.", "chain.")):
            raise ValueError("scope_or_chain_id must identify a scope or chain")
        if not self.intent_id.startswith("intent."):
            raise ValueError("intent_id must identify an intent")
        if self.tool_id is not None and not self.tool_id.startswith("tool."):
            raise ValueError("tool_id must identify a tool")
        return self


class CandidateProtocolConfig(ConfigModel):
    allowed_intents: list[str] = Field(min_length=1)
    allowed_statuses: list[str] = Field(min_length=1)
    allowed_next_actions: list[str] = Field(min_length=1)
    allowed_scenario_types: list[str] = Field(min_length=1)
    allowed_difficulties: list[str] = Field(min_length=1)
    rule_refs_required: bool

    @model_validator(mode="after")
    def enums_are_unique(self) -> Self:
        for field_name in (
            "allowed_intents",
            "allowed_statuses",
            "allowed_next_actions",
            "allowed_scenario_types",
            "allowed_difficulties",
        ):
            _unique(getattr(self, field_name), field_name)
        return self


class SnapshotValueReference(ConfigModel):
    snapshot_id: str = Field(min_length=1)
    pointer: str = Field(pattern=r"^/")


class LabelInstruction(ConfigModel):
    source: Literal[
        "literal",
        "candidate",
        "slot",
        "rule_refs",
        "coverage_tags",
        "snapshot",
    ]
    value: str | None = None
    field: str | None = None
    prefix: str = ""
    snapshot_id: str | None = None
    pointer: str | None = None

    @model_validator(mode="after")
    def required_values_match_source(self) -> Self:
        required = {
            "literal": ("value",),
            "candidate": ("field",),
            "slot": ("field",),
            "rule_refs": (),
            "coverage_tags": (),
            "snapshot": ("snapshot_id", "pointer"),
        }[self.source]
        missing = [name for name in required if not getattr(self, name)]
        if missing:
            raise ValueError(f"label source {self.source!r} requires {missing}")
        if self.pointer is not None and not self.pointer.startswith("/"):
            raise ValueError("snapshot label pointer must be a JSON pointer")
        return self


class ExecutionConfig(ConfigModel):
    tool_profile: str = Field(min_length=1)
    allowed_tools: list[str] | None
    fault_injection: dict[str, Any]
    max_steps: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0)


class ExecutionProfileConfig(ConfigModel):
    allowed_tools: list[str]

    @field_validator("allowed_tools")
    @classmethod
    def unique_non_empty_tools(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("allowed_tools must contain non-empty strings")
        return _unique(value, "allowed_tools")


class AssertionConfig(ConfigModel):
    name: str = Field(min_length=1)
    weight: int = Field(gt=0)
    critical: bool
    config: dict[str, Any]


class CompilationConfig(ConfigModel):
    case_id_prefix: str = Field(min_length=1)
    case_id_width: int = Field(ge=1)
    task_ids: dict[str, str]
    scenario_type_map: dict[str, str]
    labels: list[LabelInstruction] = Field(min_length=1)
    execution: ExecutionConfig
    user_responses_by_intent: dict[str, list[str]]
    cleanup_by_intent: dict[str, dict[str, Any]]
    oracle_reason: str
    assertions: list[AssertionConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def compilation_values_are_consistent(self) -> Self:
        names = [item.name for item in self.assertions]
        if len(names) != len(set(names)):
            raise ValueError("assertion names must be unique")
        return self


class StatusRule(ConfigModel):
    minimum_parameter_count: int = Field(ge=0)
    missing_parameters: Literal["empty", "non_empty", "any"]


class ValidationConfig(ConfigModel):
    decision_protocol: SnapshotValueReference | None
    capability_by_intent: dict[str, str]
    parameters_schema_pointer: str = Field(pattern=r"^/")
    missing_parameters_pointer: str = Field(pattern=r"^/")
    allowed_parameters_by_intent: dict[str, list[str]]
    omit_null_parameters: bool
    status_rules: dict[str, StatusRule]
    forbidden_intents: list[str]
    execution_parameter_names: list[str]
    require_slot_scenario_match: bool
    require_rule_refs_match: bool

    @model_validator(mode="after")
    def validation_lists_are_unique(self) -> Self:
        _unique(self.forbidden_intents, "forbidden_intents")
        _unique(self.execution_parameter_names, "execution_parameter_names")
        for intent, names in self.allowed_parameters_by_intent.items():
            _unique(names, f"allowed_parameters_by_intent[{intent}]")
        return self


class DistributionField(ConfigModel):
    report_name: str = Field(min_length=1)
    case_pointers: list[str] = Field(min_length=1)
    plan_field: str | None
    slot_fields: list[str] = Field(min_length=1)

    @field_validator("case_pointers")
    @classmethod
    def valid_case_pointers(cls, value: list[str]) -> list[str]:
        _unique(value, "case_pointers")
        if any(not item.startswith("/") for item in value):
            raise ValueError("case_pointers must be JSON pointers")
        return value


class CoverageConfig(ConfigModel):
    distribution_fields: list[DistributionField]

    @model_validator(mode="after")
    def report_names_are_unique(self) -> Self:
        _unique(
            [item.report_name for item in self.distribution_fields],
            "coverage report names",
        )
        return self


class QualityPolicy(ConfigModel):
    minimum_input_length: int = Field(ge=0)
    forbidden_phrases: list[str] = Field(default_factory=list)
    sensitive_phrases: list[str] = Field(default_factory=list)
    compound_markers: list[str] = Field(default_factory=list)
    compound_forbidden_intents: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def values_are_unique(self) -> Self:
        for name in (
            "forbidden_phrases",
            "sensitive_phrases",
            "compound_markers",
            "compound_forbidden_intents",
        ):
            _unique(getattr(self, name), name)
        return self


class SuiteConfig(ConfigModel):
    schema_version: Literal["1.0"]
    metadata: SuiteMetadata
    paths: SuitePaths
    capability_input: CapabilityInputConfig
    execution_profiles: dict[str, ExecutionProfileConfig]
    policies: PolicyReferences

    @model_validator(mode="after")
    def execution_profile_is_declared(self) -> Self:
        if not self.execution_profiles:
            raise ValueError("execution_profiles must not be empty")
        if any(not name for name in self.execution_profiles):
            raise ValueError("execution profile names must be non-empty")
        return self


def load_suite_config_file(path: Path) -> SuiteConfig:
    return SuiteConfig.model_validate_json(path.read_text())


def write_suite_config_schema(path: Path) -> None:
    path.write_text(
        json.dumps(SuiteConfig.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
    )
