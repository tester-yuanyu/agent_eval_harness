"""Business population and performance semantics; no independent eval engine."""

from __future__ import annotations

import math
from collections.abc import Sequence

from .phase2_schemas import ComparisonPerformance, ComparisonResult, PerformanceSummary
from .schemas import CaseResult, EvaluationRunResult

METRIC_VERSION = "business-metrics-v2"


def quality_applicable(quality: str, run_mode: str) -> bool:
    return run_mode == "agent_benchmark" and quality != "NOT_APPLICABLE"


def trial_key(case: CaseResult) -> str:
    return f"{case.case_id}/{case.trial_id}"


def nearest_rank(values: Sequence[int | float], percentile: float) -> float | None:
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


def _performance(
    latencies: Sequence[int | float], tokens: dict[str, int | None]
) -> PerformanceSummary:
    known = [value for value in tokens.values() if value is not None]
    return PerformanceSummary(
        latency_sample_count=len(latencies),
        latency_p50_ms=nearest_rank(latencies, 0.5),
        latency_p95_ms=nearest_rank(latencies, 0.95),
        judge_token_totals=tokens,
        judge_token_total=sum(known) if known else None,
        judge_token_max=max(known) if known else None,
    )


def build_performance(cases: Sequence[CaseResult]) -> PerformanceSummary:
    """Compute once during formal aggregation, or project a historical run."""
    tokens = {
        trial_key(case): sum(case.judge_result.token_usage.values())
        if case.judge_result is not None and case.judge_result.token_usage
        else None
        for case in cases
    }
    return _performance([case.latency_ms for case in cases], tokens)


def run_performance(result: EvaluationRunResult) -> PerformanceSummary:
    """Use authoritative stored metrics; legacy projection never rewrites a run."""
    if result.summary.performance is not None:
        return result.summary.performance
    return build_performance(result.cases)


def comparison_performance(result: ComparisonResult) -> ComparisonPerformance:
    """Old comparison files only have paired deltas; adapt those in one place."""
    if result.performance is not None:
        return result.performance

    def side(name: str) -> PerformanceSummary:
        latencies = [
            float(value)
            for item in result.latency_deltas
            if (value := getattr(item, name)) is not None
        ]
        tokens = {
            f"{item.case_id}/{item.trial_id}": int(value) if value is not None else None
            for item in result.token_deltas
            for value in [getattr(item, name)]
        }
        return _performance(latencies, tokens)

    return ComparisonPerformance(baseline=side("baseline"), candidate=side("candidate"))
