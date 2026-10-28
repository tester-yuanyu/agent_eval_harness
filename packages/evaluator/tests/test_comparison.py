from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_framework.cli import main
from eval_framework.comparison import (
    check_comparability,
    compare_runs,
    write_comparison,
)
from eval_framework.phase2_schemas import (
    CaseStabilityResult,
    JudgeResult,
    RunStability,
)
from eval_framework.result_loader import LoadedRunResult
from eval_framework.schemas import EvaluationRunResult


def loaded(case, *, sha="sha", **updates):
    payload = {
        "evaluator_run_id": f"run-{sha}",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:00:01Z",
        "dataset_path": "dataset.jsonl",
        "dataset_version": "1.0",
        "dataset_hash": "dataset-hash",
        "dataset_total_cases": 1,
        "dataset_lifecycle_state": "FROZEN",
        "agent_version": "agent-v1",
        "provider_id": "mini_agent",
        "provider_version": "provider-v1",
        "capability_bundle_sha256": "capabilities-hash",
        "model_metadata": {"model": "agent-model-v1", "prompt": "agent-p1"},
        "assertion_registry_version": "assertions-v1",
        "run_config": {
            "run_mode": "agent_benchmark",
            "execution_type": "full",
            "trials_per_case": 1,
        },
        "cases": [case],
        "summary": {
            "total_cases": 1,
            "total_trials": 1,
            "execution_status_counts": {case.execution_status: 1},
            "quality_counts": {case.quality_conclusion: 1},
            "framework_completion_rate": 100,
            "agent_case_pass_rate": 100,
            "average_score": case.score,
            "average_latency_ms": case.latency_ms,
            "median_latency_ms": case.latency_ms,
            "max_latency_ms": case.latency_ms,
            "by_scope": {},
            "by_intent": {},
            "by_task_id": {},
            "failed_assertions": {},
        },
        "trials_per_case": 1,
        "total_duration_ms": case.latency_ms,
        "judge_metadata": {
            "provider": "deepseek",
            "model": "judge-v1",
            "prompt_version": "judge-p1",
            "rubric_id": "semantic-response",
            "rubric_version": "1.0",
            "output_schema_version": "output-v1",
            "rubric_sha256": "rubric-hash",
            "timeout_seconds": 30,
            "max_retries": 1,
        },
    }
    payload.update(updates)
    return LoadedRunResult(
        result=EvaluationRunResult.model_validate(payload),
        source_path=f"/{sha}/results.json",
        sha256=sha,
    )


def test_identical_protocols_are_comparable(case_result_factory):
    baseline = loaded(case_result_factory(), sha="baseline")
    candidate = loaded(
        case_result_factory(),
        sha="candidate",
        agent_version="agent-v2",
        provider_version="provider-v2",
        model_metadata={"model": "agent-model-v2", "prompt": "agent-p2"},
    )

    report = check_comparability(baseline, candidate)

    assert report.status == "COMPARABLE"
    assert report.issues == []


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"dataset_lifecycle_state": "DRAFT"}, "NON_FROZEN_INPUT"),
        ({"dataset_hash": "other"}, "DATASET_HASH_MISMATCH"),
        ({"provider_id": "other"}, "PROVIDER_ID_MISMATCH"),
        (
            {"capability_bundle_sha256": "other"},
            "CAPABILITY_BUNDLE_MISMATCH",
        ),
        (
            {"assertion_registry_version": "other"},
            "ASSERTION_REGISTRY_MISMATCH",
        ),
        ({"judge_metadata": None}, "JUDGE_FINGERPRINT_MISMATCH"),
    ],
)
def test_required_protocol_mismatches_are_all_invalid(
    case_result_factory, change, code
):
    baseline = loaded(case_result_factory(), sha="baseline")
    candidate = loaded(case_result_factory(), sha="candidate", **change)

    report = check_comparability(baseline, candidate)

    assert report.status == "INVALID_COMPARISON"
    assert code in {issue.code for issue in report.issues}


def test_run_config_tool_profile_and_trial_alignment_are_strict(case_result_factory):
    baseline = loaded(case_result_factory(), sha="baseline")
    changed = case_result_factory(
        trial_id="trial_002",
        tool_profile="shadow_read",
    )
    candidate = loaded(
        changed,
        sha="candidate",
        run_config={
            "run_mode": "agent_benchmark",
            "execution_type": "filtered_subset",
            "filters": {"labels": ["core"]},
            "pass_threshold": 90,
            "trials_per_case": 2,
        },
        trials_per_case=2,
    )

    comparison = compare_runs(baseline, candidate)
    codes = {issue.code for issue in comparison.comparability.issues}

    assert {
        "FILTERS_MISMATCH",
        "EXECUTION_TYPE_MISMATCH",
        "TRIAL_COUNT_MISMATCH",
        "PASS_THRESHOLD_MISMATCH",
        "TOOL_PROFILE_MAP_MISMATCH",
        "TRIAL_SET_MISMATCH",
    } <= codes
    assert comparison.status == "INVALID_COMPARISON"
    assert comparison.newly_failed == []
    assert comparison.missing_trials == ["MODULE-1/trial_001"]
    assert comparison.extra_trials == ["MODULE-1/trial_002"]


def _stability(volatile: bool) -> RunStability:
    return RunStability(
        stability_version="stability-v1",
        trials_per_case=1,
        cases=[
            CaseStabilityResult(
                case_id="MODULE-1",
                planned_trials=1,
                completed_trials=1,
                pass_count=1,
                fail_count=0,
                inconclusive_count=0,
                not_applicable_count=0,
                error_count=0,
                trial_pass_rate=100,
                pass_at_k=True,
                pass_power_k=True,
                quality_volatile=volatile,
                output_volatile=False,
            )
        ],
        pass_at_k_rate=100,
        pass_power_k_rate=100,
        trial_pass_rate=100,
    )


def test_comparison_classifies_quality_execution_judge_and_stability_deltas(
    case_result_factory,
):
    baseline_case = case_result_factory(
        latency_ms=10,
        judge_result=JudgeResult(
            status="COMPLETED",
            score=90,
            passed=True,
            token_usage={"input_tokens": 10, "output_tokens": 5},
        ),
    )
    candidate_case = baseline_case.model_copy(
        update={
            "quality_conclusion": "FAIL",
            "latency_ms": 25,
            "judge_result": JudgeResult(
                status="COMPLETED",
                score=70,
                passed=False,
                token_usage={"input_tokens": 20, "output_tokens": 8},
            ),
        }
    )
    baseline = loaded(baseline_case, sha="baseline", stability=_stability(False))
    candidate = loaded(candidate_case, sha="candidate", stability=_stability(True))

    comparison = compare_runs(baseline, candidate)

    assert comparison.status == "COMPARABLE"
    assert [(item.case_id, item.trial_id) for item in comparison.newly_failed] == [
        ("MODULE-1", "trial_001")
    ]
    assert comparison.newly_unstable == ["MODULE-1"]
    assert comparison.judge_deltas[0].baseline == 90
    assert comparison.judge_deltas[0].candidate == 70
    assert comparison.latency_deltas[0].candidate == 25
    assert comparison.token_deltas[0].candidate == 28


def test_comparison_outputs_reload(tmp_path: Path, case_result_factory):
    result = compare_runs(
        loaded(case_result_factory(), sha="baseline"),
        loaded(case_result_factory(), sha="candidate"),
    )

    paths = write_comparison(result, tmp_path)

    assert json.loads(Path(paths.json_path).read_text())["status"] == "COMPARABLE"
    assert Path(paths.markdown_path).read_text().startswith("# Comparison: COMPARABLE")


def test_compare_cli_writes_outputs_and_uses_invalid_exit_code(
    tmp_path: Path, case_result_factory
):
    baseline = loaded(case_result_factory(), sha="baseline")
    candidate = loaded(case_result_factory(), sha="candidate")
    baseline_dir = tmp_path / "baseline"
    candidate_dir = tmp_path / "candidate"
    output_dir = tmp_path / "comparison"
    baseline_dir.mkdir()
    candidate_dir.mkdir()
    (baseline_dir / "results.json").write_text(
        baseline.result.model_dump_json(indent=2), encoding="utf-8"
    )
    (candidate_dir / "results.json").write_text(
        candidate.result.model_dump_json(indent=2), encoding="utf-8"
    )

    assert (
        main(
            [
                "compare",
                "--baseline",
                str(baseline_dir),
                "--candidate",
                str(candidate_dir),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    assert (output_dir / "comparison.json").is_file()

    changed = candidate.result.model_copy(update={"dataset_hash": "different"})
    (candidate_dir / "results.json").write_text(
        changed.model_dump_json(indent=2), encoding="utf-8"
    )
    assert (
        main(
            [
                "compare",
                "--baseline",
                str(baseline_dir),
                "--candidate",
                str(candidate_dir),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 2
    )
