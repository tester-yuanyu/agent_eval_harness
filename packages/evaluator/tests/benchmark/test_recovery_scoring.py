"""Regression checks for the published missing-primary recovery contract."""

import json
from copy import deepcopy
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path

import pytest

from eval_framework.benchmark.tasks import load_tasks

ROOT = Path(__file__).resolve().parents[4]
MODULE = "eval_framework.benchmark.recovery_scoring"


def score(task, observation):
    assert find_spec(MODULE) is not None, "Missing semantic recovery grader"
    return import_module(MODULE).score_recovery_policy(task, observation)


@pytest.fixture
def task():
    return next(
        item
        for item in load_tasks(ROOT / "data/benchmarks/file-tools-v2")
        if item["id"] == "file-tools-v2/chain/recover_missing/001"
    )


def tool(identifier, name, path, second, *, error=False, output="Success"):
    return {
        "id": identifier,
        "type": "tool",
        "name": name,
        "turn": 1,
        "parent_id": "turn-1",
        "execution_started": True,
        "input": {"path": "/isolated/workspace/" + path},
        "normalized_input": {"path": path},
        "output": output,
        "is_error": error,
        "tool_error": error,
        "error": output if error else None,
        "start_time": f"2026-11-01T00:00:{second:02d}.000000+00:00",
        "end_time": f"2026-11-01T00:00:{second:02d}.100000+00:00",
    }


@pytest.fixture
def observed():
    return {
        "status": "completed",
        "evidence_complete": True,
        "events": [
            {"id": "turn-1", "type": "turn", "turn": 1},
            tool(
                "primary",
                "read_file",
                "primary.txt",
                1,
                error=True,
                output="Error: File not found: /isolated/workspace/primary.txt",
            ),
            tool(
                "fallback", "read_file", "input.txt", 2, output="1| alpha-1\n2| beta-1"
            ),
            tool("write", "write_file", "recovered.txt", 3),
        ],
    }


def test_ordered_missing_error_and_successful_recovery_pass(task, observed):
    record = score(task, observed)[0]
    assert record["score"] == 1 and record["success"] is True
    assert record["formal"] is True and record["backend"] == "deepeval"
    assert record["scope"] == "chain" and record["event_id"] == "write"
    assert record["evidence_ids"] == ["primary", "fallback", "write"]
    assert record["version"] == import_module(MODULE).REVIEW_RECOVERY_VERSION


def test_primary_attempt_after_write_does_not_establish_recovery(task, observed):
    primary = observed["events"].pop(1)
    primary.update(start_time="2026-11-01T00:00:04Z", end_time="2026-11-01T00:00:05Z")
    observed["events"].append(primary)
    assert score(task, observed)[0]["score"] == 0


@pytest.mark.parametrize(
    "failure", ["primary_success", "not_missing", "fallback", "write"]
)
def test_each_required_result_must_have_the_right_semantics(task, observed, failure):
    if failure == "primary_success":
        observed["events"][1].update(
            is_error=False, tool_error=False, error=None, output="primary file contents"
        )
    elif failure == "not_missing":
        observed["events"][1].update(
            error="Permission denied", output="Error: Permission denied"
        )
    else:
        index = 2 if failure == "fallback" else 3
        observed["events"][index].update(
            is_error=True,
            tool_error=True,
            error="Permission denied",
            output="Error: Permission denied",
        )
    assert score(task, observed)[0]["score"] == 0


def test_fallback_cannot_begin_before_primary_error_is_observed(task, observed):
    observed["events"][1]["end_time"] = "2026-11-01T00:00:02.500000Z"
    assert score(task, observed)[0]["score"] == 0


def test_intervening_calls_and_failed_attempts_allow_later_recovery(task, observed):
    observed["events"].insert(2, tool("inspect", "list_dir", ".", 1))
    observed["events"].insert(
        3,
        tool(
            "failed-fallback",
            "read_file",
            "input.txt",
            1,
            error=True,
            output="Error: Temporary read failure",
        ),
    )
    observed["events"][-1]["name"] = "edit_file"
    assert score(task, observed)[0]["score"] == 1


@pytest.mark.parametrize(
    "problem", ["absent", "false", "unfinished", "output", "timestamps", "ids"]
)
def test_missing_evidence_never_yields_a_successful_recovery(task, observed, problem):
    if problem == "absent":
        observed.pop("evidence_complete")
    elif problem == "false":
        observed["evidence_complete"] = False
    elif problem == "unfinished":
        observed["events"][1]["incomplete"] = True
    elif problem == "output":
        observed["events"][1].pop("output")
    elif problem == "timestamps":
        observed["events"][1].pop("end_time")
    else:
        observed["events"][1]["id"] = "write"
    record = score(task, observed)[0]
    assert record["score"] is None and record["success"] is None
    assert record["status"] == "MISSING" and record["formal"] is True


def test_missing_whole_trace_has_no_dangling_event_link(task):
    record = score(task, {})[0]
    assert record["status"] == "MISSING" and record["score"] is None
    assert record["event_id"] is None and record["scope"] == "task"
    assert record["intended_scope"] == "chain"


@pytest.mark.parametrize("events", [None, []])
def test_completeness_claim_does_not_replace_absent_events(task, events):
    record = score(task, {"evidence_complete": True, "events": events})[0]
    assert record["score"] is None and record["status"] == "MISSING"


def test_selectors_are_derived_from_private_checkpoints(task, observed):
    for checkpoint in task["checkpoints"]:
        if checkpoint["id"] == "attempt-primary":
            checkpoint["arguments"]["path"] = "other-primary.txt"
    assert score(task, observed)[0]["score"] == 0
    observed["events"][1]["normalized_input"]["path"] = "other-primary.txt"
    assert score(task, observed)[0]["score"] == 1


def test_unrelated_family_and_new_dataset_do_not_inherit_domain_policy(task, observed):
    other = deepcopy(task)
    other["family"] = "chain/protect_source"
    assert score(other, observed) == []
    other = deepcopy(task)
    other["id"] = "file-tools-v3/chain/recover_missing/001"
    assert score(other, observed) == []


def test_missing_contract_selector_cannot_silently_pass(task, observed):
    task["checkpoints"] = [
        p for p in task["checkpoints"] if p["id"] != "attempt-primary"
    ]
    record = score(task, observed)[0]
    assert record["score"] is None and record["status"] == "MISSING"


def test_saved_live_pilot_and_primary_after_write_mutation(task):
    path = ROOT / "artifacts/benchmark-v2/chain-pilot/results.json"
    if not path.exists():
        pytest.skip("optional local saved pilot; no live execution")
    run = json.loads(path.read_text())
    observation = deepcopy(
        next(r["observation"] for r in run["trials"] if r["case_id"] == task["id"])
    )
    assert score(task, observation)[0]["score"] == 1
    primary = next(
        e
        for e in observation["events"]
        if e.get("type") == "tool"
        and e.get("normalized_input", {}).get("path") == "primary.txt"
    )
    observation["events"].remove(primary)
    observation["events"].append(primary)
    assert score(task, observation)[0]["score"] == 0
