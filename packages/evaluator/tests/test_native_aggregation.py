"""Business eligibility survives replacement with native Inspect reducers."""

import pytest

from eval_framework.stability import aggregate_stability


@pytest.mark.parametrize("passed,expected", [(23, 14.38), (49, 30.62)])
def test_percentage_preserves_historical_rounding(passed, expected):
    from eval_framework.inspect_metrics import native_percentage

    assert native_percentage([1] * passed + [0] * (160 - passed)) == expected


@pytest.mark.parametrize(
    "qualities,planned,rate,any_pass,all_pass",
    [
        (["PASS", "FAIL", "INCONCLUSIVE"], 3, 33.33, True, False),
        (["PASS"], 3, 33.33, True, False),
        (["INCONCLUSIVE"], 3, 0.0, False, False),
        (["PASS", "PASS"], 2, 100.0, True, True),
        (["PASS", "NOT_APPLICABLE"], 2, None, False, False),
    ],
)
def test_native_trial_reduction_preserves_business_denominator(
    case_result_factory, qualities, planned, rate, any_pass, all_pass
):
    cases = [
        case_result_factory(trial_id=f"trial_{i}", quality_conclusion=quality)
        for i, quality in enumerate(qualities)
    ]
    result = aggregate_stability(cases, planned_trials=planned)
    assert result.trial_pass_rate == rate
    case = result.cases[0]
    assert case.trial_pass_rate == rate
    assert case.pass_at_k is any_pass
    assert case.pass_power_k is all_pass


@pytest.mark.parametrize("duplicate", [True, False])
def test_reduction_rejects_trials_outside_the_frozen_plan(
    case_result_factory, duplicate
):
    # Repeated identities and extra epochs cannot manufacture a passing rate.
    cases = [
        case_result_factory(trial_id="trial_1"),
        case_result_factory(trial_id="trial_1" if duplicate else "trial_2"),
    ]
    with pytest.raises(ValueError):
        aggregate_stability(cases, planned_trials=2 if duplicate else 1)


def test_native_reducers_receive_trials_including_missing_attempts(
    case_result_factory, monkeypatch
):
    import eval_framework.stability as stability

    # Transparent spies run the real reducers; the boundary must receive raw
    # binary outcomes, not an already computed custom pass@k/pass^k result.
    seen = {}
    for name in ("pass_at", "pass_k"):
        original = getattr(stability, name, None)
        assert original is not None, f"{name} must use Inspect's reducer"

        def tracked(k, *, _original=original, _name=name):
            reduce = _original(k)

            def calculate(scores):
                seen[_name] = (k, [score.value for score in scores])
                return reduce(scores)

            return calculate

        monkeypatch.setattr(stability, name, tracked)

    result = aggregate_stability([case_result_factory()], planned_trials=3)
    assert result.trial_pass_rate == 33.33
    assert seen == {"pass_at": (3, [1, 0, 0]), "pass_k": (3, [1, 0, 0])}


def test_summary_keeps_unknown_in_denominator_and_excludes_not_applicable(
    case_result_factory, dataset_path
):
    from eval_framework import load_dataset
    from eval_framework.inspect_metrics import summarize

    cases = [
        case_result_factory(latency_ms=10),
        case_result_factory(quality_conclusion="FAIL", score=0, latency_ms=20),
        case_result_factory(
            quality_conclusion="INCONCLUSIVE",
            score=None,
            execution_status="AGENT_EXCEPTION",
            latency_ms=30,
        ),
        case_result_factory(
            quality_conclusion="NOT_APPLICABLE", score=None, latency_ms=40
        ),
    ]
    summary = summarize(cases, load_dataset(dataset_path), "agent_benchmark")
    assert summary.strict_assertion_pass_rate == 33.33
    assert summary.agent_case_pass_rate == 33.33
    assert summary.core_behavior_match_rate == 33.33
    assert summary.framework_completion_rate == 75.0
    assert summary.average_score == 50.0
    assert summary.average_latency_ms == 25.0
    assert summary.median_latency_ms == 25.0
    assert summary.by_scope["module"] == {
        "count": 4,
        "applicable_count": 3,
        "pass_count": 1,
        "pass_rate": 33.33,
    }


def test_stability_reuses_native_categorical_metrics(case_result_factory, monkeypatch):
    import eval_framework.inspect_metrics as metrics

    native = metrics.frequency
    observed = []

    def capture(*args, **kwargs):
        calculate = native(*args, **kwargs)

        def measure(scores):
            observed.append([item.score.value for item in scores])
            return calculate(scores)

        return measure

    monkeypatch.setattr(metrics, "frequency", capture)
    cases = [
        case_result_factory(trial_id="trial_1"),
        case_result_factory(
            trial_id="trial_2",
            quality_conclusion="INCONCLUSIVE",
            execution_status="AGENT_EXCEPTION",
        ),
    ]
    result = aggregate_stability(cases, planned_trials=3)
    assert ["PASS", "INCONCLUSIVE"] in observed
    assert ["COMPLETED", "AGENT_EXCEPTION"] in observed
    assert result.cases[0].fail_count == 0
    assert result.cases[0].inconclusive_count == 1
    assert result.cases[0].completed_trials == 1
    assert result.trial_pass_rate == 33.33
