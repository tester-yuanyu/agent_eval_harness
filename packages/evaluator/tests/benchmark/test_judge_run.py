"""Saved-evidence annotation must not rerun or rewrite the Agent experiment."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from eval_framework.benchmark.judge_calibration import create_calibration_worksheet
from eval_framework.benchmark.judge_run import judge_run
from eval_framework.benchmark.runner import digest, save_json
from eval_framework.benchmark.tasks import dataset_identity, load_tasks

DATASET = Path(__file__).resolve().parents[4] / "data/benchmarks/file-tools-v1"
CONFIG = {"model": "stub-judge", "api_key_env": "UNUSED_TEST_KEY"}


@pytest.fixture
def saved_run(tmp_path):
    task = load_tasks(DATASET)[0]
    identity = {
        "dataset": dataset_identity(DATASET),
        "runtime": {"agent": "nanobot"},
        "offline": False,
    }
    identity_hash = digest(identity)
    event = {
        "id": "turn-1",
        "type": "turn",
        "input": task["prompt"],
        "output": "Done",
        "snapshot": {},
        "start_time": "2026-11-01T00:00:00Z",
        "end_time": "2026-11-01T00:00:02Z",
    }
    row = {
        "identity_hash": identity_hash,
        "case_id": task["id"],
        "trial": 1,
        "category": task["category"],
        "split": task["split"],
        "family": task["family"],
        "execution_mode": "agent",
        "evaluation_level": "e2e",
        "latency_seconds": 2.0,
        "cleanup_status": "complete",
        "started_at": event["start_time"],
        "finished_at": event["end_time"],
        "observation": {
            "execution_kind": "real_agent",
            "events": [event],
            "turns": [{"input": task["prompt"], "output": "Done", "snapshot": {}}],
            "usage": {"input_tokens": 100, "output_tokens": 20, "cost_usd": 0.01},
        },
        "assessment": {
            "verdict": "FAIL",
            "validity": "VALID",
            "metrics": [{"name": "task_success", "formal": True, "score": 0}],
            "errors": [],
            "scoring_backend": "deepeval",
        },
    }
    source = {
        "run_id": "original",
        "identity": identity,
        "identity_hash": identity_hash,
        "mode": "real_agent",
        "planned_case_ids": [task["id"]],
        "trials_per_case": 1,
        "trials": [row],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }
    directory = tmp_path / "source"
    save_json(directory / "results.json", source)
    return directory, source


@pytest.fixture
def stub_judge(monkeypatch):
    calls = []

    def judge(task, observation, config):
        calls.append(deepcopy(observation))
        return [
            {
                "metric_id": "same-evidence-metric",
                "name": "response_groundedness",
                "version": "trajectory-geval-v1",
                "scope": "turn",
                "event_id": "turn-1",
                "evidence_ids": ["turn-1"],
                "status": "SCORED",
                "formal": False,
                "score": 0.2 if len(calls) == 1 else 0.8,
                "reason": "Recorded evidence",
                "events": [
                    {
                        "id": "judge-call",
                        "type": "generation",
                        "parent_id": "turn-1",
                        "model": "stub-judge",
                        "start_time": "2026-11-01T01:00:00Z",
                        "end_time": "2026-11-01T01:00:01Z",
                        "input": "EVIDENCE_PROMPT",
                        "output": "Judge result",
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 2,
                            "cost_usd": None,
                        },
                    }
                ],
            }
        ]

    monkeypatch.setattr("eval_framework.benchmark.judging.judge_observation", judge)
    return calls


def test_source_formal_verdict_and_agent_usage_are_preserved(
    saved_run, tmp_path, stub_judge
):
    source, original = saved_run
    raw = (source / "results.json").read_bytes()
    result = judge_run(source, DATASET, tmp_path / "graded", CONFIG)
    assert (source / "results.json").read_bytes() == raw
    row = result["trials"][0]
    assert row["assessment"]["verdict"] == "FAIL"
    assert (
        row["assessment"]["metrics"][0]
        == original["trials"][0]["assessment"]["metrics"][0]
    )
    assert row["source_assessment"] == original["trials"][0]["assessment"]
    assert row["execution_finished_at"] == original["finished_at"]
    assert (
        row["observation"]["events"][0]
        == original["trials"][0]["observation"]["events"][0]
    )
    assert row["observation"]["usage"] == original["trials"][0]["observation"]["usage"]
    assert result["judge_usage"]["input_tokens"] == 10
    assert result["judge_usage"]["cost_usd"] is None
    assert result["provenance"]["new_agent_executions"] == 0
    assert stub_judge == [original["trials"][0]["observation"]]


def test_unknown_worker_requests_remain_unknown_in_run_usage(
    saved_run, tmp_path, monkeypatch
):
    def judge(_task, _observation, _config):
        return [
            {
                "metric_id": "native-worker-failure",
                "name": "step_efficiency",
                "version": "trajectory-native-v1",
                "scope": "chain",
                "event_id": None,
                "evidence_ids": [],
                "status": "ERROR",
                "formal": False,
                "score": None,
                "reason": "Worker exited without a final audit record.",
                "events": [],
                "model_requests": None,
                "model_requests_known_subtotal": 0,
                "model_requests_unknown": True,
            }
        ]

    monkeypatch.setattr("eval_framework.benchmark.judging.judge_observation", judge)
    result = judge_run(saved_run[0], DATASET, tmp_path / "graded", CONFIG)

    assert result["judge_usage"]["model_requests"] is None
    assert result["judge_usage"]["model_requests_known_subtotal"] == 0
    assert result["judge_usage"]["model_requests_unknown"] is True
    assert result["judge_usage"]["input_tokens"] is None
    assert result["provenance"]["new_judge_model_requests"] is None
    assert result["provenance"]["new_judge_model_requests_known_subtotal"] == 0
    assert result["provenance"]["new_judge_model_requests_unknown"] is True


def test_repeats_have_distinct_export_events_stability_and_one_label_per_evidence(
    saved_run, tmp_path, stub_judge
):
    result = judge_run(saved_run[0], DATASET, tmp_path / "graded", CONFIG, repeats=2)
    calls = [
        event
        for event in result["trials"][0]["observation"]["events"]
        if event.get("is_judge")
    ]
    assert len({event["id"] for event in calls}) == 2
    recorded_ids = {event["id"] for event in calls}
    embedded = [
        event["id"]
        for metric in result["trials"][0]["assessment"]["metrics"]
        for event in metric.get("events", [])
    ]
    assert set(embedded) == recorded_ids
    assert result["judge_stability"]["matched_metrics"] == 1
    assert result["judge_stability"]["mean_range"] == pytest.approx(0.6)
    worksheet = create_calibration_worksheet(result)
    assert len(worksheet["rows"]) == 1
    assert worksheet["rows"][0]["human_score"] is None


def test_genuine_isolated_model_decision_can_receive_judge_scores(
    saved_run, tmp_path, stub_judge
):
    directory, source = saved_run
    source["mode"] = "real_model_decision"
    source["trials"][0]["execution_mode"] = "decision"
    source["trials"][0]["observation"]["execution_kind"] = "real_model_decision"
    save_json(directory / "results.json", source)
    result = judge_run(directory, DATASET, tmp_path / "decision-judge", CONFIG)
    assert result["judge_summary"]["scored"] == 1


def test_completed_and_journal_resume_do_not_make_more_calls(
    saved_run, tmp_path, stub_judge
):
    output = tmp_path / "graded"
    first = judge_run(saved_run[0], DATASET, output, CONFIG, repeats=2)
    assert len(stub_judge) == 2
    assert judge_run(saved_run[0], DATASET, output, CONFIG, repeats=2) == first
    assert len(stub_judge) == 2
    (output / "results.json").unlink()
    resumed = judge_run(saved_run[0], DATASET, output, CONFIG, repeats=2)
    assert len(stub_judge) == 2
    assert resumed["judge_summary"] == first["judge_summary"]


def test_changed_source_or_judge_config_cannot_resume(saved_run, tmp_path, stub_judge):
    source, original = saved_run
    output = tmp_path / "graded"
    judge_run(source, DATASET, output, CONFIG)
    with pytest.raises(ValueError, match="identity"):
        judge_run(source, DATASET, output, {**CONFIG, "model": "changed"})
    original["trials"][0]["observation"]["turns"][0]["output"] = "Changed evidence"
    save_json(source / "results.json", original)
    with pytest.raises(ValueError, match="identity"):
        judge_run(source, DATASET, output, CONFIG)
    assert len(stub_judge) == 1


@pytest.mark.parametrize(
    "mode", ["offline", "module_observation", "module_row", "reference_observation"]
)
def test_non_agent_source_is_rejected_without_judge_calls(
    saved_run, tmp_path, stub_judge, mode
):
    source, original = saved_run
    if mode == "offline":
        original["mode"] = "offline_reference_smoke"
    elif mode == "module_row":
        original["trials"][0]["execution_mode"] = "module"
    elif mode == "module_observation":
        original["trials"][0]["observation"]["execution_kind"] = "real_module"
    else:
        original["trials"][0]["observation"]["execution_kind"] = (
            "deterministic_reference_not_agent"
        )
    save_json(source / "results.json", original)
    with pytest.raises(ValueError):
        judge_run(source, DATASET, tmp_path / "graded", CONFIG)
    assert not stub_judge


def test_concurrent_owner_is_rejected_before_requests(saved_run, tmp_path, stub_judge):
    output = tmp_path / "graded"
    output.mkdir()
    (output / ".running").write_text("another process")
    with pytest.raises(ValueError, match="running"):
        judge_run(saved_run[0], DATASET, output, CONFIG)
    assert not stub_judge
    assert (output / ".running").read_text() == "another process"


def test_source_mutation_during_judging_cannot_publish_results(
    saved_run, tmp_path, monkeypatch
):
    source, original = saved_run

    def corrupt(*args):
        (source / "results.json").write_text(json.dumps({**original, "changed": True}))
        return []

    monkeypatch.setattr("eval_framework.benchmark.judging.judge_observation", corrupt)
    with pytest.raises(ValueError, match="changed"):
        judge_run(source, DATASET, tmp_path / "graded", CONFIG)
    assert not (tmp_path / "graded/results.json").exists()
    assert not (tmp_path / "graded/.running").exists()


def test_dataset_identity_mismatch_is_rejected_before_calls(
    saved_run, tmp_path, stub_judge
):
    source, original = saved_run
    original["identity"]["dataset"]["unexpected_revision"] = "changed"
    original["identity_hash"] = digest(original["identity"])
    original["trials"][0]["identity_hash"] = original["identity_hash"]
    save_json(source / "results.json", original)
    with pytest.raises(ValueError, match="dataset"):
        judge_run(source, DATASET, tmp_path / "graded", CONFIG)
    assert not stub_judge


def test_source_identity_corruption_is_rejected_before_calls(
    saved_run, tmp_path, stub_judge
):
    source, original = saved_run
    original["identity_hash"] = "corrupted"
    save_json(source / "results.json", original)
    with pytest.raises(ValueError, match="identity"):
        judge_run(source, DATASET, tmp_path / "graded", CONFIG)
    assert not stub_judge


def test_judge_output_cannot_be_nested_in_source(saved_run, stub_judge):
    with pytest.raises(ValueError, match="outside"):
        judge_run(saved_run[0], DATASET, saved_run[0] / "graded", CONFIG)
    assert not stub_judge
    assert not (saved_run[0] / "graded").exists()


def test_completed_result_identity_corruption_is_not_silently_reused(
    saved_run, tmp_path, stub_judge
):
    output = tmp_path / "graded"
    first = judge_run(saved_run[0], DATASET, output, CONFIG)
    first["identity_hash"] = "corrupted"
    save_json(output / "results.json", first)
    with pytest.raises(ValueError, match="identity"):
        judge_run(saved_run[0], DATASET, output, CONFIG)
    assert len(stub_judge) == 1
