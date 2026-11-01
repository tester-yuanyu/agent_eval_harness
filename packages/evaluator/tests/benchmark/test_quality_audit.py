"""Offline diagnostics preserve execution evidence and comparison boundaries."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from eval_framework.benchmark.runner import digest
from eval_framework.benchmark.tasks import dataset_identity, load_tasks

DATASET = Path(__file__).resolve().parents[4] / "data/benchmarks/file-tools-v2"


def saved_run(tmp_path, name="source"):
    task = next(t for t in load_tasks(DATASET) if t["evaluation_level"] == "chain")
    identity = {
        "dataset": dataset_identity(DATASET),
        "scoring_version": "saved-version",
        "offline": False,
        "runtime": {"agent": "nanobot", "source": "fixed"},
    }
    tool = {
        "id": "tool-1",
        "type": "tool",
        "name": "read_file",
        "turn": 1,
        "input": {"path": "input.txt"},
        "normalized_input": {"path": "input.txt"},
        "execution_started": True,
        "is_error": False,
        "tool_error": False,
        "start_time": "2026-11-01T00:00:00Z",
        "end_time": "2026-11-01T00:00:01Z",
        "output": "PRIVATE_TOOL_OUTPUT",
        "before_files": {"input.txt": "PRIVATE_CONTENT"},
        "after_files": {"input.txt": "PRIVATE_CONTENT"},
    }
    second = {
        **deepcopy(tool),
        "id": "tool-2",
        "start_time": "2026-11-01T00:00:02Z",
        "end_time": "2026-11-01T00:00:03Z",
    }
    row = {
        "case_id": task["id"],
        "trial": 1,
        "family": task["family"],
        "category": task["category"],
        "split": task["split"],
        "identity_hash": digest(identity),
        "latency_seconds": 3.0,
        "observation": {
            "status": "completed",
            "evidence_complete": True,
            "execution_kind": "real_agent",
            "events": [tool, second],
        },
        "assessment": {"verdict": "PASS", "validity": "VALID", "metrics": []},
    }
    run = {
        "run_id": name,
        "identity": identity,
        "identity_hash": digest(identity),
        "mode": "real_agent",
        "planned_case_ids": [task["id"]],
        "trials_per_case": 1,
        "trials": [row],
        "config": {"instructions": "PRIVATE_PROMPT", "variant": name},
    }
    path = tmp_path / name
    path.mkdir()
    (path / "results.json").write_text(json.dumps(run))
    return path, run


def test_offline_audit_binds_sources_counts_candidates_and_leaves_verdicts(tmp_path):
    from eval_framework.benchmark.quality_audit import build_quality_audit

    path, _ = saved_run(tmp_path)
    before = (path / "results.json").read_bytes()
    output = tmp_path / "audit"
    result = build_quality_audit([path], DATASET, output)
    assert result["new_agent_executions"] == result["new_model_requests"] == 0
    assert result["runs"][0]["saved_verdicts"] == {"PASS": 1}
    assert result["repetition"]["scored"] == 2
    assert result["repetition"]["candidates"] == 1
    assert result["repetition"]["candidate_rate_scored"] == 0.5
    assert result["sources"][0]["sha256"] == hashlib.sha256(before).hexdigest()
    assert (path / "results.json").read_bytes() == before
    assert result["comparison"]["status"] == "not_supplied"
    for file in output.iterdir():
        assert "PRIVATE_" not in file.read_text()
        assert str(tmp_path) not in file.read_text()


def test_audit_missing_evidence_stays_in_applicable_denominator(tmp_path):
    from eval_framework.benchmark.quality_audit import build_quality_audit

    path, run = saved_run(tmp_path)
    del run["trials"][0]["observation"]["events"][1]["before_files"]
    (path / "results.json").write_text(json.dumps(run))
    result = build_quality_audit([path], DATASET, tmp_path / "audit")
    assert result["repetition"]["applicable"] == 2
    assert result["repetition"]["missing"] >= 1
    assert result["repetition"]["coverage"] < 1


def test_audit_rejects_duplicate_executions_and_existing_destination(tmp_path):
    from eval_framework.benchmark.quality_audit import build_quality_audit

    path, _ = saved_run(tmp_path)
    with pytest.raises(ValueError, match="duplicate"):
        build_quality_audit([path, path], DATASET, tmp_path / "bad")
    output = tmp_path / "exists"
    output.mkdir()
    with pytest.raises(ValueError, match="exists"):
        build_quality_audit([path], DATASET, output)


def test_comparison_reports_improvement_and_rejects_changed_controls(tmp_path):
    from eval_framework.benchmark.quality_audit import build_quality_audit

    source, _ = saved_run(tmp_path)
    baseline, left = saved_run(tmp_path, "baseline")
    candidate, right = saved_run(tmp_path, "candidate")
    left["trials"][0]["assessment"]["verdict"] = "FAIL"
    (baseline / "results.json").write_text(json.dumps(left))
    report = build_quality_audit(
        [source], DATASET, tmp_path / "audit", baseline=baseline, candidate=candidate
    )
    assert report["comparison"]["improvements"] == 1
    assert report["comparison"]["regressions"] == 0
    assert report["comparison"]["pass_rate_delta"] == 1.0
    right["config"]["temperature"] = 0.5
    (candidate / "results.json").write_text(json.dumps(right))
    with pytest.raises(ValueError, match="control"):
        build_quality_audit(
            [source], DATASET, tmp_path / "bad", baseline=baseline, candidate=candidate
        )
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("mutation", ["trial_identity", "reference", "config_binding"])
def test_comparison_rejects_unbound_or_reference_trials(tmp_path, mutation):
    from eval_framework.benchmark.quality_audit import build_quality_audit

    source, _ = saved_run(tmp_path)
    baseline, _ = saved_run(tmp_path, "baseline")
    candidate, right = saved_run(tmp_path, "candidate")
    if mutation == "trial_identity":
        right["trials"][0]["identity_hash"] = "foreign-run"
    elif mutation == "reference":
        right["trials"][0]["observation"]["execution_kind"] = (
            "deterministic_reference_not_agent"
        )
    else:
        right["identity"]["config"] = {"instructions": "other-config"}
        right["identity_hash"] = digest(right["identity"])
        right["trials"][0]["identity_hash"] = right["identity_hash"]
    (candidate / "results.json").write_text(json.dumps(right))
    with pytest.raises(ValueError):
        build_quality_audit(
            [source], DATASET, tmp_path / "bad", baseline=baseline, candidate=candidate
        )
    assert not (tmp_path / "bad").exists()
