"""Strict protocols for phase-two analysis, comparison, and gates."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from .schema_base import StrictModel

JudgeStatus = Literal[
    "NOT_APPLICABLE",
    "COMPLETED",
    "MODEL_OUTPUT_ERROR",
    "MODEL_INVOCATION_ERROR",
    "MODEL_TIMEOUT",
]
ComparisonStatus = Literal["COMPARABLE", "INVALID_COMPARISON"]
GateConclusion = Literal["PASS", "FAIL", "REVIEW_REQUIRED", "INVALID_COMPARISON"]


class JudgeDimensionSpec(StrictModel):
    name: str = Field(min_length=1)
    weight: float = Field(gt=0)
    threshold: float = Field(ge=0, le=100)


class JudgeCaseSpec(StrictModel):
    rubric_id: str = Field(min_length=1)
    rubric_version: str = Field(min_length=1)
    dimensions: list[JudgeDimensionSpec] = Field(min_length=1)
    reference_facts: dict[str, Any] = Field(default_factory=dict)
    required: bool = False

    @model_validator(mode="after")
    def unique_dimensions(self) -> Self:
        names = [item.name for item in self.dimensions]
        if len(names) != len(set(names)):
            raise ValueError("judge dimension names must be unique")
        return self


class JudgeRunConfig(StrictModel):
    enabled: bool = True
    rubric_path: str = Field(min_length=1)
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=1, ge=0)


class JudgeRubricDimension(StrictModel):
    name: str = Field(min_length=1)
    instruction: str = Field(min_length=1)


class JudgeRubric(StrictModel):
    rubric_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    output_schema_version: str = Field(min_length=1)
    dimensions: list[JudgeRubricDimension] = Field(min_length=1)
    max_text_chars: int = Field(default=4000, gt=0)

    @model_validator(mode="after")
    def unique_dimensions(self) -> Self:
        names = [item.name for item in self.dimensions]
        if len(names) != len(set(names)):
            raise ValueError("rubric dimension names must be unique")
        return self


class JudgeRequest(StrictModel):
    user_input: str
    final_response: str
    tool_result_summaries: list[dict[str, Any]] = Field(default_factory=list)
    reference_facts: dict[str, Any] = Field(default_factory=dict)
    dimensions: list[JudgeDimensionSpec]
    dimension_instructions: dict[str, str]
    rubric_id: str
    rubric_version: str
    prompt_version: str


class JudgeAttempt(StrictModel):
    attempt: int = Field(ge=1)
    status: JudgeStatus
    latency_ms: int = Field(ge=0)
    error: str | None = None


class JudgeDimensionResult(StrictModel):
    name: str
    score: float = Field(ge=0, le=100)
    passed: bool
    reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class JudgeResult(StrictModel):
    status: JudgeStatus
    model: str | None = None
    prompt_version: str | None = None
    rubric_id: str | None = None
    rubric_version: str | None = None
    output_schema_version: str | None = None
    dimensions: list[JudgeDimensionResult] = Field(default_factory=list)
    score: float | None = Field(default=None, ge=0, le=100)
    passed: bool | None = None
    attempts: list[JudgeAttempt] = Field(default_factory=list)
    latency_ms: int = Field(default=0, ge=0)
    token_usage: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


class NormalizedTraceEvent(StrictModel):
    event_id: str
    event_type: str
    turn_index: int = Field(ge=0)
    agent_run_id: str | None = None
    timestamp: str | None = None
    evidence_ref: str
    source_index: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class TraceIssue(StrictModel):
    code: str
    message: str
    severity: Literal["INFO", "WARNING", "ERROR"] = "WARNING"
    evidence_refs: list[str] = Field(default_factory=list)


class TraceAnalysis(StrictModel):
    timeline: list[NormalizedTraceEvent] = Field(default_factory=list)
    issues: list[TraceIssue] = Field(default_factory=list)
    first_observed_deviation: TraceIssue | None = None
    suggested_investigation_areas: list[str] = Field(default_factory=list)


class RunAnalysis(StrictModel):
    analysis_version: str
    source_results_sha256: str
    traces: dict[str, TraceAnalysis]


class CaseStabilityResult(StrictModel):
    case_id: str
    planned_trials: int = Field(ge=1)
    completed_trials: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    inconclusive_count: int = Field(ge=0)
    not_applicable_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    trial_pass_rate: float | None = Field(default=None, ge=0, le=100)
    pass_at_k: bool
    pass_power_k: bool
    quality_volatile: bool
    output_volatile: bool
    output_hashes: list[str] = Field(default_factory=list)
    latency_p50_ms: float | None = Field(default=None, ge=0)
    latency_p95_ms: float | None = Field(default=None, ge=0)
    critical_failure_any: bool = False


class RunStability(StrictModel):
    stability_version: str
    trials_per_case: int = Field(ge=1)
    cases: list[CaseStabilityResult]
    pass_at_k_rate: float | None = Field(default=None, ge=0, le=100)
    pass_power_k_rate: float | None = Field(default=None, ge=0, le=100)
    trial_pass_rate: float | None = Field(default=None, ge=0, le=100)
    latency_p50_ms: float | None = Field(default=None, ge=0)
    latency_p95_ms: float | None = Field(default=None, ge=0)


class ComparabilityIssue(StrictModel):
    code: str
    message: str


class ComparabilityReport(StrictModel):
    status: ComparisonStatus
    issues: list[ComparabilityIssue] = Field(default_factory=list)


class TrialDelta(StrictModel):
    case_id: str
    trial_id: str
    baseline: str | float | None = None
    candidate: str | float | None = None


class PerformanceSummary(StrictModel):
    """Saved business latency and Judge usage metrics for one Trial population."""

    latency_sample_count: int = Field(ge=0)
    latency_p50_ms: float | None = Field(default=None, ge=0)
    latency_p95_ms: float | None = Field(default=None, ge=0)
    judge_token_totals: dict[str, int | None] = Field(default_factory=dict)
    judge_token_total: int | None = Field(default=None, ge=0)
    judge_token_max: int | None = Field(default=None, ge=0)


class ComparisonPerformance(StrictModel):
    baseline: PerformanceSummary
    candidate: PerformanceSummary


class ComparisonResult(StrictModel):
    comparison_version: str
    performance: ComparisonPerformance | None = None
    status: ComparisonStatus
    baseline_sha256: str
    candidate_sha256: str
    comparability: ComparabilityReport
    newly_failed: list[TrialDelta] = Field(default_factory=list)
    fixed: list[TrialDelta] = Field(default_factory=list)
    persistently_failed: list[TrialDelta] = Field(default_factory=list)
    new_execution_errors: list[TrialDelta] = Field(default_factory=list)
    recovered_execution_errors: list[TrialDelta] = Field(default_factory=list)
    newly_unstable: list[str] = Field(default_factory=list)
    stability_improved: list[str] = Field(default_factory=list)
    judge_deltas: list[TrialDelta] = Field(default_factory=list)
    latency_deltas: list[TrialDelta] = Field(default_factory=list)
    token_deltas: list[TrialDelta] = Field(default_factory=list)
    missing_trials: list[str] = Field(default_factory=list)
    extra_trials: list[str] = Field(default_factory=list)


class GatePolicy(StrictModel):
    policy_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    require_comparison: bool = False
    minimum_execution_rate: float | None = Field(default=None, ge=0, le=100)
    minimum_strict_pass_rate: float | None = Field(default=None, ge=0, le=100)
    minimum_pass_power_k_rate: float | None = Field(default=None, ge=0, le=100)
    maximum_regressions: int | None = Field(default=None, ge=0)
    maximum_unstable_cases: int | None = Field(default=None, ge=0)
    core_labels: list[str] = Field(default_factory=list)
    zero_tolerance_labels: list[str] = Field(default_factory=list)
    zero_tolerance_assertions: list[str] = Field(default_factory=list)
    required_judge_dimensions: dict[str, float] = Field(default_factory=dict)
    maximum_latency_p50_ms: float | None = Field(default=None, ge=0)
    maximum_latency_p95_ms: float | None = Field(default=None, ge=0)
    maximum_token_usage: int | None = Field(default=None, ge=0)
    maximum_latency_p50_increase_percent: float | None = Field(
        default=None, ge=0
    )
    maximum_latency_p95_increase_percent: float | None = Field(
        default=None, ge=0
    )
    maximum_token_increase_percent: float | None = Field(default=None, ge=0)
    minimum_percentile_samples: int = Field(default=20, ge=1)
    require_trace_evidence: bool = False


class GateCheckResult(StrictModel):
    code: str
    state: Literal["PASS", "FAIL", "REVIEW"]
    operator: str
    threshold: Any = None
    actual: Any = None
    evidence_refs: list[str] = Field(default_factory=list)


class GateResult(StrictModel):
    gate_version: str
    conclusion: GateConclusion
    policy_id: str
    policy_version: str
    candidate_sha256: str
    comparison_sha256: str | None = None
    checks: list[GateCheckResult] = Field(default_factory=list)


class AnalysisPaths(StrictModel):
    analysis: str
    trace_files: list[str] = Field(default_factory=list)


class ComparisonPaths(StrictModel):
    json_path: str
    markdown_path: str


class GatePaths(StrictModel):
    json_path: str
    markdown_path: str
