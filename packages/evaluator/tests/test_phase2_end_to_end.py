from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from eval_framework import (
    analyze_run,
    compare_runs,
    evaluate_gate,
    load_run_result,
    write_comparison,
    write_gate_result,
)
from eval_framework.gating import GatePolicy
from eval_framework.phase2_schemas import (
    JudgeDimensionResult,
    JudgeResult,
)
from eval_framework.reporting import write_report
from eval_framework.schemas import EvaluationRunResult
from eval_framework.stability import aggregate_stability
from eval_framework.trace_analysis import analyze_case_trace, write_run_analysis


def _run(case_result_factory, *, baseline: bool = False) -> EvaluationRunResult:
    cases = []
    for case_id in ("CASE-A", "CASE-B"):
        for number in range(1, 4):
            failed = case_id == "CASE-B" and number == 2 and not baseline
            case = case_result_factory(
                case_id=case_id,
                task_id="phase-two",
                trial_id=f"trial_{number:03d}",
                labels=["core"],
                quality_conclusion="FAIL" if failed else "PASS",
                score=0 if failed else 100,
                latency_ms=number * 10,
                module_output={"answer": "bad" if failed else "ok"},
                trace_events=[
                    {
                        "event_id": f"{case_id}-{number}",
                        "event_type": "intent_requested",
                    }
                ],
                judge_result=(
                    JudgeResult(
                        status="COMPLETED",
                        model="judge-v1",
                        prompt_version="judge-p1",
                        rubric_id="semantic-response",
                        rubric_version="1.0",
                        output_schema_version="output-v1",
                        dimensions=[
                            JudgeDimensionResult(
                                name="clarity",
                                score=85,
                                passed=True,
                                reason="clear",
                            )
                        ],
                        score=85,
                        passed=True,
                        token_usage={"input_tokens": 10, "output_tokens": 5},
                    )
                    if case_id == "CASE-A"
                    else None
                ),
            )
            case = case.model_copy(
                update={"trace_analysis": analyze_case_trace(case)}
            )
            cases.append(case)
    stability = aggregate_stability(cases, planned_trials=3)
    failures = sum(case.quality_conclusion == "FAIL" for case in cases)
    return EvaluationRunResult.model_validate(
        {
            "evaluator_run_id": "eval-baseline" if baseline else "eval-candidate",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "dataset_path": "dataset.jsonl",
            "dataset_version": "2.0",
            "dataset_hash": "dataset-hash",
            "dataset_total_cases": 2,
            "dataset_lifecycle_state": "FROZEN",
            "agent_version": "agent-v1" if baseline else "agent-v2",
            "provider_id": "mini_agent",
            "provider_version": "provider-v1",
            "capability_bundle_sha256": "capabilities-hash",
            "model_metadata": {"model": "offline-scripted"},
            "assertion_registry_version": "assertions-v1",
            "run_config": {
                "run_mode": "agent_benchmark",
                "execution_type": "full",
                "trials_per_case": 3,
            },
            "cases": cases,
            "summary": {
                "total_cases": 2,
                "total_trials": 6,
                "execution_status_counts": {"COMPLETED": 6},
                "quality_counts": {"PASS": 6 - failures, "FAIL": failures},
                "framework_completion_rate": 100,
                "agent_case_pass_rate": round((6 - failures) / 6 * 100, 2),
                "strict_assertion_pass_rate": round((6 - failures) / 6 * 100, 2),
                "core_behavior_match_rate": round((6 - failures) / 6 * 100, 2),
                "average_score": round((6 - failures) / 6 * 100, 2),
                "average_latency_ms": 20,
                "median_latency_ms": 20,
                "max_latency_ms": 30,
                "by_scope": {},
                "by_intent": {},
                "by_task_id": {},
                "failed_assertions": {},
            },
            "trials_per_case": 3,
            "total_duration_ms": 120,
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
            "stability": stability,
        }
    )


def test_phase_two_artifacts_are_reloadable_linked_and_immutable(
    tmp_path: Path, case_result_factory, capability_registry
):
    candidate = _run(case_result_factory)
    report_paths = write_report(candidate, tmp_path, capability_registry)
    run_dir = Path(report_paths.output_dir)
    report = Path(report_paths.report).read_text(encoding="utf-8")

    assert "确定性断言" in report
    assert "DeepSeek Judge" in report
    assert "Trace 观察" in report
    assert "pass@k" in report and "pass^k" in report
    assert "根因" not in report
    assert any("/judge/CASE-A/" in path for path in report_paths.evidence_files)
    assert any(
        "/trace_analysis/CASE-B/" in path
        for path in report_paths.evidence_files
    )
    for target in re.findall(r"\]\(([^)]+)\)", report):
        if "://" not in target:
            assert (run_dir / target).exists(), target

    results_path = Path(report_paths.results)
    original_hash = hashlib.sha256(results_path.read_bytes()).hexdigest()
    loaded_candidate = load_run_result(run_dir)
    analysis = analyze_run(
        loaded_candidate.result,
        source_results_sha256=loaded_candidate.sha256,
    )
    analysis_paths = write_run_analysis(analysis, run_dir)
    assert json.loads(Path(analysis_paths.analysis).read_text())["analysis_version"]

    baseline_path = tmp_path / "baseline-results.json"
    baseline_path.write_text(
        _run(case_result_factory, baseline=True).model_dump_json(indent=2),
        encoding="utf-8",
    )
    comparison = compare_runs(load_run_result(baseline_path), loaded_candidate)
    comparison_paths = write_comparison(comparison, tmp_path / "comparison")
    assert json.loads(Path(comparison_paths.json_path).read_text())["newly_failed"]

    gate = evaluate_gate(
        loaded_candidate,
        GatePolicy(
            policy_id="blocking",
            version="1.0",
            maximum_regressions=0,
            core_labels=[],
            zero_tolerance_labels=[],
            zero_tolerance_assertions=[],
        ),
        comparison,
    )
    gate_paths = write_gate_result(gate, tmp_path / "gate")
    assert json.loads(Path(gate_paths.json_path).read_text())["conclusion"] == "FAIL"
    assert hashlib.sha256(results_path.read_bytes()).hexdigest() == original_hash
