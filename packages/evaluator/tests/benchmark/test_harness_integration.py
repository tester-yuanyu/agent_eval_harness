"""Exercise real Inspect/DeepEval boundaries without any Agent or network calls."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
from pathlib import Path

import pytest

from eval_framework.benchmark.runner import (
    RuntimeIdentityChanged,
    require_runtime_identity,
    run_benchmark,
)
from eval_framework.benchmark.tasks import (
    CONTRACT_VERSION,
    GRADER_VERSION,
    dataset_identity,
    load_tasks,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail closed on DNS/TCP while preserving asyncio's local socketpair."""
    monkeypatch.setenv("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    attempts = []
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    getaddrinfo = socket.getaddrinfo

    def checked_connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            attempts.append(address)
            raise AssertionError("network access is forbidden in harness tests")
        return connect(sock, address)

    def checked_connect_ex(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            attempts.append(address)
            raise AssertionError("network access is forbidden in harness tests")
        return connect_ex(sock, address)

    def checked_getaddrinfo(host, *args, **kwargs):
        if host not in (None, "localhost", "127.0.0.1", "::1"):
            attempts.append(host)
            raise AssertionError("external DNS is forbidden in harness tests")
        return getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", checked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", checked_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", checked_getaddrinfo)
    yield attempts
    assert not attempts, f"offline integration attempted network access: {attempts}"


@pytest.fixture
def frozen_dataset(tmp_path):
    root = tmp_path / "dataset"
    root.mkdir()
    common = {
        "category": "create_edit",
        "split": "dev",
        "followups": [],
        "allowed_tools": ["read_file", "write_file", "edit_file", "list_dir"],
        "required_tools": ["read_file", "write_file"],
        "max_steps": 4,
    }
    tasks = [
        {
            **common,
            "id": "integration/copy",
            "family": "copy",
            "prompt": "Copy source.txt verbatim to backup.txt; preserve other files.",
            "fixtures": {"source.txt": "alpha\n", "keep.txt": "untouched\n"},
            "oracle": {
                "expected_files": {"backup.txt": "alpha\n"},
                "preserve_other_files": True,
                "forbid_extra_files": True,
            },
            "reference": [{"op": "copy", "path": "source.txt", "dest": "backup.txt"}],
        },
        {
            **common,
            "id": "integration/replace",
            "family": "replace",
            "prompt": "Replace status=draft with status=final in status.txt.",
            "fixtures": {"status.txt": "status=draft\nrevision=2\n"},
            "oracle": {
                "expected_files": {"status.txt": "status=final\nrevision=2\n"},
                "preserve_other_files": True,
                "forbid_extra_files": True,
            },
            "reference": [
                {
                    "op": "replace",
                    "path": "status.txt",
                    "old": "status=draft",
                    "new": "status=final",
                }
            ],
        },
    ]
    path = root / "tasks.jsonl"
    path.write_text(
        "".join(json.dumps(task, sort_keys=True) + "\n" for task in tasks),
        encoding="utf-8",
    )
    manifest = {
        "dataset_id": "integration-two-tasks",
        "version": "1.0.0",
        "contract_version": CONTRACT_VERSION,
        "grader_version": GRADER_VERSION,
        "tasks_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "case_count": 2,
        "category_counts": {"create_edit": 2},
        "split_counts": {"dev": 2},
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _offline_run(path: Path, output: Path, **overrides):
    options = {
        "dataset": dataset_identity(path),
        "config": {},
        "output": output,
        "repeats": 1,
        "concurrency": 2,
        "offline": True,
    }
    options.update(overrides)
    return run_benchmark(load_tasks(path), **options)


def test_inspect_deepeval_offline_execution_and_completed_resume_are_immutable(
    frozen_dataset,
    tmp_path,
    monkeypatch,
):
    from inspect_ai.log import read_eval_log

    output = tmp_path / "run"
    result = _offline_run(frozen_dataset, output)
    assert result["mode"] == "offline_reference_smoke"
    assert result["execution_backend"] == "inspect_ai"
    assert result["scoring_backend"] == "deepeval"
    assert result["identity"]["offline"] is True
    assert result["identity"]["runtime"] == {"mode": "reference_smoke_only"}
    assert result["summary"]["completed_trials"] == 2
    assert result["summary"]["verdicts"] == {"PASS": 2}
    for row in result["trials"]:
        observation, assessment = row["observation"], row["assessment"]
        assert observation["execution_kind"] == "deterministic_reference_not_agent"
        assert observation["events"] == []
        assert observation["usage"] == {}
        assert row["cleanup_status"] == "inspect_managed"
        assert assessment["scoring_backend"] == "deepeval"
        assert any(metric["formal"] for metric in assessment["metrics"])
        assert all(metric["backend"] == "deepeval" for metric in assessment["metrics"])
        assert all(
            metric["success"] for metric in assessment["metrics"] if metric["formal"]
        )
    logs = list((output / "inspect").glob("*.eval"))
    assert len(logs) == 1, "Inspect must have written its genuine evaluation log"
    log = read_eval_log(logs[0])
    assert log.status == "success"
    assert len(log.samples) == 2
    assert all(sample.target == "" for sample in log.samples)
    for sample in log.samples:
        assert sample.scores
        for score in sample.scores.values():
            stored = json.loads(score.explanation)
            assert stored["scoring_backend"] == "deepeval"
            assert stored["verdict"] == "PASS"

    before = {
        path.relative_to(output): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in output.rglob("*")
        if path.is_file()
    }

    def must_not_execute(*args, **kwargs):
        raise AssertionError("completed immutable run must not schedule execution")

    monkeypatch.setattr("inspect_ai.eval_set", must_not_execute)
    again = _offline_run(frozen_dataset, output)
    assert again == result
    after = {
        path.relative_to(output): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in output.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (output / ".running").exists()


@pytest.mark.parametrize("changed", [{"config": {"max_steps": 5}}, {"repeats": 2}])
def test_resume_rejects_config_or_repeat_changes_without_overwriting_results(
    frozen_dataset,
    tmp_path,
    changed,
):
    output = tmp_path / "run"
    _offline_run(frozen_dataset, output)
    before = (output / "results.json").read_bytes()
    with pytest.raises(ValueError, match="resume identity changed"):
        _offline_run(frozen_dataset, output, **changed)
    assert (output / "results.json").read_bytes() == before
    assert not (output / ".running").exists()


def test_runtime_source_change_has_a_dedicated_exception():
    original = {"source_commit": "commit-a", "working_tree_sha256": "tree-a"}
    require_runtime_identity(original, dict(original))
    with pytest.raises(RuntimeIdentityChanged, match="source/configuration changed"):
        require_runtime_identity(
            original, {**original, "working_tree_sha256": "tree-b"}
        )


def test_root_cli_preserves_env_file_after_benchmark_command(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[4]
    monkeypatch.syspath_prepend(str(repo / "src"))
    from agent_eval_suite.cli import main

    capture = tmp_path / "forwarded.json"
    interpreter = tmp_path / "fake-python"
    interpreter.write_text(
        f"#!{sys.executable}\nimport json,sys\n"
        f"with open({str(capture)!r},'w') as f: json.dump(sys.argv[1:],f)\n",
        encoding="utf-8",
    )
    interpreter.chmod(0o700)
    env_file = tmp_path / "offline.env"
    env_file.write_text("BENCHMARK_INTEGRATION_ENV_FILE=loaded\n", encoding="utf-8")
    forwarded = [
        "demo",
        "--env-file",
        str(env_file),
        "--output",
        str(tmp_path / "demo"),
        "--limit",
        "2",
    ]
    assert (
        main(
            [
                "--root",
                str(repo),
                "--evaluator-python",
                str(interpreter),
                "benchmark",
                *forwarded,
            ]
        )
        == 0
    )
    assert json.loads(capture.read_text()) == [
        "-m",
        "eval_framework.benchmark.cli",
        *forwarded,
    ]


def test_downstream_cli_accepts_and_loads_post_command_env_file(
    frozen_dataset,
    tmp_path,
    monkeypatch,
    capsys,
):
    from eval_framework.benchmark.cli import main

    monkeypatch.setenv("BENCHMARK_INTEGRATION_ENV_FILE", "temporary-test-state")
    monkeypatch.delenv("BENCHMARK_INTEGRATION_ENV_FILE")
    env_file = tmp_path / "offline.env"
    env_file.write_text("BENCHMARK_INTEGRATION_ENV_FILE=loaded\n", encoding="utf-8")
    assert (
        main(
            [
                "validate",
                "--dataset",
                str(frozen_dataset),
                "--env-file",
                str(env_file),
            ]
        )
        == 0
    )
    assert os.environ["BENCHMARK_INTEGRATION_ENV_FILE"] == "loaded"
    output = json.loads(capsys.readouterr().out)
    assert output["tasks"] == 2
    assert output["reference_failures"] == []
