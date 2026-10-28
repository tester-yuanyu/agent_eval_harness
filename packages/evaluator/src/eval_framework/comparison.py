"""Strict, immutable comparison of two saved evaluation runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .metric_policy import run_performance
from .phase2_schemas import (
    ComparabilityIssue,
    ComparabilityReport,
    ComparisonPaths,
    ComparisonPerformance,
    ComparisonResult,
    TrialDelta,
)
from .result_loader import LoadedRunResult
from .schemas import CaseResult, EvaluationRunResult

COMPARISON_VERSION = "comparison-v2"
_ERROR_STATUSES = {
    "INITIALIZATION_ERROR",
    "MODEL_TIMEOUT",
    "MODEL_INVOCATION_ERROR",
    "MODEL_OUTPUT_ERROR",
    "AGENT_EXCEPTION",
    "OUTER_TIMEOUT",
    "EVALUATOR_ERROR",
}


def _add_if_different(
    issues: list[ComparabilityIssue],
    code: str,
    label: str,
    baseline: Any,
    candidate: Any,
) -> None:
    if baseline != candidate:
        issues.append(
            ComparabilityIssue(
                code=code,
                message=f"{label} differs: {baseline!r} != {candidate!r}",
            )
        )


def _trial_keys(result: EvaluationRunResult) -> set[str]:
    return {f"{case.case_id}/{case.trial_id}" for case in result.cases}


def _tool_profile_map(result: EvaluationRunResult) -> dict[str, str]:
    return {
        f"{case.case_id}/{case.trial_id}": case.tool_profile for case in result.cases
    }


def check_comparability(
    baseline: LoadedRunResult, candidate: LoadedRunResult
) -> ComparabilityReport:
    before = baseline.result
    after = candidate.result
    issues: list[ComparabilityIssue] = []
    for label, result in (("Baseline", before), ("Candidate", after)):
        if any(case.evaluation_validity == "INVALID" for case in result.cases):
            issues.append(
                ComparabilityIssue(
                    code="EVALUATION_INVALID",
                    message=f"{label} contains invalid evaluation Trials.",
                )
            )
    if before.dataset_lifecycle_state != "FROZEN":
        issues.append(
            ComparabilityIssue(
                code="NON_FROZEN_INPUT",
                message="Baseline dataset lifecycle is not FROZEN.",
            )
        )
    if after.dataset_lifecycle_state != "FROZEN":
        issues.append(
            ComparabilityIssue(
                code="NON_FROZEN_INPUT",
                message="Candidate dataset lifecycle is not FROZEN.",
            )
        )
    comparisons = [
        (
            "DIAGNOSTIC_FINGERPRINT_MISMATCH",
            "diagnostic metric fingerprint",
            (before.run_config.conversation_completeness, before.diagnostic_metadata),
            (after.run_config.conversation_completeness, after.diagnostic_metadata),
        ),
        (
            "METRIC_VERSION_MISMATCH",
            "metric version",
            before.summary.metric_version,
            after.summary.metric_version,
        ),
        (
            "DATASET_HASH_MISMATCH",
            "dataset hash",
            before.dataset_hash,
            after.dataset_hash,
        ),
        (
            "FILTERS_MISMATCH",
            "dataset filters",
            before.run_config.filters,
            after.run_config.filters,
        ),
        (
            "EXECUTION_TYPE_MISMATCH",
            "execution type",
            before.run_config.execution_type,
            after.run_config.execution_type,
        ),
        (
            "TRIAL_COUNT_MISMATCH",
            "trial count",
            before.trials_per_case,
            after.trials_per_case,
        ),
        (
            "CAPABILITY_BUNDLE_MISMATCH",
            "capability bundle",
            before.capability_bundle_sha256,
            after.capability_bundle_sha256,
        ),
        ("PROVIDER_ID_MISMATCH", "provider ID", before.provider_id, after.provider_id),
        (
            "EVALUATION_BACKEND_MISMATCH",
            "evaluation backend",
            before.evaluation_backend,
            after.evaluation_backend,
        ),
        (
            "ASSERTION_REGISTRY_MISMATCH",
            "assertion registry",
            before.assertion_registry_version,
            after.assertion_registry_version,
        ),
        (
            "PASS_THRESHOLD_MISMATCH",
            "pass threshold",
            before.run_config.pass_threshold,
            after.run_config.pass_threshold,
        ),
        (
            "TOOL_PROFILE_MAP_MISMATCH",
            "tool-profile map",
            _tool_profile_map(before),
            _tool_profile_map(after),
        ),
        (
            "JUDGE_FINGERPRINT_MISMATCH",
            "Judge fingerprint",
            before.judge_metadata,
            after.judge_metadata,
        ),
        (
            "TRIAL_SET_MISMATCH",
            "Case/Trial set",
            _trial_keys(before),
            _trial_keys(after),
        ),
    ]
    for code, label, left, right in comparisons:
        _add_if_different(issues, code, label, left, right)
    return ComparabilityReport(
        status="INVALID_COMPARISON" if issues else "COMPARABLE",
        issues=issues,
    )


def _case_map(result: EvaluationRunResult) -> dict[str, CaseResult]:
    return {f"{case.case_id}/{case.trial_id}": case for case in result.cases}


def _delta(case: CaseResult, baseline: Any, candidate: Any) -> TrialDelta:
    return TrialDelta(
        case_id=case.case_id,
        trial_id=case.trial_id,
        baseline=baseline,
        candidate=candidate,
    )


def _judge_deltas(before: CaseResult, after: CaseResult) -> list[TrialDelta]:
    if before.judge_result is None or after.judge_result is None:
        return []
    left_dimensions = {item.name: item.score for item in before.judge_result.dimensions}
    right_dimensions = {item.name: item.score for item in after.judge_result.dimensions}
    common = sorted(set(left_dimensions) & set(right_dimensions))
    if common:
        return [
            TrialDelta(
                case_id=after.case_id,
                trial_id=f"{after.trial_id}:dimension:{name}",
                baseline=left_dimensions[name],
                candidate=right_dimensions[name],
            )
            for name in common
            if left_dimensions[name] != right_dimensions[name]
        ]
    if before.judge_result.score != after.judge_result.score:
        return [_delta(after, before.judge_result.score, after.judge_result.score)]
    return []


def compare_runs(
    baseline: LoadedRunResult, candidate: LoadedRunResult
) -> ComparisonResult:
    report = check_comparability(baseline, candidate)
    before_map = _case_map(baseline.result)
    after_map = _case_map(candidate.result)
    missing = sorted(set(before_map) - set(after_map))
    extra = sorted(set(after_map) - set(before_map))
    common = sorted(set(before_map) & set(after_map))
    result = ComparisonResult(
        comparison_version=COMPARISON_VERSION,
        status=report.status,
        baseline_sha256=baseline.sha256,
        candidate_sha256=candidate.sha256,
        comparability=report,
        missing_trials=missing,
        extra_trials=extra,
    )
    if report.status == "INVALID_COMPARISON":
        return result

    before_performance = run_performance(baseline.result)
    after_performance = run_performance(candidate.result)
    newly_failed = []
    fixed = []
    persistent = []
    new_errors = []
    recovered_errors = []
    judge_deltas = []
    latency_deltas = []
    token_deltas = []
    for key in common:
        before = before_map[key]
        after = after_map[key]
        before_failed = before.quality_conclusion == "FAIL"
        after_failed = after.quality_conclusion == "FAIL"
        if after_failed and not before_failed:
            newly_failed.append(
                _delta(after, before.quality_conclusion, after.quality_conclusion)
            )
        elif before_failed and not after_failed:
            fixed.append(
                _delta(after, before.quality_conclusion, after.quality_conclusion)
            )
        elif before_failed and after_failed:
            persistent.append(
                _delta(after, before.quality_conclusion, after.quality_conclusion)
            )
        before_error = before.execution_status in _ERROR_STATUSES
        after_error = after.execution_status in _ERROR_STATUSES
        if after_error and not before_error:
            new_errors.append(
                _delta(after, before.execution_status, after.execution_status)
            )
        elif before_error and not after_error:
            recovered_errors.append(
                _delta(after, before.execution_status, after.execution_status)
            )
        judge_deltas.extend(_judge_deltas(before, after))
        latency_deltas.append(_delta(after, before.latency_ms, after.latency_ms))
        before_tokens = before_performance.judge_token_totals[key]
        after_tokens = after_performance.judge_token_totals[key]
        if before_tokens is not None or after_tokens is not None:
            token_deltas.append(_delta(after, before_tokens, after_tokens))

    before_stability_cases = (
        baseline.result.stability.cases if baseline.result.stability else []
    )
    after_stability_cases = (
        candidate.result.stability.cases if candidate.result.stability else []
    )
    before_stability = {item.case_id: item for item in before_stability_cases}
    after_stability = {item.case_id: item for item in after_stability_cases}
    newly_unstable = []
    stability_improved = []
    for case_id in sorted(set(before_stability) & set(after_stability)):
        was = before_stability[case_id].quality_volatile
        now = after_stability[case_id].quality_volatile
        if now and not was:
            newly_unstable.append(case_id)
        elif was and not now:
            stability_improved.append(case_id)
    return result.model_copy(
        update={
            "performance": ComparisonPerformance(
                baseline=before_performance, candidate=after_performance
            ),
            "newly_failed": newly_failed,
            "fixed": fixed,
            "persistently_failed": persistent,
            "new_execution_errors": new_errors,
            "recovered_execution_errors": recovered_errors,
            "newly_unstable": newly_unstable,
            "stability_improved": stability_improved,
            "judge_deltas": judge_deltas,
            "latency_deltas": latency_deltas,
            "token_deltas": token_deltas,
        }
    )


def _markdown(result: ComparisonResult) -> str:
    lines = [f"# Comparison: {result.status}", ""]
    if result.comparability.issues:
        lines.extend(["## Comparability", ""])
        lines.extend(
            f"- `{issue.code}`: {issue.message}"
            for issue in result.comparability.issues
        )
        lines.append("")
    sections = [
        ("Regressions", result.newly_failed),
        ("Fixes", result.fixed),
        ("Execution regressions", result.new_execution_errors),
        ("Judge changes", result.judge_deltas),
        ("Latency changes", result.latency_deltas),
        ("Token changes", result.token_deltas),
    ]
    for title, entries in sections:
        lines.extend([f"## {title}", ""])
        if entries:
            lines.extend(
                f"- `{item.case_id}/{item.trial_id}`: "
                f"{item.baseline} → {item.candidate}"
                for item in entries
            )
        else:
            lines.append("- None")
        lines.append("")
    lines.extend(["## Stability", ""])
    lines.append("- Newly unstable: " + (", ".join(result.newly_unstable) or "None"))
    lines.append("- Improved: " + (", ".join(result.stability_improved) or "None"))
    return "\n".join(lines) + "\n"


def write_comparison(
    result: ComparisonResult, output_dir: str | Path
) -> ComparisonPaths:
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "comparison.json"
    markdown_path = root / "comparison.md"
    json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(result), encoding="utf-8")
    return ComparisonPaths(
        json_path=str(json_path),
        markdown_path=str(markdown_path),
    )
