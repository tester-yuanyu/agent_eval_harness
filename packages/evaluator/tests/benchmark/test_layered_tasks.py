from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path

import pytest
from eval_framework.benchmark.tasks import execution_task, load_tasks, validate_task

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / "data/benchmarks/file-tools-v2"


def task():
    value = load_tasks(ROOT / "data/benchmarks/file-tools-v1")[0]
    value.update(
        evaluation_level="chain",
        execution_mode="agent",
        checkpoints=[
            {
                "id": "state",
                "kind": "turn_files",
                "required": True,
                "turn": 1,
                "expected_files": {"result.txt": "private answer"},
            }
        ],
    )
    return value


def test_projection_removes_all_scoring_metadata():
    source = task()
    projected = execution_task(source)
    assert (
        not {
            "oracle",
            "reference",
            "checkpoints",
            "evaluation_level",
            "execution_mode",
            "family",
            "split",
        }
        & projected.keys()
    )
    assert "private answer" not in str(projected)
    source.update(
        evaluation_level="module",
        execution_mode="module",
        checkpoints=[],
        module_calls=[{"name": "read_file", "arguments": {"path": "input.txt"}}],
    )
    source["oracle"]["module_results"] = [
        {"call": 1, "error": False, "output_contains": []}
    ]
    projected = execution_task(source)
    assert projected["module_calls"] == source["module_calls"]
    projected["module_calls"][0]["arguments"]["path"] = "changed"
    assert source["module_calls"][0]["arguments"]["path"] == "input.txt"


@pytest.mark.parametrize(
    "change",
    [
        {"turn": 0},
        {"turn": True},
        {"turn": 2},
        {"turn": "1"},
        {"expected_files": {}},
        {"expected_files": {"../secret": "x"}},
        {"required": "yes"},
        {"unknown": 2},
        {"kind": "unsupported"},
    ],
)
def test_malformed_checkpoint_fails_closed(change):
    value = task()
    value["checkpoints"][0].update(change)
    with pytest.raises(ValueError):
        validate_task(value)


def test_duplicate_checkpoint_and_layer_mismatch_rejected():
    value = task()
    value["checkpoints"] *= 2
    with pytest.raises(ValueError, match="checkpoint"):
        validate_task(value)
    value = task()
    value["evaluation_level"] = "module"
    with pytest.raises(ValueError, match="module"):
        validate_task(value)


def test_v2_dataset_is_three_real_layers_and_family_disjoint():
    tasks = load_tasks(DATA)
    assert Counter(t["evaluation_level"] for t in tasks) == {
        "module": 60,
        "chain": 60,
        "e2e": 300,
    }
    assert Counter(t["split"] for t in tasks) == {"dev": 340, "holdout": 80}
    assert len({t["family"] for t in tasks}) == 104
    assert all(t["module_calls"] for t in tasks if t["evaluation_level"] == "module")
    assert all(t["checkpoints"] for t in tasks if t["evaluation_level"] == "chain")
    assert {p["kind"] for t in tasks for p in t["checkpoints"]} == {
        "turn_files",
        "tool_args",
        "tool_order",
    }
    for old in load_tasks(ROOT / "data/benchmarks/file-tools-v1"):
        new = next(t for t in tasks if t.get("source_task_id") == old["id"])
        assert new["fixtures"] == old["fixtures"]
        assert new["oracle"] == old["oracle"]
        if old["family"] != "read_search/markdown_heading":
            assert new["prompt"] == old["prompt"]
        else:
            assert "保留标题正文内部的空格" in new["prompt"]


def test_v2_generation_deterministic_and_immutable(tmp_path):
    spec = importlib.util.spec_from_file_location("build_v2", DATA / "build_dataset.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build_dataset(tmp_path / "dataset")
    assert (tmp_path / "dataset/tasks.jsonl").read_bytes() == (
        DATA / "tasks.jsonl"
    ).read_bytes()
    module.build_dataset(tmp_path / "dataset")
    target = tmp_path / "dataset/tasks.jsonl"
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="immutable"):
        module.build_dataset(tmp_path / "dataset")


def test_conflict_chain_detects_premature_resolution():
    cases = [t for t in load_tasks(DATA) if t["family"] == "chain/resolve_conflict"]
    for case in cases:
        before_answer = next(
            c for c in case["checkpoints"] if c["id"] == "conflict-no-change"
        )
        assert before_answer["expected_files"]["resolved.txt"] == "WAITING\n"
        assert case["oracle"]["expected_files"]["resolved.txt"] != "WAITING\n"
