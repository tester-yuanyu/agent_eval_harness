import copy
from pathlib import Path

import pytest

from eval_framework.benchmark.tasks import (
    dataset_identity,
    execution_task,
    load_tasks,
    select_tasks,
    validate_task,
)

DATASET = Path(__file__).resolve().parents[4] / "data/benchmarks/file-tools-v1"


def test_frozen_dataset_has_300_distinct_executable_cases():
    tasks = load_tasks(DATASET)
    assert len(tasks) == 300
    assert len({task["id"] for task in tasks}) == 300
    assert sum(task["split"] == "dev" for task in tasks) == 240
    assert sum(task["split"] == "holdout" for task in tasks) == 60
    assert {task["family"] for task in tasks if task["split"] == "dev"}.isdisjoint(
        task["family"] for task in tasks if task["split"] == "holdout"
    )
    assert dataset_identity(DATASET)["case_count"] == 300


def test_pilot_is_deterministic_and_covers_every_category():
    tasks = load_tasks(DATASET)
    pilot = select_tasks(tasks, limit=20, split="dev")
    assert pilot == select_tasks(list(reversed(tasks)), limit=20, split="dev")
    assert len(pilot) == 20
    assert len({task["category"] for task in pilot}) == 5
    assert all(task["split"] == "dev" for task in pilot)


def test_execution_projection_excludes_answers_and_is_independent():
    task = load_tasks(DATASET)[0]
    projected = execution_task(task)
    assert set(projected) == {
        "id",
        "prompt",
        "followups",
        "fixtures",
        "allowed_tools",
        "max_steps",
    }
    projected["fixtures"].clear()
    assert task["fixtures"]


@pytest.mark.parametrize("path", ["../secret", "/tmp/secret", "a/../b", "./a", "a\\b"])
def test_unsafe_fixture_paths_are_rejected(path):
    task = copy.deepcopy(load_tasks(DATASET)[0])
    task["fixtures"][path] = "secret"
    with pytest.raises(ValueError, match="path"):
        validate_task(task)


def test_frozen_byte_tampering_is_rejected(tmp_path):
    for name in ("tasks.jsonl", "manifest.json"):
        (tmp_path / name).write_bytes((DATASET / name).read_bytes())
    with (tmp_path / "tasks.jsonl").open("ab") as handle:
        handle.write(b"\n")
    with pytest.raises(ValueError, match="SHA-256"):
        load_tasks(tmp_path)
