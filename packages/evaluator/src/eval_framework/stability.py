"""Deterministic aggregation for repeated evaluation Trials."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Any

from inspect_ai.scorer import Score, pass_at, pass_k

from .inspect_metrics import category_counts, native_percentage
from .metric_policy import nearest_rank as nearest_rank
from .phase2_schemas import CaseStabilityResult, PerformanceSummary, RunStability
from .schemas import CaseResult

OutputNormalizer = Callable[[CaseResult], dict[str, Any]]
STABILITY_VERSION = "phase2-stability-v1"

_VOLATILE_KEYS = {
    "agent_run_id",
    "created_at",
    "event_id",
    "finished_at",
    "run_id",
    "session_id",
    "started_at",
    "timestamp",
}


def canonical_observed_output(case: CaseResult) -> dict[str, Any]:
    turns = [
        {
            "status": turn.get("status"),
            "intent_result": turn.get("intent_result"),
            "tool_calls": turn.get("tool_calls", []),
            "final_response": turn.get("final_response"),
        }
        for turn in case.turn_results
    ]
    output = {
        "module_output": case.module_output,
        "turns": turns,
        "system_snapshot": case.system_snapshot,
    }
    if case.observations is not None:
        output["observations"] = case.observations
    return _without_volatile(output)


def observed_output_sha256(
    case: CaseResult,
    normalizer: OutputNormalizer | None = None,
) -> str:
    payload = normalizer(case) if normalizer else canonical_observed_output(case)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def aggregate_stability(
    cases: Sequence[CaseResult],
    *,
    planned_trials: int,
    performance: PerformanceSummary | None = None,
    normalizer: OutputNormalizer | None = None,
) -> RunStability:
    if planned_trials < 1:
        raise ValueError("planned_trials must be positive")
    grouped: dict[str, list[CaseResult]] = defaultdict(list)
    for case in cases:
        grouped[case.case_id].append(case)

    aggregates: list[CaseStabilityResult] = []
    eligible_outcomes: list[int] = []
    for case_id, trials in grouped.items():
        ordered = sorted(trials, key=lambda item: item.trial_id)
        if len({item.trial_id for item in ordered}) != len(ordered):
            raise ValueError(f"Duplicate Trial identity for case {case_id}")
        if len(ordered) > planned_trials:
            raise ValueError(f"Trial count exceeds frozen plan for case {case_id}")
        quality = category_counts([item.quality_conclusion for item in ordered])
        completed = category_counts(
            [item.execution_status for item in ordered]
        ).get("COMPLETED", 0)
        output_hashes = [observed_output_sha256(item, normalizer) for item in ordered]
        applicable = quality.get("NOT_APPLICABLE", 0) == 0
        pass_count = quality.get("PASS", 0)
        # The frozen plan defines the denominator. Missing/unknown attempts do
        # not prove success; these binary observations are not numeric grades.
        outcomes = [int(item.quality_conclusion == "PASS") for item in ordered]
        outcomes.extend([0] * (planned_trials - len(ordered)))
        scores = [Score(value=value) for value in outcomes]
        if applicable:
            eligible_outcomes.extend(outcomes)
        aggregates.append(
            CaseStabilityResult(
                case_id=case_id,
                planned_trials=planned_trials,
                completed_trials=completed,
                pass_count=pass_count,
                fail_count=quality.get("FAIL", 0),
                inconclusive_count=quality.get("INCONCLUSIVE", 0),
                not_applicable_count=quality.get("NOT_APPLICABLE", 0),
                error_count=len(ordered) - completed,
                trial_pass_rate=(native_percentage(outcomes) if applicable else None),
                pass_at_k=applicable and pass_at(planned_trials)(scores).value == 1,
                pass_power_k=applicable and pass_k(planned_trials)(scores).value == 1,
                quality_volatile=len({item.quality_conclusion for item in ordered}) > 1,
                output_volatile=len(set(output_hashes)) > 1,
                output_hashes=output_hashes,
                latency_p50_ms=nearest_rank([item.latency_ms for item in ordered], 0.5),
                latency_p95_ms=nearest_rank(
                    [item.latency_ms for item in ordered], 0.95
                ),
                critical_failure_any=any(
                    assertion.critical and assertion.passed is False
                    for item in ordered
                    for assertion in item.assertion_results
                ),
            )
        )

    eligible = [item for item in aggregates if item.not_applicable_count == 0]
    all_latencies = [item.latency_ms for item in cases]
    return RunStability(
        stability_version=STABILITY_VERSION,
        trials_per_case=planned_trials,
        cases=aggregates,
        pass_at_k_rate=(
            native_percentage([item.pass_at_k for item in eligible])
            if eligible
            else None
        ),
        pass_power_k_rate=(
            native_percentage([item.pass_power_k for item in eligible])
            if eligible
            else None
        ),
        trial_pass_rate=(
            native_percentage(eligible_outcomes) if eligible_outcomes else None
        ),
        latency_p50_ms=(
            performance.latency_p50_ms
            if performance is not None
            else nearest_rank(all_latencies, 0.5)
        ),
        latency_p95_ms=(
            performance.latency_p95_ms
            if performance is not None
            else nearest_rank(all_latencies, 0.95)
        ),
    )


def _without_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_volatile(item)
            for key, item in value.items()
            if key not in _VOLATILE_KEYS
            and not (isinstance(item, str) and item.startswith("/tmp/"))
        }
    if isinstance(value, list):
        return [_without_volatile(item) for item in value]
    return value
