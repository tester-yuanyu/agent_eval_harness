"""Versioned, auditable local release gates."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .inspect_metrics import quality_pass_rate
from .metric_policy import METRIC_VERSION, comparison_performance, run_performance
from .phase2_schemas import (
    ComparisonResult,
    GateCheckResult,
    GatePaths,
    GatePolicy,
    GateResult,
)
from .result_loader import LoadedRunResult

GATE_VERSION = "gate-v2"
_REQUIRED_LISTS = (
    "core_labels",
    "zero_tolerance_labels",
    "zero_tolerance_assertions",
)


def load_gate_policy(path: str | Path) -> GatePolicy:
    source = Path(path).expanduser().resolve()
    raw = json.loads(source.read_text(encoding="utf-8"))
    missing = [name for name in _REQUIRED_LISTS if name not in raw]
    if missing:
        raise ValueError("Gate Policy must explicitly declare " + ", ".join(missing))
    return GatePolicy.model_validate(raw)


def _validate_references(candidate: LoadedRunResult, policy: GatePolicy) -> None:
    labels = {label for case in candidate.result.cases for label in case.labels}
    assertions = {
        item.name for case in candidate.result.cases for item in case.assertion_results
    }
    judge_dimensions = {
        item.name
        for case in candidate.result.cases
        if case.judge_result is not None
        for item in case.judge_result.dimensions
    }
    unknown_labels = sorted(
        (set(policy.core_labels) | set(policy.zero_tolerance_labels)) - labels
    )
    unknown_assertions = sorted(set(policy.zero_tolerance_assertions) - assertions)
    unknown_dimensions = sorted(
        set(policy.required_judge_dimensions) - judge_dimensions
    )
    unknown = [
        *(f"label:{value}" for value in unknown_labels),
        *(f"assertion:{value}" for value in unknown_assertions),
        *(f"judge_dimension:{value}" for value in unknown_dimensions),
    ]
    if unknown:
        raise ValueError("unknown Gate Policy references: " + ", ".join(unknown))


def _check(
    code: str,
    state: str,
    operator: str,
    threshold: Any,
    actual: Any,
    refs: list[str] | None = None,
) -> GateCheckResult:
    return GateCheckResult(
        code=code,
        state=state,
        operator=operator,
        threshold=threshold,
        actual=actual,
        evidence_refs=refs or [],
    )


def _minimum(code: str, threshold: float, actual: float | None) -> GateCheckResult:
    if actual is None:
        return _check(code, "REVIEW", ">=", threshold, None)
    return _check(
        code,
        "PASS" if actual >= threshold else "FAIL",
        ">=",
        threshold,
        actual,
    )


def _maximum(code: str, threshold: float, actual: float | None) -> GateCheckResult:
    if actual is None:
        return _check(code, "REVIEW", "<=", threshold, None)
    return _check(
        code,
        "PASS" if actual <= threshold else "FAIL",
        "<=",
        threshold,
        actual,
    )


def _comparison_required(policy: GatePolicy) -> bool:
    return (
        any(
            value is not None
            for value in (
                policy.maximum_regressions,
                policy.maximum_latency_p50_increase_percent,
                policy.maximum_latency_p95_increase_percent,
                policy.maximum_token_increase_percent,
            )
        )
        or policy.require_comparison
    )


def _relative_increase(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    if before == 0:
        return 0.0 if after == 0 else math.inf
    return round((after - before) / before * 100, 4)


def _comparison_hash(comparison: ComparisonResult | None) -> str | None:
    if comparison is None:
        return None
    raw = comparison.model_dump_json().encode()
    return hashlib.sha256(raw).hexdigest()


def evaluate_gate(
    candidate: LoadedRunResult,
    policy: GatePolicy,
    comparison: ComparisonResult | None = None,
) -> GateResult:
    _validate_references(candidate, policy)
    checks: list[GateCheckResult] = []
    onboarding = candidate.result.onboarding
    if onboarding is not None and onboarding.get("release_eligible") is not True:
        checks.append(
            _check(
                "ONBOARDING_RELEASE_INELIGIBLE",
                "FAIL",
                "==",
                True,
                onboarding.get("release_eligible"),
            )
        )
    invalid_trials = [
        f"{case.case_id}/{case.trial_id}"
        for case in candidate.result.cases
        if case.evaluation_validity == "INVALID"
    ]
    if invalid_trials:
        checks.append(
            _check(
                "EVALUATION_INVALID",
                "FAIL",
                "==",
                0,
                len(invalid_trials),
                invalid_trials,
            )
        )
    comparison_needed = _comparison_required(policy)
    comparison_invalid = comparison_needed and (
        comparison is None
        or comparison.status != "COMPARABLE"
        or comparison.candidate_sha256 != candidate.sha256
    )
    if comparison_invalid:
        checks.append(
            _check(
                "VALID_COMPARISON_REQUIRED",
                "FAIL",
                "==",
                "COMPARABLE candidate identity",
                None if comparison is None else comparison.status,
            )
        )

    summary = candidate.result.summary
    if policy.minimum_execution_rate is not None:
        checks.append(
            _minimum(
                "MINIMUM_EXECUTION_RATE",
                policy.minimum_execution_rate,
                summary.framework_completion_rate,
            )
        )
    if policy.minimum_strict_pass_rate is not None:
        refs: list[str] = []
        if policy.core_labels:
            core = [
                case
                for case in candidate.result.cases
                if set(case.labels) & set(policy.core_labels)
            ]
            # Label unions are a separate scoped metric. Reuse the saved rate
            # when its population is the whole run under the current policy.
            strict_rate = (
                summary.strict_assertion_pass_rate
                if len(core) == len(candidate.result.cases)
                and summary.metric_version == METRIC_VERSION
                else quality_pass_rate(core, candidate.result.run_config.run_mode)
            )
            refs = [f"case:{case.case_id}/{case.trial_id}" for case in core]
        else:
            strict_rate = summary.strict_assertion_pass_rate
        check = _minimum(
            "MINIMUM_STRICT_PASS_RATE", policy.minimum_strict_pass_rate, strict_rate
        )
        checks.append(check.model_copy(update={"evidence_refs": refs}))
    stability = candidate.result.stability
    if policy.minimum_pass_power_k_rate is not None:
        checks.append(
            _minimum(
                "MINIMUM_PASS_POWER_K_RATE",
                policy.minimum_pass_power_k_rate,
                stability.pass_power_k_rate if stability else None,
            )
        )
    if policy.maximum_regressions is not None and comparison is not None:
        regression_count = len(comparison.newly_failed) + len(
            comparison.new_execution_errors
        )
        checks.append(
            _maximum(
                "MAXIMUM_REGRESSIONS",
                policy.maximum_regressions,
                regression_count,
            )
        )
    if policy.maximum_unstable_cases is not None:
        unstable = (
            sum(item.quality_volatile for item in stability.cases)
            if stability
            else None
        )
        checks.append(
            _maximum(
                "MAXIMUM_UNSTABLE_CASES",
                policy.maximum_unstable_cases,
                unstable,
            )
        )

    for label in policy.zero_tolerance_labels:
        failed = [
            case
            for case in candidate.result.cases
            if label in case.labels and case.quality_conclusion != "PASS"
        ]
        checks.append(
            _check(
                "ZERO_TOLERANCE_LABEL_FAILED",
                "FAIL" if failed else "PASS",
                "==",
                0,
                len(failed),
                [f"case:{case.case_id}/{case.trial_id}" for case in failed],
            )
        )
    for name in policy.zero_tolerance_assertions:
        failed_assertions = [
            (case, item)
            for case in candidate.result.cases
            for item in case.assertion_results
            if item.name == name and item.passed is False
        ]
        refs = [ref for _, item in failed_assertions for ref in item.evidence_refs]
        checks.append(
            _check(
                "ZERO_TOLERANCE_ASSERTION_FAILED",
                "FAIL" if failed_assertions else "PASS",
                "==",
                0,
                len(failed_assertions),
                refs,
            )
        )

    for name, threshold in policy.required_judge_dimensions.items():
        scores = [
            dimension.score
            for case in candidate.result.cases
            if case.judge_result is not None
            for dimension in case.judge_result.dimensions
            if dimension.name == name
        ]
        checks.append(
            _minimum(
                "REQUIRED_JUDGE_DIMENSION",
                threshold,
                min(scores) if scores else None,
            )
        )

    performance = run_performance(candidate.result)
    p50, p95 = performance.latency_p50_ms, performance.latency_p95_ms
    if policy.maximum_latency_p50_ms is not None:
        checks.append(
            _maximum("MAXIMUM_LATENCY_P50", policy.maximum_latency_p50_ms, p50)
        )
    if policy.maximum_latency_p95_ms is not None:
        if performance.latency_sample_count < policy.minimum_percentile_samples:
            checks.append(
                _check(
                    "LATENCY_P95_SAMPLE_INSUFFICIENT",
                    "REVIEW",
                    ">=",
                    policy.minimum_percentile_samples,
                    performance.latency_sample_count,
                )
            )
        else:
            checks.append(
                _maximum(
                    "MAXIMUM_LATENCY_P95",
                    policy.maximum_latency_p95_ms,
                    p95,
                )
            )
    if policy.maximum_token_usage is not None:
        checks.append(
            _maximum(
                "MAXIMUM_TOKEN_USAGE",
                policy.maximum_token_usage,
                performance.judge_token_max,
            )
        )

    if comparison is not None and comparison.status == "COMPARABLE":
        paired = comparison_performance(comparison)
        before, after = paired.baseline, paired.candidate
        relative_metrics = [
            (
                "MAXIMUM_LATENCY_P50_INCREASE_PERCENT",
                policy.maximum_latency_p50_increase_percent,
                _relative_increase(before.latency_p50_ms, after.latency_p50_ms),
            ),
            (
                "MAXIMUM_TOKEN_INCREASE_PERCENT",
                policy.maximum_token_increase_percent,
                _relative_increase(before.judge_token_total, after.judge_token_total),
            ),
        ]
        if policy.maximum_latency_p95_increase_percent is not None:
            sample_count = min(before.latency_sample_count, after.latency_sample_count)
            if sample_count < policy.minimum_percentile_samples:
                checks.append(
                    _check(
                        "LATENCY_P95_RELATIVE_SAMPLE_INSUFFICIENT",
                        "REVIEW",
                        ">=",
                        policy.minimum_percentile_samples,
                        sample_count,
                    )
                )
            else:
                relative_metrics.append(
                    (
                        "MAXIMUM_LATENCY_P95_INCREASE_PERCENT",
                        policy.maximum_latency_p95_increase_percent,
                        _relative_increase(before.latency_p95_ms, after.latency_p95_ms),
                    )
                )
        for code, threshold, actual in relative_metrics:
            if threshold is not None:
                checks.append(_maximum(code, threshold, actual))

    if policy.require_trace_evidence:
        missing_trace = [
            case for case in candidate.result.cases if case.trace_analysis is None
        ]
        checks.append(
            _check(
                "TRACE_EVIDENCE_REQUIRED",
                "REVIEW" if missing_trace else "PASS",
                "==",
                0,
                len(missing_trace),
                [f"case:{case.case_id}/{case.trial_id}" for case in missing_trace],
            )
        )

    if comparison_invalid:
        conclusion = "INVALID_COMPARISON"
    elif any(check.state == "REVIEW" for check in checks):
        conclusion = "REVIEW_REQUIRED"
    elif any(check.state == "FAIL" for check in checks):
        conclusion = "FAIL"
    else:
        conclusion = "PASS"
    return GateResult(
        gate_version=GATE_VERSION,
        conclusion=conclusion,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        candidate_sha256=candidate.sha256,
        comparison_sha256=_comparison_hash(comparison),
        checks=checks,
    )


def _markdown(result: GateResult) -> str:
    lines = [f"# Gate: {result.conclusion}", "", "## Checks", ""]
    if not result.checks:
        lines.append("- No configured checks")
    else:
        lines.extend(
            f"- **{check.state}** `{check.code}`: actual={check.actual!r} "
            f"{check.operator} threshold={check.threshold!r}"
            for check in result.checks
        )
    return "\n".join(lines) + "\n"


def write_gate_result(result: GateResult, output_dir: str | Path) -> GatePaths:
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "gate.json"
    markdown_path = root / "gate.md"
    json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(result), encoding="utf-8")
    return GatePaths(json_path=str(json_path), markdown_path=str(markdown_path))
