from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from eval_framework.benchmark.module_oracle import evaluate_module_calls
from eval_framework.benchmark.tasks import load_tasks

ROOT = Path(__file__).resolve().parents[4]


def module_task(family):
    return next(
        t
        for t in load_tasks(ROOT / "data/benchmarks/file-tools-v2")
        if t["family"] == f"module/{family}" and t["id"].endswith("/001")
    )


def observation(task, output):
    call = task["module_calls"][0]
    return {
        "events": [
            {
                "type": "tool",
                "name": call["name"],
                "input": copy.deepcopy(call["arguments"]),
                "output": output,
                "is_error": False,
            }
        ]
    }


def test_actual_slice_output_passes():
    task = module_task("read_slice")
    output = "2| beta-1\n\n(Showing lines 2-2 of 3. Use offset=3 to continue.)"
    checks = evaluate_module_calls(task, observation(task, output))
    assert checks and all(c["passed"] for c in checks), checks


@pytest.mark.parametrize(
    "output",
    [
        "1| alpha-1\n2| beta-1\n3| gamma-1\n\n(End of file — 3 lines total)",
        "alpha-1\nbeta-1\ngamma-1\n",
        "1| beta-1\n\n(Showing lines 1-1 of 3. Use offset=2 to continue.)",
        "2| beta-1\n3| gamma-1\n\n(End of file — 3 lines total)",
        "2| beta-1\n\n(Showing lines 2-2 of 4. Use offset=3 to continue.)",
        "2| beta-1\n\n(Showing lines 2-2 of 3. Use offset=2 to continue.)",
        "2| beta-1\n\n(End of file — 3 lines total)",
        "2| beta-1\n2| beta-1\n\n(Showing lines 2-2 of 3. Use offset=3 to continue.)",
        "2| beta-1\n\n(Showing lines 2-2 of 3. Use offset=3 to continue.)\nalpha-1",
    ],
)
def test_slice_rejects_whole_input_wrong_indices_counts_and_extra_output(output):
    task = module_task("read_slice")
    checks = evaluate_module_calls(task, observation(task, output))
    assert not all(c["passed"] for c in checks), checks


def test_full_read_requires_all_content_not_just_first_and_last_tokens():
    task = module_task("read_text")
    output = "1| alpha-1\n2| wrong\n3| gamma-1\n\n(End of file — 3 lines total)"
    assert not all(
        c["passed"] for c in evaluate_module_calls(task, observation(task, output))
    )


def test_list_requires_exact_fixture_entries_and_no_duplicate_or_fabricated_paths():
    task = module_task("list_nested")
    good = "section-1/\nsection-1/note.txt"
    assert all(
        c["passed"] for c in evaluate_module_calls(task, observation(task, good))
    )
    for bad in (
        "section-1/note.txt",
        good + "\nsecret.txt",
        good + "\nsection-1/note.txt",
    ):
        assert not all(
            c["passed"] for c in evaluate_module_calls(task, observation(task, bad))
        )


def test_public_invocation_must_match_and_missing_events_never_pass():
    task = module_task("read_slice")
    output = "2| beta-1\n\n(Showing lines 2-2 of 3. Use offset=3 to continue.)"
    value = observation(task, output)
    value["events"][0]["input"]["offset"] = 1
    assert not all(c["passed"] for c in evaluate_module_calls(task, value))
    assert not all(c["passed"] for c in evaluate_module_calls(task, {"events": []}))
    assert evaluate_module_calls({"execution_mode": "agent"}, {"events": []}) == []


def test_saved_real_module_outputs_pass_without_rerunning_modules():
    path = ROOT / "artifacts/benchmark-v2/modules60/results.json"
    if not path.exists():
        pytest.skip("optional saved real module evidence")
    tasks = {t["id"]: t for t in load_tasks(ROOT / "data/benchmarks/file-tools-v2")}
    run = json.loads(path.read_text())
    for trial in run["trials"]:
        checks = evaluate_module_calls(tasks[trial["case_id"]], trial["observation"])
        assert checks and all(c["passed"] for c in checks), (trial["case_id"], checks)
