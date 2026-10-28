"""Strict, versioned protocols for deterministic evaluation."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from .diagnostic_metrics import (
    ConversationMetricConfig,
    DiagnosticMetricResult,
    DiagnosticMetricSummary,
)
from .phase2_schemas import (
    JudgeCaseSpec,
    JudgeResult,
    JudgeRunConfig,
    PerformanceSummary,
    RunStability,
    TraceAnalysis,
)
from .schema_base import StrictModel

TestScope = Literal["module", "link", "end_to_end"]
ScenarioType = Literal[
    "normal",
    "valid_boundary",
    "invalid_parameter",
    "missing_parameter",
    "ambiguous_expression",
    "multi_condition",
    "expression_variant",
    "correction_conflict",
    "unsupported_batch",
]
RunMode = Literal["framework_self_test", "agent_benchmark"]
DatasetLifecycle = Literal["DRAFT", "VALIDATED", "APPROVED", "FROZEN", "UNKNOWN"]
ExecutionType = Literal["auto", "full", "targeted_smoke", "filtered_subset"]
ExecutionStatus = Literal[
    "COMPLETED",
    "MODEL_OUTPUT_ERROR",
    "MODEL_INVOCATION_ERROR",
    "MODEL_TIMEOUT",
    "AGENT_EXCEPTION",
    "OUTER_TIMEOUT",
    "INITIALIZATION_ERROR",
    "EVALUATOR_ERROR",
]
QualityConclusion = Literal["PASS", "FAIL", "INCONCLUSIVE", "NOT_APPLICABLE"]
ManualConclusion = Literal[
    "UPHOLD",
    "OVERRIDE_PASS",
    "OVERRIDE_FAIL",
    "CONTRACT_DISPUTE",
    "INCONCLUSIVE",
]


class ExecutionSpec(StrictModel):
    adapter_input: dict[str, Any] | None = None
    user_input: str = Field(min_length=1)
    user_responses: list[str] = Field(default_factory=list)
    tool_profile: str = Field(min_length=1)
    allowed_tools: list[str] | None = None
    fault_injection: dict[str, str] = Field(default_factory=dict)
    max_steps: int = Field(default=4, gt=0)
    timeout_seconds: float = Field(default=30.0, gt=0)


class ExpectedToolCall(StrictModel):
    name: str = Field(min_length=1)
    arguments: dict[str, Any] | None = None
    count: int | None = Field(default=None, ge=0)
    status: Literal["SUCCESS", "FAILED", "TIMEOUT"] | None = None


class AssertionSpec(StrictModel):
    name: str = Field(min_length=1)
    weight: float = Field(gt=0)
    critical: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class EvaluationSpec(StrictModel):
    checks: list[AssertionSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_names(self) -> Self:
        names = [item.name for item in self.checks]
        if len(names) != len(set(names)):
            raise ValueError("assertion names must be unique within a case")
        return self


class OracleSpec(StrictModel):
    expected_module_output: dict[str, Any] | None = None
    expected_agent_status: str | None = None
    expected_tool_calls: list[ExpectedToolCall] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    goal_state: dict[str, Any] | None = None
    process_constraints: dict[str, Any] = Field(default_factory=dict)
    expected_response: dict[str, Any] | None = None
    evaluation: EvaluationSpec
    judge: JudgeCaseSpec | None = None


class CleanupSpec(StrictModel):
    required: bool = True
    strategy: Literal["temporary_directory"] = "temporary_directory"


class EvalCase(StrictModel):
    schema_version: str = Field(min_length=1)
    case_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    task_id: str = Field(min_length=1)
    scenario_type: ScenarioType
    test_scope: TestScope
    target: str = Field(min_length=1)
    execution: ExecutionSpec
    oracle: OracleSpec
    labels: list[str] = Field(default_factory=list)
    cleanup: CleanupSpec | None = None


class DatasetFilters(StrictModel):
    scopes: list[TestScope] | None = None
    task_ids: list[str] | None = None
    labels: list[str] | None = None
    case_ids: list[str] | None = None


class ExecutionProfile(StrictModel):
    allowed_tools: list[str]

    @field_validator("allowed_tools")
    @classmethod
    def unique_non_empty_tools(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("allowed_tools must contain non-empty strings")
        if len(value) != len(set(value)):
            raise ValueError("allowed_tools must be unique")
        return value


class DatasetBundle(StrictModel):
    onboarding: dict[str, Any] | None = None
    path: str
    sha256: str
    schema_versions: list[str]
    dataset_version: str
    lifecycle_state: DatasetLifecycle = "UNKNOWN"
    suite_id: str | None = None
    manifest_path: str | None = None
    provider_id: str = "unknown"
    capability_bundle_path: str | None = None
    capability_bundle_sha256: str | None = None
    legacy_capability_snapshots: list[dict[str, Any]] = Field(default_factory=list)
    execution_profiles: dict[str, ExecutionProfile] = Field(default_factory=dict)
    execution_profiles_source: Literal["manifest", "legacy_module"] = "legacy_module"
    total_count: int
    cases: list[EvalCase]


class ValidationIssue(StrictModel):
    case_id: str | None
    field_path: str
    message: str


class ValidationReport(StrictModel):
    valid: bool
    issues: list[ValidationIssue]


class AssertionResult(StrictModel):
    name: str
    weight: float
    critical: bool
    applicable: bool = True
    passed: bool | None
    expected: Any = None
    actual: Any = None
    message: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    native_scores: list[dict[str, Any]] = Field(default_factory=list)


class Diagnosis(StrictModel):
    code: str
    title: str
    category: str
    source_assertions: list[str]
    evidence_refs: list[str] = Field(default_factory=list)


class CaseResult(StrictModel):
    diagnostic_metrics: dict[str, DiagnosticMetricResult] = Field(default_factory=dict)
    observations: dict[str, Any] | None = None
    execution_started_at: str | None = None
    execution_finished_at: str | None = None
    before_snapshot: dict[str, Any] | None = None
    trace_id: str | None = None
    evidence_status: Literal[
        "COMPLETE", "PARTIAL", "STILL_OPEN", "EXPORT_FAILED", "UNAVAILABLE"
    ] = "UNAVAILABLE"
    evidence_manifest: dict[str, Any] = Field(default_factory=dict)
    evaluation_validity: Literal["VALID", "INVALID"] = "VALID"
    evaluation_issues: list[dict[str, Any]] = Field(default_factory=list)
    evaluator_run_id: str
    case_id: str
    task_id: str
    scenario_type: ScenarioType
    test_scope: TestScope
    user_input: str
    trial_id: str
    run_mode: RunMode
    tool_profile: str = Field(min_length=1)
    tool_version: str
    max_steps: int
    timeout_seconds: float
    session_id: str | None
    agent_run_ids: list[str]
    execution_status: ExecutionStatus
    quality_conclusion: QualityConclusion
    score: float | None
    module_output: dict[str, Any] | None
    turn_results: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    trace_events: list[dict[str, Any]]
    turn_snapshots: list[dict[str, Any]]
    system_snapshot: dict[str, Any] | None
    assertion_results: list[AssertionResult]
    first_failed_assertion: AssertionResult | None
    diagnoses: list[Diagnosis] = Field(default_factory=list)
    latency_ms: int = Field(ge=0)
    evidence_refs: list[str]
    cleanup_status: str
    exception: dict[str, Any] | None = None
    labels: list[str] = Field(default_factory=list)
    judge_result: JudgeResult | None = None
    trace_analysis: TraceAnalysis | None = None

    @property
    def deterministic_score(self) -> float | None:
        return self.score


class RunConfig(StrictModel):
    conversation_completeness: ConversationMetricConfig | None = None
    run_mode: RunMode = "agent_benchmark"
    pass_threshold: float = Field(default=100.0, ge=0, le=100)
    execution_type: ExecutionType = "auto"
    filters: DatasetFilters | None = None
    allow_non_frozen_dataset: bool = False
    trials_per_case: int = Field(default=1, ge=1)
    judge: JudgeRunConfig | None = None


class SummaryStats(StrictModel):
    diagnostic_metrics: dict[str, DiagnosticMetricSummary] = Field(default_factory=dict)
    metric_version: str | None = None
    performance: PerformanceSummary | None = None
    total_cases: int
    total_trials: int = 0
    execution_status_counts: dict[str, int]
    quality_counts: dict[str, int]
    framework_completion_rate: float
    agent_case_pass_rate: float | None
    strict_assertion_pass_rate: float | None = None
    core_behavior_match_rate: float | None = None
    average_score: float | None
    average_latency_ms: float
    median_latency_ms: float
    max_latency_ms: int
    by_scope: dict[str, dict[str, float | int | None]]
    by_intent: dict[str, dict[str, float | int | None]]
    by_expected_intent: dict[str, dict[str, float | int | None]] = Field(
        default_factory=dict
    )
    by_actual_intent: dict[str, dict[str, float | int | None]] = Field(
        default_factory=dict
    )
    by_task_id: dict[str, dict[str, float | int | None]]
    failed_assertions: dict[str, int]


class EvaluationRunResult(StrictModel):
    diagnostic_metadata: dict[str, dict[str, Any]] = Field(default_factory=dict)
    onboarding: dict[str, Any] | None = None
    evaluation_backend: dict[str, Any] | None = None
    native_artifacts: dict[str, str] = Field(default_factory=dict)
    run_directory: str | None = None
    evaluator_run_id: str
    started_at: str
    finished_at: str
    dataset_path: str
    dataset_version: str
    dataset_hash: str
    dataset_total_cases: int = Field(default=0, ge=0)
    dataset_lifecycle_state: DatasetLifecycle = "UNKNOWN"
    dataset_manifest_path: str | None = None
    agent_version: str
    provider_id: str = "unknown"
    provider_version: str = "unknown"
    capability_bundle_sha256: str | None = None
    model_metadata: dict[str, Any]
    assertion_registry_version: str
    run_config: RunConfig
    cases: list[CaseResult]
    summary: SummaryStats
    trials_per_case: int = Field(default=1, ge=1)
    total_duration_ms: int = Field(ge=0)
    judge_metadata: dict[str, Any] | None = None
    stability: RunStability | None = None
    compiled_suite_sha256: str | None = None
    compiled_suite_snapshot: dict[str, Any] | None = None
    plugin_fingerprints: list[dict[str, str]] = Field(default_factory=list)
    contract_fingerprints: list[dict[str, str]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_agent_version(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        migrated = dict(value)
        legacy = migrated.pop("mini_agent_version", None)
        current = migrated.get("agent_version")
        if legacy is not None and current is not None and legacy != current:
            raise ValueError("agent version fields conflict")
        if current is None and legacy is not None:
            migrated["agent_version"] = legacy
        return migrated

    @model_validator(mode="after")
    def restore_legacy_dataset_count(self) -> Self:
        if self.dataset_total_cases == 0 and self.cases:
            self.dataset_total_cases = len(self.cases)
        return self


class ReportPaths(StrictModel):
    output_dir: str
    manifest: str
    results: str
    summary: str
    report: str
    summary_json: str
    results_jsonl: str
    failures: str
    case_files: list[str]
    evidence_files: list[str]


class InvalidRunRecord(StrictModel):
    run_id: str
    verdict: Literal["INVALID_RUN"] = "INVALID_RUN"
    error_code: str
    message: str
    evidence_refs: list[str]
    provider_id: str
    dataset_path: str
    issues: list[dict[str, Any]] = Field(default_factory=list)


class InvalidRunPaths(StrictModel):
    output_dir: str
    record: str
    report: str
