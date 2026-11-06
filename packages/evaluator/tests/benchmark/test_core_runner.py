"""The Inspect core boundary never receives a private task or executes holdout."""

import json
import os
import py_compile
import subprocess
import sys

import pytest

from eval_framework.benchmark import core_runner


def test_boundary_startup_ignores_source_sitecustomize(tmp_path):
    source = tmp_path / "source"
    (source / "nanobot").mkdir(parents=True)
    (source / "nanobot" / "__init__.py").write_text("")
    (source / "sitecustomize.py").write_text(
        "raise RuntimeError('source hook executed')"
    )
    command = core_runner.core_command(
        {"nanobot_root": str(source), "python": sys.executable},
        ["-c", "import json,nanobot; print(json.dumps(nanobot.__file__))"],
    )
    result = subprocess.run(command, text=True, capture_output=True, check=True)
    assert "source hook executed" not in result.stderr
    assert json.loads(result.stdout) == str(source / "nanobot" / "__init__.py")


def test_boundary_does_not_read_stale_source_bytecode(tmp_path):
    source = tmp_path / "source"
    (source / "nanobot").mkdir(parents=True)
    module = source / "nanobot" / "__init__.py"
    module.write_text("VALUE='old'\n")
    original_time = module.stat().st_mtime
    py_compile.compile(str(module), doraise=True)
    module.write_text("VALUE='new'\n")
    os.utime(module, (original_time, original_time))
    command = core_runner.core_command(
        {"nanobot_root": str(source), "python": sys.executable},
        ["-c", "import nanobot; print(nanobot.VALUE)"],
    )
    result = subprocess.run(command, text=True, capture_output=True, check=True)
    assert result.stdout.strip() == "new"


def task(split="dev"):
    return {
        "id": "memory-001",
        "split": split,
        "component": "memory",
        "family": "memory_roundtrip",
        "description": "检查记忆保存",
        "fixtures": {},
        "settings": {},
        "operations": [{"id": "read", "operation": "memory.read_long", "input": {}}],
        "oracle": {"secret": "PRIVATE-EXPECTED-ANSWER"},
    }


@pytest.mark.parametrize(
    "config",
    [{}, {"nanobot_root": "/tmp", "python": "/usr/bin/python", "api_key": "secret"}],
)
def test_config_rejects_missing_or_extra_fields(config):
    with pytest.raises(ValueError):
        core_runner.validate_core_config(config)


def test_holdout_is_refused_before_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(core_runner, "load_core_tasks", lambda p: [task("holdout")])
    monkeypatch.setattr(core_runner, "core_dataset_identity", lambda p: {})
    with pytest.raises(ValueError, match="dev"):
        core_runner.run_core_benchmark(
            tmp_path,
            {"nanobot_root": "/tmp", "python": "/usr/bin/python"},
            tmp_path / "run",
        )
    assert not (tmp_path / "run").exists()


def test_inspect_repeats_public_payload_and_drift_failure(tmp_path, monkeypatch):
    private = task()
    snapshot = {
        "snapshot_hash": "snapshot",
        "source": {"working_tree_sha256": "source"},
        "environment": {"dependencies_sha256": "deps"},
        "profiles": {
            "core_modules": {
                "profile_hash": "profile",
                "adapter_sha256": "adapter",
                "scoring_sha256": "scorer",
            }
        },
    }
    monkeypatch.setattr(core_runner, "load_core_tasks", lambda p: [private])
    monkeypatch.setattr(
        core_runner, "core_dataset_identity", lambda p: {"sha256": "dataset"}
    )
    monkeypatch.setattr(core_runner, "snapshot_nanobot", lambda c: snapshot)
    monkeypatch.setattr(
        core_runner,
        "core_execution_task",
        lambda t: {k: t[k] for k in ("settings", "operations")},
    )
    seen = []

    async def execute(public, *, config, identity):
        seen.append(public)
        assert "PRIVATE" not in json.dumps(public)
        return {
            "status": "completed",
            "evidence_complete": True,
            "execution_kind": "real_core_module",
            "runtime_identity": identity,
            "events": [],
            "errors": [],
        }

    monkeypatch.setattr(core_runner, "execute_core_boundary", execute)
    monkeypatch.setattr(
        core_runner,
        "score_core_task",
        lambda t, o: {
            "validity": "VALID",
            "verdict": "PASS",
            "metrics": [{"formal": True, "success": True}],
        },
    )
    result = core_runner.run_core_benchmark(
        tmp_path,
        {"nanobot_root": "/tmp", "python": "/usr/bin/python"},
        tmp_path / "run",
        repeats=3,
        concurrency=2,
    )
    assert len(seen) == 3
    assert {row["trial"] for row in result["trials"]} == {1, 2, 3}
    assert result["summary"]["planned_trials"] == 3
    assert result["summary"]["all_repeats_passed_cases"] == 1
    assert result["summary"]["human_reviewed_cases"] == 0
    assert list((tmp_path / "run" / "inspect").glob("*.eval"))
    with pytest.raises(ValueError, match="exists"):
        core_runner.run_core_benchmark(
            tmp_path,
            {"nanobot_root": "/tmp", "python": "/usr/bin/python"},
            tmp_path / "run",
        )

    calls = 0

    def drift(c):
        nonlocal calls
        calls += 1
        return snapshot if calls == 1 else {**snapshot, "snapshot_hash": "changed"}

    monkeypatch.setattr(core_runner, "snapshot_nanobot", drift)
    with pytest.raises(RuntimeError, match="identity"):
        core_runner.run_core_benchmark(
            tmp_path,
            {"nanobot_root": "/tmp", "python": "/usr/bin/python"},
            tmp_path / "drift",
            repeats=1,
        )
    assert not (tmp_path / "drift" / "results.json").exists()
    assert list((tmp_path / "drift" / "inspect").glob("*.eval"))


def test_summary_keeps_invalid_trials_in_planned_denominator():
    rows = [
        {
            "case_id": "a",
            "assessment": {"verdict": "PASS", "validity": "VALID"},
            "latency_seconds": 1,
        },
        {
            "case_id": "a",
            "assessment": {"verdict": "INVALID", "validity": "INVALID"},
            "latency_seconds": 2,
        },
    ]
    summary = core_runner.summarize_core(rows, ["a"], 3)
    assert summary["pass_rate_planned"] == 1 / 3
    assert summary["pass_rate_valid"] == 1
    assert summary["missing_trials"] == 1
    assert summary["all_repeats_passed_cases"] == 0


def test_cli_core_validate_does_not_execute(tmp_path, monkeypatch, capsys):
    from eval_framework.benchmark import cli, core_tasks

    monkeypatch.setattr(
        core_tasks, "load_core_tasks", lambda p: [task(), task("holdout")]
    )
    monkeypatch.setattr(
        core_tasks, "core_dataset_identity", lambda p: {"sha256": "dataset"}
    )
    cli.main(["core-validate", "--dataset", str(tmp_path)])
    result = json.loads(capsys.readouterr().out)
    assert result["splits"] == {"dev": 1, "holdout": 1}
    assert result["executed"] is False


def test_native_timeout_retains_invalid_trial(tmp_path, monkeypatch):
    import anyio
    import inspect_ai

    snapshot = {
        "snapshot_hash": "snapshot",
        "source": {"working_tree_sha256": "source"},
        "environment": {"dependencies_sha256": "deps"},
        "profiles": {
            "core_modules": {
                "profile_hash": "profile",
                "adapter_sha256": "adapter",
                "scoring_sha256": "scorer",
            }
        },
    }
    monkeypatch.setattr(core_runner, "load_core_tasks", lambda p: [task()])
    monkeypatch.setattr(
        core_runner, "core_dataset_identity", lambda p: {"sha256": "dataset"}
    )
    monkeypatch.setattr(core_runner, "snapshot_nanobot", lambda c: snapshot)
    monkeypatch.setattr(
        core_runner,
        "core_execution_task",
        lambda t: {"settings": {}, "operations": t["operations"]},
    )
    original_task = inspect_ai.Task
    monkeypatch.setattr(
        inspect_ai,
        "Task",
        lambda **kwargs: original_task(**{**kwargs, "time_limit": 1}),
    )

    async def slow(public, **kwargs):
        await anyio.sleep(3)
        raise AssertionError("must be cancelled")

    monkeypatch.setattr(core_runner, "execute_core_boundary", slow)

    def score(t, observation):
        assert observation["status"] == "timeout"
        assert observation["evidence_complete"] is False
        assert any(error.get("code") == "time_limit" for error in observation["errors"])
        return {"validity": "INVALID", "verdict": "INVALID", "metrics": []}

    monkeypatch.setattr(core_runner, "score_core_task", score)
    result = core_runner.run_core_benchmark(
        tmp_path,
        {"nanobot_root": "/tmp", "python": "/usr/bin/python"},
        tmp_path / "timeout",
        repeats=1,
    )
    assert result["summary"]["verdict_counts"] == {"INVALID": 1}
    assert result["summary"]["planned_trials"] == 1
    assert result["summary"]["missing_trials"] == 0


def test_dataset_identity_drift_during_load_is_rejected(tmp_path, monkeypatch):
    values = iter([{"sha256": "old"}, {"sha256": "new"}])
    monkeypatch.setattr(core_runner, "core_dataset_identity", lambda p: next(values))
    monkeypatch.setattr(core_runner, "load_core_tasks", lambda p: [task()])
    with pytest.raises(RuntimeError, match="dataset identity changed"):
        core_runner.run_core_benchmark(
            tmp_path,
            {"nanobot_root": "/tmp", "python": sys.executable},
            tmp_path / "run",
        )
    assert not (tmp_path / "run").exists()


def test_rebound_dataset_during_first_snapshot_cannot_publish_results(
    tmp_path, monkeypatch
):
    import hashlib
    import shutil
    from pathlib import Path

    frozen = Path(__file__).resolve().parents[4] / "data/benchmarks/nanobot-core-v1"
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    for name in ("tasks.jsonl", "manifest.json"):
        shutil.copyfile(frozen / name, dataset / name)
    original_identity = core_runner.core_dataset_identity(dataset)
    snapshot = {
        "snapshot_hash": "snapshot",
        "source": {"working_tree_sha256": "source"},
        "environment": {"dependencies_sha256": "deps"},
        "profiles": {
            "core_modules": {
                "profile_hash": "profile",
                "adapter_sha256": "adapter",
                "scoring_sha256": "scorer",
            }
        },
    }
    snapshot_calls = 0
    boundary_calls = 0

    def mutate_on_first_snapshot(config):
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_calls == 1:
            task_path = dataset / "tasks.jsonl"
            tasks = [json.loads(line) for line in task_path.read_text().splitlines()]
            tasks[0]["description"] += "（仅在测试副本中变更）"
            task_path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in tasks)
            )
            manifest_path = dataset / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["sha256"] = hashlib.sha256(task_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest))
        return snapshot

    async def must_not_execute(public, **kwargs):
        nonlocal boundary_calls
        boundary_calls += 1
        raise AssertionError("dataset drift must be rejected before execution")

    monkeypatch.setattr(core_runner, "snapshot_nanobot", mutate_on_first_snapshot)
    monkeypatch.setattr(core_runner, "execute_core_boundary", must_not_execute)
    output = tmp_path / "run"
    with pytest.raises(RuntimeError, match="identity changed"):
        core_runner.run_core_benchmark(
            dataset,
            {"nanobot_root": "/tmp", "python": sys.executable},
            output,
            repeats=1,
        )
    assert snapshot_calls > 1
    assert boundary_calls == 0
    assert core_runner.core_dataset_identity(dataset) != original_identity
    assert not (output / "results.json").exists()
    assert list((output / "inspect").glob("*.eval"))
