"""Contract tests: execution isolation, immutable binding, malformed inputs."""

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / "data/benchmarks/nanobot-core-v1/tasks.jsonl"


def task():
    return {
        "id": "case",
        "contract_version": "nanobot-core-task-v1",
        "family": "memory_history_integrity",
        "split": "dev",
        "component": "memory",
        "description": "append then read",
        "fixtures": {},
        "settings": {},
        "operations": [
            {"id": "read", "operation": "memory.read", "input": {"since_cursor": 0}}
        ],
        "oracle": {
            "assertions": [
                {"event": "read", "path": ["output"], "kind": "equals", "value": []}
            ]
        },
    }


def test_contract_implementation_exists():
    assert importlib.util.find_spec("eval_framework.benchmark.core_tasks") is not None


def test_execution_projection_excludes_private_context_and_is_detached():
    from eval_framework.benchmark.core_tasks import core_execution_task

    source = task()
    result = core_execution_task(source)
    assert result == {"settings": {}, "operations": source["operations"]}
    result["operations"][0]["input"]["since_cursor"] = 9
    assert source["operations"][0]["input"]["since_cursor"] == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t["fixtures"].update({"../escape": "bad"}),
        lambda t: t["fixtures"].update({"/absolute": "bad"}),
        lambda t: t["fixtures"].update({"x/../escape": "bad"}),
        lambda t: t["operations"][0].update(operation="os.system"),
        lambda t: t["operations"][0]["input"].update(oracle="leak"),
        lambda t: t["operations"].append(copy.deepcopy(t["operations"][0])),
        lambda t: t["operations"][0]["input"].update(since_cursor=True),
        lambda t: t["settings"].update(config_path="/private/config"),
        lambda t: t["oracle"].update(assertions=[]),
        lambda t: t.update(split="test"),
    ],
)
def test_invalid_contract_is_rejected(mutate):
    from eval_framework.benchmark.core_tasks import core_execution_task

    source = task()
    mutate(source)
    with pytest.raises(ValueError):
        core_execution_task(source)


def test_frozen_dataset_has_disjoint_reserved_families_and_bound_bytes(tmp_path):
    from eval_framework.benchmark.core_tasks import (
        core_dataset_identity,
        load_core_tasks,
    )

    tasks = load_core_tasks(DATA)
    assert len(tasks) == 32
    dev = [t for t in tasks if t["split"] == "dev"]
    held = [t for t in tasks if t["split"] == "holdout"]
    assert len(dev) == 24 and len(held) == 8
    assert not {t["family"] for t in dev} & {t["family"] for t in held}
    assert {t["component"] for t in dev} == {"memory", "session", "context", "skills"}
    assert core_dataset_identity(DATA)["human_reviewed"] is False
    clone = tmp_path / "tasks.jsonl"
    clone.write_bytes(DATA.read_bytes() + b"\n")
    (tmp_path / "manifest.json").write_bytes(
        DATA.with_name("manifest.json").read_bytes()
    )
    with pytest.raises(ValueError, match="[Hh]ash|SHA|sha"):
        load_core_tasks(clone)


def test_builder_refuses_overwriting_changed_frozen_bytes(tmp_path):
    import runpy

    builder = runpy.run_path(str(DATA.with_name("build_dataset.py")))
    builder["build"](tmp_path)
    original = (tmp_path / "tasks.jsonl").read_bytes()
    (tmp_path / "tasks.jsonl").write_bytes(original + b"\n")
    with pytest.raises(ValueError, match="frozen|冻结"):
        builder["build"](tmp_path)
    assert (tmp_path / "tasks.jsonl").read_bytes() == original + b"\n"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t["oracle"]["assertions"][0].update(event=[]),
        lambda t: t["oracle"]["assertions"][0].update(
            path=[], kind="any_file_contains"
        ),
        lambda t: t["oracle"]["assertions"][0].update(kind=[]),
    ],
)
def test_malformed_private_assertions_fail_with_contract_error(mutate):
    from eval_framework.benchmark.core_tasks import core_execution_task

    source = task()
    mutate(source)
    with pytest.raises(ValueError):
        core_execution_task(source)


def test_dataset_directory_and_tasks_file_resolve_same_identity():
    from eval_framework.benchmark.core_tasks import (
        core_dataset_identity,
        load_core_tasks,
    )

    assert load_core_tasks(DATA.parent) == load_core_tasks(DATA)
    assert core_dataset_identity(DATA.parent) == core_dataset_identity(DATA)
