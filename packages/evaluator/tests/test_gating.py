from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_comparison import _stability, loaded

from eval_framework.cli import main
from eval_framework.gating import (
    evaluate_gate,
    load_gate_policy,
    write_gate_result,
)
from eval_framework.phase2_schemas import (
    ComparabilityReport,
    ComparisonResult,
    GatePolicy,
    JudgeDimensionResult,
    JudgeResult,
    TrialDelta,
)
from eval_framework.result_loader import LoadedRunResult
from eval_framework.schemas import AssertionResult


def policy(**updates) -> GatePolicy:
    values = {
        "policy_id": "release",
        "version": "1.0",
        "core_labels": [],
        "zero_tolerance_labels": [],
        "zero_tolerance_assertions": [],
    }
    values.update(updates)
    return GatePolicy.model_validate(values)


def replace_result(value: LoadedRunResult, **updates) -> LoadedRunResult:
    return value.model_copy(update={"result": value.result.model_copy(update=updates)})


def comparison(candidate_sha: str, *, regressions=0, status="COMPARABLE"):
    return ComparisonResult(
        comparison_version="comparison-v1",
        status=status,
        baseline_sha256="baseline-sha",
        candidate_sha256=candidate_sha,
        comparability=ComparabilityReport(status=status),
        newly_failed=[
            TrialDelta(
                case_id=f"case-{index}",
                trial_id="trial_001",
                baseline="PASS",
                candidate="FAIL",
            )
            for index in range(regressions)
        ],
    )


def test_policy_loader_requires_explicit_reference_lists(tmp_path: Path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"policy_id": "release", "version": "1.0"}))

    with pytest.raises(ValueError, match="core_labels"):
        load_gate_policy(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("core_labels", ["unknown-label"]),
        ("zero_tolerance_labels", ["unknown-label"]),
        ("zero_tolerance_assertions", ["unknown-assertion"]),
        ("required_judge_dimensions", {"unknown-dimension": 80}),
    ],
)
def test_unknown_policy_references_are_input_errors(
    case_result_factory, field, value
):
    candidate = loaded(case_result_factory(labels=["known"]), sha="candidate")

    with pytest.raises(ValueError, match="unknown"):
        evaluate_gate(candidate, policy(**{field: value}))


def test_threshold_regression_and_instability_violations_fail(case_result_factory):
    candidate = loaded(
        case_result_factory(),
        sha="candidate",
        stability=_stability(True),
    )
    summary = candidate.result.summary.model_copy(
        update={
            "framework_completion_rate": 80,
            "strict_assertion_pass_rate": 75,
        }
    )
    candidate = replace_result(candidate, summary=summary)
    result = evaluate_gate(
        candidate,
        policy(
            require_comparison=True,
            minimum_execution_rate=90,
            minimum_strict_pass_rate=90,
            minimum_pass_power_k_rate=100,
            maximum_regressions=0,
            maximum_unstable_cases=0,
        ),
        comparison(candidate.sha256, regressions=1),
    )

    assert result.conclusion == "FAIL"
    failed = {check.code for check in result.checks if check.state == "FAIL"}
    assert {
        "MINIMUM_EXECUTION_RATE",
        "MINIMUM_STRICT_PASS_RATE",
        "MAXIMUM_REGRESSIONS",
        "MAXIMUM_UNSTABLE_CASES",
    } <= failed


def test_zero_tolerance_failure_blocks_despite_other_improvements(
    case_result_factory,
):
    assertion = AssertionResult(
        name="no_write_before_confirmation",
        weight=1,
        critical=True,
        passed=False,
        evidence_refs=["snapshot:turn:0/count"],
    )
    case = case_result_factory(
        labels=["safety"],
        assertion_results=[assertion],
        quality_conclusion="FAIL",
    )
    candidate = loaded(case, sha="candidate")

    result = evaluate_gate(
        candidate,
        policy(
            zero_tolerance_labels=["safety"],
            zero_tolerance_assertions=["no_write_before_confirmation"],
        ),
    )

    assert result.conclusion == "FAIL"
    assert {
        "ZERO_TOLERANCE_LABEL_FAILED",
        "ZERO_TOLERANCE_ASSERTION_FAILED",
    } <= {check.code for check in result.checks}


def test_missing_trace_and_insufficient_percentile_samples_require_review(
    case_result_factory,
):
    candidate = loaded(case_result_factory(trace_analysis=None), sha="candidate")

    result = evaluate_gate(
        candidate,
        policy(
            require_trace_evidence=True,
            maximum_latency_p95_ms=100,
            maximum_latency_p50_ms=0,
            minimum_percentile_samples=20,
        ),
    )

    assert result.conclusion == "REVIEW_REQUIRED"
    assert {check.code for check in result.checks if check.state == "REVIEW"} == {
        "TRACE_EVIDENCE_REQUIRED",
        "LATENCY_P95_SAMPLE_INSUFFICIENT",
    }


def test_relative_latency_and_token_regressions_fail(case_result_factory):
    candidate = loaded(case_result_factory(), sha="candidate")
    diff = comparison(candidate.sha256).model_copy(
        update={
            "latency_deltas": [
                TrialDelta(
                    case_id="MODULE-1",
                    trial_id="trial_001",
                    baseline=100,
                    candidate=125,
                )
            ],
            "token_deltas": [
                TrialDelta(
                    case_id="MODULE-1",
                    trial_id="trial_001",
                    baseline=100,
                    candidate=120,
                )
            ],
        }
    )

    result = evaluate_gate(
        candidate,
        policy(
            maximum_latency_p50_increase_percent=10,
            maximum_token_increase_percent=10,
        ),
        diff,
    )

    assert result.conclusion == "FAIL"
    assert {
        "MAXIMUM_LATENCY_P50_INCREASE_PERCENT",
        "MAXIMUM_TOKEN_INCREASE_PERCENT",
    } <= {check.code for check in result.checks if check.state == "FAIL"}


def test_required_judge_dimension_and_absolute_limits(case_result_factory):
    case = case_result_factory(
        latency_ms=120,
        judge_result=JudgeResult(
            status="COMPLETED",
            passed=False,
            score=60,
            dimensions=[
                JudgeDimensionResult(
                    name="clarity",
                    score=60,
                    passed=False,
                    reason="unclear",
                )
            ],
            token_usage={"input_tokens": 80, "output_tokens": 40},
        ),
    )
    candidate = loaded(case, sha="candidate")
    candidate = replace_result(candidate, stability=_stability(False))

    result = evaluate_gate(
        candidate,
        policy(
            required_judge_dimensions={"clarity": 80},
            maximum_latency_p50_ms=100,
            maximum_token_usage=100,
        ),
    )

    assert result.conclusion == "FAIL"
    assert {
        "REQUIRED_JUDGE_DIMENSION",
        "MAXIMUM_LATENCY_P50",
        "MAXIMUM_TOKEN_USAGE",
    } <= {check.code for check in result.checks if check.state == "FAIL"}


def test_invalid_required_comparison_has_highest_precedence(case_result_factory):
    candidate = loaded(case_result_factory(trace_analysis=None), sha="candidate")

    result = evaluate_gate(
        candidate,
        policy(require_comparison=True, require_trace_evidence=True),
        comparison(candidate.sha256, status="INVALID_COMPARISON"),
    )

    assert result.conclusion == "INVALID_COMPARISON"


def test_gate_outputs_and_cli_exit_codes(tmp_path: Path, case_result_factory):
    candidate = loaded(case_result_factory(), sha="candidate")
    gate_policy = policy(minimum_execution_rate=100)
    result = evaluate_gate(candidate, gate_policy)
    paths = write_gate_result(result, tmp_path / "direct")
    assert json.loads(Path(paths.json_path).read_text())["conclusion"] == "PASS"
    assert Path(paths.markdown_path).read_text().startswith("# Gate: PASS")

    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    (candidate_dir / "results.json").write_text(
        candidate.result.model_dump_json(indent=2), encoding="utf-8"
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(gate_policy.model_dump_json(indent=2), encoding="utf-8")
    assert (
        main(
            [
                "gate",
                "--candidate",
                str(candidate_dir),
                "--policy",
                str(policy_path),
                "--output-dir",
                str(tmp_path / "cli"),
            ]
        )
        == 0
    )

    for name, changed_policy, expected in [
        ("fail", policy(maximum_latency_p50_ms=0), 4),
        ("review", policy(require_trace_evidence=True), 5),
        ("invalid", policy(require_comparison=True), 2),
    ]:
        policy_path.write_text(
            changed_policy.model_dump_json(indent=2), encoding="utf-8"
        )
        assert (
            main(
                [
                    "gate",
                    "--candidate",
                    str(candidate_dir),
                    "--policy",
                    str(policy_path),
                    "--output-dir",
                    str(tmp_path / name),
                ]
            )
            == expected
        )
