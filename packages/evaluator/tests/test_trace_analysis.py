from __future__ import annotations

import hashlib
from pathlib import Path

from eval_framework.cli import main
from eval_framework.phase2_schemas import TraceIssue
from eval_framework.schemas import AssertionResult, EvaluationRunResult
from eval_framework.trace_analysis import (
    analyze_case_trace,
    analyze_run,
    write_run_analysis,
)


def test_two_turn_trace_keeps_turn_and_run_identity(case_result_factory):
    case = case_result_factory(
        test_scope="end_to_end",
        agent_run_ids=["run-confirm", "run-write"],
        turn_results=[
            {
                "run_id": "run-confirm",
                "events": [{"event_id": "e1", "event_type": "run_started"}],
            },
            {
                "run_id": "run-write",
                "events": [{"event_id": "e2", "event_type": "run_completed"}],
            },
        ],
        trace_events=[
            {"event_id": "e1", "event_type": "run_started"},
            {"event_id": "e2", "event_type": "run_completed"},
        ],
    )

    analysis = analyze_case_trace(case)

    assert [(event.turn_index, event.agent_run_id) for event in analysis.timeline] == [
        (0, "run-confirm"),
        (1, "run-write"),
    ]
    assert analysis.timeline[0].payload == {
        "event_id": "e1",
        "event_type": "run_started",
    }


def test_module_trace_without_agent_run_id_is_retained(case_result_factory):
    case = case_result_factory(
        trace_events=[{"event_id": "intent-1", "event_type": "intent_requested"}]
    )

    event = analyze_case_trace(case).timeline[0]

    assert event.turn_index == 0
    assert event.agent_run_id is None
    assert event.evidence_ref == "event:intent-1"


def test_structural_anomalies_are_observations_not_root_causes(case_result_factory):
    case = case_result_factory(
        test_scope="end_to_end",
        agent_run_ids=["run-known"],
        turn_results=[
            {
                "run_id": "run-other",
                "events": [
                    {
                        "event_id": "duplicate",
                        "event_type": "tool_started",
                        "timestamp": "2026-01-02T00:00:00Z",
                    },
                    {
                        "event_id": "duplicate",
                        "event_type": "unrelated",
                        "timestamp": "2026-01-01T00:00:00Z",
                    },
                ],
            }
        ],
    )

    analysis = analyze_case_trace(case)
    codes = {issue.code for issue in analysis.issues}

    assert {
        "OBSERVED_DUPLICATE_EVENT_ID",
        "OBSERVED_TIMESTAMP_REVERSAL",
        "OBSERVED_RUN_ASSOCIATION_MISMATCH",
        "OBSERVED_UNCLOSED_LIFECYCLE",
    } <= codes
    assert all("root cause" not in issue.message.lower() for issue in analysis.issues)


def test_invalid_assertion_evidence_ref_is_reported(case_result_factory):
    case = case_result_factory(
        trace_events=[{"event_id": "found", "event_type": "confirmation_requested"}],
        assertion_results=[
            AssertionResult(
                name="confirmation_requested",
                weight=1,
                critical=True,
                passed=True,
                evidence_refs=["event:found", "event:missing"],
            )
        ],
    )

    issues = analyze_case_trace(case).issues

    assert [issue.code for issue in issues].count("EVIDENCE_REF_UNRESOLVED") == 1
    assert issues[-1].evidence_refs == ["event:missing"]


def test_provider_trace_rules_are_appended(case_result_factory):
    class Rule:
        def analyze(self, timeline, case):
            assert timeline
            assert case.case_id == "MODULE-1"
            return [
                TraceIssue(
                    code="SUGGESTED_PROVIDER_CHECK",
                    message="Inspect provider-specific sequencing.",
                )
            ]

    case = case_result_factory(
        trace_events=[{"event_id": "e1", "event_type": "intent_requested"}]
    )

    analysis = analyze_case_trace(case, rules=[Rule()])

    assert "SUGGESTED_PROVIDER_CHECK" in {issue.code for issue in analysis.issues}


def test_write_run_analysis_does_not_modify_results(
    tmp_path: Path, case_result_factory
):
    case = case_result_factory(
        trace_events=[{"event_id": "e1", "event_type": "intent_requested"}]
    )
    result = EvaluationRunResult.model_validate(
        {
            "evaluator_run_id": "eval-run",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "dataset_path": "dataset.jsonl",
            "dataset_version": "1.0",
            "dataset_hash": "dataset-hash",
            "agent_version": "agent-v1",
            "model_metadata": {},
            "assertion_registry_version": "v1",
            "run_config": {"run_mode": "framework_self_test"},
            "cases": [case],
            "summary": {
                "total_cases": 1,
                "total_trials": 1,
                "execution_status_counts": {"COMPLETED": 1},
                "quality_counts": {"PASS": 1},
                "framework_completion_rate": 100,
                "agent_case_pass_rate": 100,
                "average_score": 100,
                "average_latency_ms": 1,
                "median_latency_ms": 1,
                "max_latency_ms": 1,
                "by_scope": {},
                "by_intent": {},
                "by_task_id": {},
                "failed_assertions": {},
            },
            "total_duration_ms": 1,
        }
    )
    results_path = tmp_path / "results.json"
    results_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    before = hashlib.sha256(results_path.read_bytes()).hexdigest()

    analysis = analyze_run(result, source_results_sha256=before)
    paths = write_run_analysis(analysis, tmp_path)

    assert hashlib.sha256(results_path.read_bytes()).hexdigest() == before
    assert Path(paths.analysis).is_file()
    assert len(paths.trace_files) == 1
    assert Path(paths.trace_files[0]).is_file()

    assert main(["analyze", "--run-dir", str(tmp_path)]) == 0
    assert hashlib.sha256(results_path.read_bytes()).hexdigest() == before
