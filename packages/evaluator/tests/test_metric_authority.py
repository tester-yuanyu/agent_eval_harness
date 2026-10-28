"""Formal aggregation is the authority for consumers and scoped business metrics."""

import pytest
from test_comparison import loaded
from test_gating import policy

from eval_framework import load_dataset
from eval_framework.comparison import check_comparability, compare_runs
from eval_framework.gating import evaluate_gate
from eval_framework.inspect_metrics import summarize
from eval_framework.phase2_schemas import JudgeResult
from eval_framework.stability import aggregate_stability


def with_summary(cases, dataset_path, *, sha="candidate", mode="agent_benchmark"):
    summary = summarize(cases, load_dataset(dataset_path), mode)
    return loaded(cases[0], sha=sha, cases=cases, summary=summary)


@pytest.mark.parametrize("mode", ["agent_benchmark", "framework_self_test"])
def test_no_quality_rate_for_inapplicable_group(
    case_result_factory, dataset_path, mode
):
    case = case_result_factory(quality_conclusion="NOT_APPLICABLE", score=None)
    summary = summarize([case], load_dataset(dataset_path), mode)
    assert summary.by_scope["module"]["pass_rate"] is None
    assert summary.by_scope["module"]["applicable_count"] == 0
    assert summary.strict_assertion_pass_rate is None


def test_framework_run_does_not_publish_group_agent_pass_rate(
    case_result_factory, dataset_path
):
    summary = summarize(
        [case_result_factory()], load_dataset(dataset_path), "framework_self_test"
    )
    assert summary.by_scope["module"]["pass_rate"] is None


def test_saved_performance_drives_stability_gate_and_comparison(
    case_result_factory, dataset_path, monkeypatch
):
    from eval_framework import metric_policy

    usages = [{"input_tokens": 12}, {"input_tokens": 0}, {}, {"output_tokens": 8}]
    cases = [
        case_result_factory(
            trial_id=f"trial_{i}",
            latency_ms=latency,
            judge_result=JudgeResult(status="COMPLETED", token_usage=usage),
        )
        for i, (latency, usage) in enumerate(zip([10, 20, 30, 40], usages, strict=True))
    ]
    run = with_summary(cases, dataset_path)
    perf = run.result.summary.performance
    assert perf.latency_sample_count == 4
    assert (perf.latency_p50_ms, perf.latency_p95_ms) == (20, 40)
    assert perf.judge_token_total == 20
    assert perf.judge_token_max == 12
    assert perf.judge_token_totals["MODULE-1/trial_1"] == 0
    assert perf.judge_token_totals["MODULE-1/trial_2"] is None
    assert run.result.summary.median_latency_ms == 25
    stability = aggregate_stability(cases, planned_trials=4, performance=perf)
    assert stability.latency_p50_ms == 20

    def forbidden(*args, **kwargs):
        raise AssertionError("consumer recomputed saved run metrics")

    monkeypatch.setattr(metric_policy, "build_performance", forbidden)
    baseline = run.model_copy(update={"sha256": "baseline"})
    diff = compare_runs(baseline, run)
    assert diff.performance.baseline == perf
    assert diff.performance.candidate == perf
    gate = evaluate_gate(
        run,
        policy(
            maximum_latency_p50_ms=20,
            maximum_latency_p95_ms=40,
            minimum_percentile_samples=4,
            maximum_token_usage=12,
            maximum_token_increase_percent=0,
        ),
        diff,
    )
    assert gate.conclusion == "PASS"
    assert diff.token_deltas[1].candidate == 0


def test_gate_label_union_uses_same_eligibility_without_double_counting(
    case_result_factory, dataset_path
):
    cases = [
        case_result_factory(trial_id="trial_1", labels=["core", "shared"]),
        case_result_factory(
            trial_id="trial_2", labels=["core"], quality_conclusion="NOT_APPLICABLE"
        ),
        case_result_factory(
            trial_id="trial_3", labels=["outside"], quality_conclusion="FAIL"
        ),
    ]
    run = with_summary(cases, dataset_path)
    assert run.result.summary.strict_assertion_pass_rate == 50
    assert run.result.summary.by_scope["module"]["pass_rate"] == 50
    gate = evaluate_gate(
        run, policy(core_labels=["core", "shared"], minimum_strict_pass_rate=100)
    )
    check = next(x for x in gate.checks if x.code == "MINIMUM_STRICT_PASS_RATE")
    assert check.actual == 100
    assert check.state == "PASS"
    assert set(check.evidence_refs) == {
        "case:MODULE-1/trial_1",
        "case:MODULE-1/trial_2",
    }


def test_metric_version_change_requires_new_baseline(case_result_factory, dataset_path):
    old = loaded(case_result_factory(), sha="old")
    new = with_summary([case_result_factory()], dataset_path)
    report = check_comparability(old, new)
    assert report.status == "INVALID_COMPARISON"
    assert "METRIC_VERSION_MISMATCH" in {item.code for item in report.issues}


def test_legacy_projection_is_read_only(case_result_factory, tmp_path):
    from eval_framework.metric_policy import run_performance
    from eval_framework.result_loader import load_run_result

    old = loaded(case_result_factory(latency_ms=17))
    payload = old.result.model_dump(mode="json")
    payload["summary"].pop("performance", None)
    payload["summary"].pop("metric_version", None)
    import json

    source = tmp_path / "results.json"
    source.write_text(json.dumps(payload))
    original = source.read_bytes()
    restored = load_run_result(source)
    before = restored.result.model_dump_json()
    assert run_performance(restored.result).latency_p50_ms == 17
    assert (
        evaluate_gate(restored, policy(maximum_latency_p50_ms=17)).conclusion == "PASS"
    )
    assert restored.result.model_dump_json() == before
    assert source.read_bytes() == original


def test_empty_run_has_no_performance_or_quality_success(dataset_path):
    summary = summarize([], load_dataset(dataset_path), "agent_benchmark")
    assert summary.strict_assertion_pass_rate is None
    assert summary.by_scope == {}
    assert summary.performance.latency_sample_count == 0
    assert summary.performance.latency_p50_ms is None
    assert summary.performance.judge_token_total is None


def test_only_inapplicable_label_scope_requires_review(
    case_result_factory, dataset_path
):
    run = with_summary(
        [
            case_result_factory(quality_conclusion="NOT_APPLICABLE", labels=["core"]),
        ],
        dataset_path,
    )
    gate = evaluate_gate(run, policy(core_labels=["core"], minimum_strict_pass_rate=90))
    assert gate.conclusion == "REVIEW_REQUIRED"
