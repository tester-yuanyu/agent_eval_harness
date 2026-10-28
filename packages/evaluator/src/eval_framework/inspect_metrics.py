"""Business aggregation invoked once by Inspect; reports consume its snapshot."""

from collections.abc import Sequence
from typing import cast

from inspect_ai.scorer import SampleScore, Score, frequency, grouped, mean, median_score

from .diagnostic_metrics import DiagnosticMetricSummary
from .metric_policy import METRIC_VERSION, build_performance, quality_applicable
from .schemas import CaseResult, DatasetBundle, SummaryStats


def native_mean(values: list[float | int]) -> float:
    """Use Inspect mean after business code has selected eligible observations."""
    return float(mean()([SampleScore(score=Score(value=v)) for v in values]))


def native_percentage(values: list[bool | int]) -> float:
    """Format Inspect's binary mean; callers own eligibility, not arithmetic."""
    # Scale observations before aggregation to retain the historical floating
    # point rounding of (100 * passed / total), including half-cent boundaries.
    return round(native_mean([100 * value for value in values]), 2)


def category_counts(values: Sequence[str]) -> dict[str, int]:
    counts = frequency(normalize=False)(
        [SampleScore(score=Score(value=value)) for value in values]
    )
    return {key: int(value) for key, value in cast(dict[str, float], counts).items()}


def quality_pass_rate(cases: Sequence[CaseResult], run_mode: str) -> float | None:
    eligible = [
        case for case in cases if quality_applicable(case.quality_conclusion, run_mode)
    ]
    return (
        native_percentage([case.quality_conclusion == "PASS" for case in eligible])
        if eligible
        else None
    )


def grouped_quality(
    values: list[tuple[str, CaseResult]], run_mode: str
) -> dict[str, dict[str, float | int | None]]:
    observations = [
        SampleScore(
            score=Score(value=case.quality_conclusion), sample_metadata={"group": key}
        )
        for key, case in values
    ]
    counts = cast(
        dict[str, dict[str, float]],
        grouped(frequency(normalize=False), "group", all=False)(observations),
    )
    applicable = [
        SampleScore(
            score=Score(value=100 * int(case.quality_conclusion == "PASS")),
            sample_metadata={"group": key},
        )
        for key, case in values
        if quality_applicable(case.quality_conclusion, run_mode)
    ]
    rates = cast(dict[str, float], grouped(mean(), "group", all=False)(applicable))
    return {
        key: {
            "count": int(sum(categories.values())),
            "applicable_count": int(
                sum(
                    n
                    for quality, n in categories.items()
                    if quality_applicable(quality, run_mode)
                )
            ),
            "pass_count": int(categories.get("PASS", 0)),
            "pass_rate": round(rates[key], 2) if key in rates else None,
        }
        for key, categories in counts.items()
    }


def summarize(
    results: list[CaseResult], dataset: DatasetBundle, run_mode: str
) -> SummaryStats:
    execution = category_counts([item.execution_status for item in results])
    quality = category_counts([item.quality_conclusion for item in results])
    scored = [item for item in results if item.score is not None]

    cases_by_id = {case.case_id: case for case in dataset.cases}
    scopes = [(cases_by_id[item.case_id].test_scope, item) for item in results]
    tasks = [(cases_by_id[item.case_id].task_id, item) for item in results]
    actual_intents = []
    expected_intents = []
    for item in results:
        intent = (item.module_output or {}).get("intent")
        if intent is None and item.turn_results:
            intent = item.turn_results[-1].get("intent_result", {}).get("intent")
        actual_intents.append((intent or "unknown", item))
        expected = (cases_by_id[item.case_id].oracle.expected_module_output or {}).get(
            "intent"
        )
        expected_intents.append((expected or cases_by_id[item.case_id].target, item))
    failed = category_counts(
        [
            assertion.name
            for item in results
            for assertion in item.assertion_results
            if assertion.passed is False
        ]
    )
    total_trials = len(results)
    total_cases = len({item.case_id for item in results})
    eligible = [
        item
        for item in results
        if quality_applicable(item.quality_conclusion, run_mode)
    ]
    strict_rate = quality_pass_rate(results, run_mode)
    by_expected = grouped_quality(expected_intents, run_mode)
    return SummaryStats(
        diagnostic_metrics=_diagnostic_summaries(results),
        metric_version=METRIC_VERSION,
        performance=build_performance(results),
        total_cases=total_cases,
        total_trials=total_trials,
        execution_status_counts=dict(execution),
        quality_counts=dict(quality),
        framework_completion_rate=native_percentage(
            [item.execution_status == "COMPLETED" for item in results]
        ),
        agent_case_pass_rate=strict_rate,
        strict_assertion_pass_rate=strict_rate,
        core_behavior_match_rate=(
            native_percentage([_core_behavior_matches(item) for item in eligible])
            if eligible
            else None
        ),
        average_score=(
            round(native_mean([item.score for item in scored]), 2) if scored else None
        ),
        average_latency_ms=(
            round(native_mean([item.latency_ms for item in results]), 2)
            if total_trials
            else 0.0
        ),
        median_latency_ms=(
            round(
                float(
                    median_score()(
                        [Score(value=item.latency_ms) for item in results]
                    ).value
                ),
                2,
            )
            if total_trials
            else 0.0
        ),
        max_latency_ms=max((item.latency_ms for item in results), default=0),
        by_scope=grouped_quality(scopes, run_mode),
        by_intent=by_expected,
        by_expected_intent=by_expected,
        by_actual_intent=grouped_quality(actual_intents, run_mode),
        by_task_id=grouped_quality(tasks, run_mode),
        failed_assertions=dict(failed),
    )


def _diagnostic_summaries(results):
    summaries = {}
    for name in sorted({name for row in results for name in row.diagnostic_metrics}):
        metrics = [row.diagnostic_metrics[name] for row in results
                   if name in row.diagnostic_metrics]
        values = [m.score for m in metrics if m.status == "SUCCESS"]
        summaries[name] = DiagnosticMetricSummary(
            status_counts=category_counts([m.status for m in metrics]),
            scored_trials=len(values),
            mean_score=native_mean(values) if values else None,
        )
    return summaries


def _core_behavior_matches(case: CaseResult) -> bool:
    if case.execution_status != "COMPLETED" or case.evaluation_validity == "INVALID":
        return False
    if case.quality_conclusion == "PASS":
        return True
    return bool(case.diagnoses) and all(
        diagnosis.code == "PROTOCOL_NAMING_MISMATCH" for diagnosis in case.diagnoses
    )
