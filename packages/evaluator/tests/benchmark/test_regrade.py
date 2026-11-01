"""Changing a metric must not rerun the Agent or rewrite execution evidence."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from eval_framework.benchmark.metrics import METRICS_VERSION
from eval_framework.benchmark.oracle import reference_observation
from eval_framework.benchmark.regrade import regrade_run
from eval_framework.benchmark.runner import digest, save_json, scoring_identity
from eval_framework.benchmark.tasks import dataset_identity, load_tasks

DATASET = Path(__file__).resolve().parents[4] / "data/benchmarks/file-tools-v1"


@pytest.fixture
def saved_run(tmp_path):
    task = load_tasks(DATASET)[0]
    observation = reference_observation(task)
    observation["execution_kind"] = "real_agent"
    observation["evidence_complete"] = True
    observation["events"] = [
        {
            "type": "tool",
            "name": "read_file",
            "input": {"path": next(iter(task["fixtures"]))},
            "output": "observed fixture",
        }
    ]
    identity = {
        "dataset": dataset_identity(DATASET),
        "scoring_version": "old-v1",
        "harness_version": "harness-v1",
        "runtime": {"agent": "nanobot", "commit": "old-source"},
        "offline": False,
    }
    identity_hash = digest(identity)
    row = {
        "identity_hash": identity_hash,
        "case_id": task["id"],
        "trial": 1,
        "category": task["category"],
        "split": task["split"],
        "family": task["family"],
        "latency_seconds": 2.0,
        "cleanup_status": "complete",
        "started_at": "2026-11-01T00:00:00Z",
        "finished_at": "2026-11-01T00:00:02Z",
        "observation": observation,
        "assessment": {
            "verdict": "FAIL",
            "validity": "VALID",
            "metrics": [],
            "errors": [],
            "scoring_backend": "deepeval",
        },
    }
    result = {
        "run_id": "old-run",
        "identity": identity,
        "identity_hash": identity_hash,
        "config": {"model": "old-model"},
        "mode": "real_agent",
        "execution_backend": "inspect_ai",
        "scoring_backend": "deepeval",
        "planned_case_ids": [task["id"]],
        "trials_per_case": 1,
        "trials": [row],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }
    source = tmp_path / "source"
    save_json(source / "results.json", result)
    save_json(source / "run.json", {k: v for k, v in result.items() if k != "trials"})
    save_json(source / "trials/0001-t1.json", row)
    return source, result


def test_regrade_preserves_original_evidence_and_updates_grading_identity(
    saved_run, tmp_path
):
    source, previous = saved_run
    original = {
        path.relative_to(source): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }

    result = regrade_run(source, DATASET, tmp_path / "new-grading")

    assert result["run_id"] != previous["run_id"]
    assert result["identity"]["scoring_version"] == METRICS_VERSION
    assert result["identity"]["scoring_identity"] == scoring_identity()
    assert result["identity_hash"] == digest(result["identity"])
    assert result["execution_identity"] == previous["identity"]
    assert (
        result["regrade"]["source_results_sha256"]
        == hashlib.sha256(original[Path("results.json")]).hexdigest()
    )
    assert result["regrade"]["new_agent_executions"] == 0
    assert result["trials"][0]["observation"] == previous["trials"][0]["observation"]
    assert result["trials"][0]["assessment"]["verdict"] == "PASS"
    assert (
        result["trials"][0]["source_assessment"] == previous["trials"][0]["assessment"]
    )
    assert result["trials"][0]["started_at"] == previous["trials"][0]["started_at"]
    assert {
        path.relative_to(source): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    } == original
    assert json.loads((tmp_path / "new-grading/results.json").read_text()) == result
    assert (tmp_path / "new-grading/run.json").is_file()
    assert (tmp_path / "new-grading/trials/0001-t1.json").is_file()


def test_regrade_never_overwrites_existing_output(saved_run, tmp_path):
    source, _ = saved_run
    destination = tmp_path / "already-present"
    destination.mkdir()

    with pytest.raises(ValueError, match="already exists"):
        regrade_run(source, DATASET, destination)


def test_regrade_refuses_output_inside_original_run(saved_run):
    source, _ = saved_run

    with pytest.raises(ValueError, match="original"):
        regrade_run(source, DATASET, source / "regraded")


@pytest.mark.parametrize(
    "mutation", ["duplicate", "missing", "wrong_identity", "wrong_category"]
)
def test_invalid_source_journal_cannot_be_regraded(saved_run, tmp_path, mutation):
    source, previous = saved_run
    if mutation == "duplicate":
        previous["trials"].append(deepcopy(previous["trials"][0]))
    elif mutation == "missing":
        previous["trials"] = []
    elif mutation == "wrong_identity":
        previous["trials"][0]["identity_hash"] = "different"
    else:
        previous["trials"][0]["category"] = "different"
    save_json(source / "results.json", previous)

    with pytest.raises(ValueError):
        regrade_run(source, DATASET, tmp_path / "regraded")

    assert not (tmp_path / "regraded").exists()


def test_regrade_does_not_erase_cleanup_failure(saved_run, tmp_path):
    source, previous = saved_run
    previous["trials"][0]["cleanup_status"] = "failed"
    save_json(source / "results.json", previous)

    result = regrade_run(source, DATASET, tmp_path / "regraded")

    assert result["trials"][0]["assessment"]["verdict"] == "INVALID"
    assert result["trials"][0]["assessment"]["validity"] == "INVALID"


def test_regrade_refuses_mismatched_dataset(saved_run, tmp_path):
    source, previous = saved_run
    previous["identity"]["dataset"]["tasks_sha256"] = "wrong"
    previous["identity_hash"] = digest(previous["identity"])
    save_json(source / "results.json", previous)

    with pytest.raises(ValueError, match="dataset"):
        regrade_run(source, DATASET, tmp_path / "regraded")
