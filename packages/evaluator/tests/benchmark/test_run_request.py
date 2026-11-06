"""Configuration composition must preserve execution choices without secrets."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from eval_framework.benchmark.cli import main

ROOT = Path(__file__).resolve().parents[4]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def document(**sections):
    return {
        "schema_version": "1.0",
        "model": {},
        "harness": {},
        "environment": {},
        "benchmark": {},
        "execution": {},
        **sections,
    }


def test_old_config_and_composed_config_preserve_every_runtime_option(tmp_path):
    from eval_framework.orchestration import load_run_request

    old = json.loads((ROOT / "configs/benchmark/nanobot.example.json").read_text())
    old.update(
        inspect_model="openai/deepseek-chat",
        module_timeout_seconds=15,
        tokenizer_cache_dir="/opt/tokenizer-cache",
        provider="nanobot",
    )
    legacy = load_run_request(write_json(tmp_path / "old.json", old))
    assert legacy.runtime_config() == old
    composed = write_json(tmp_path / "new.json", legacy.model_dump(exclude_unset=True))
    assert load_run_request(composed).runtime_config() == old


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("environment", [{}, {"sandbox": "docker"}])
def test_default_serialization_roundtrip_preserves_omitted_runtime_options(
    json_mode, environment,
):
    from eval_framework.orchestration import RunRequest

    source = document(
        model={"temperature": 0, "base_url": None},
        harness={"max_steps": 12}, environment=environment,
        benchmark={"level": "module"}, execution={"concurrency": 4},
    )
    request = RunRequest.model_validate(source)
    if json_mode:
        serialized = request.model_dump_json()
        assert json.loads(serialized) == source
        restored = RunRequest.model_validate_json(serialized)
    else:
        serialized = request.model_dump()
        assert serialized == source
        restored = RunRequest.model_validate(serialized)
    assert restored.runtime_config() == {
        "temperature": 0, "base_url": None, "max_steps": 12, **environment,
    }
    assert restored.model_dump(exclude_unset=True) == source


@pytest.mark.parametrize("json_mode", [False, True])
def test_nested_run_request_serialization_preserves_omission(json_mode):
    from eval_framework.orchestration import RunRequest

    class Envelope(BaseModel):
        requests: list[RunRequest]

    source = {"requests": [document(), document(environment={"sandbox": "docker"})]}
    envelope = Envelope.model_validate(source)
    if json_mode:
        serialized = envelope.model_dump_json()
        assert json.loads(serialized) == source
        restored = Envelope.model_validate_json(serialized)
    else:
        serialized = envelope.model_dump()
        assert serialized == source
        restored = Envelope.model_validate(serialized)
    assert [request.runtime_config() for request in restored.requests] == [
        {}, {"sandbox": "docker"},
    ]


def test_referenced_specs_resolve_paths_against_each_containing_file(tmp_path):
    from eval_framework.orchestration import load_run_request

    write_json(tmp_path / "specs/environment.json", {
        "nanobot_root": "../agent", "python": "../agent/.venv/bin/python",
        "tokenizer_cache_dir": "../cache",
    })
    write_json(tmp_path / "specs/benchmark.json", {"dataset": "../tasks.jsonl"})
    config = write_json(tmp_path / "run.json", document(
        environment="specs/environment.json", benchmark="specs/benchmark.json",
    ))
    request = load_run_request(config)
    assert request.runtime_config() == {
        "nanobot_root": str(tmp_path / "agent"),
        "python": str(tmp_path / "agent/.venv/bin/python"),
        "tokenizer_cache_dir": str(tmp_path / "cache"),
    }
    assert request.benchmark.dataset == str(tmp_path / "tasks.jsonl")


def test_legacy_relative_paths_keep_cwd_semantics(tmp_path):
    from eval_framework.orchestration import load_run_request

    path = write_json(tmp_path / "legacy.json", {
        "nanobot_root": "./agent", "python": "./agent/.venv/bin/python",
    })
    assert load_run_request(path).runtime_config() == {
        "nanobot_root": "./agent", "python": "./agent/.venv/bin/python",
    }


@pytest.mark.parametrize("value", [
    document(model={"typo": 1}),
    document(harness={"max_steps": True}),
    document(harness={"max_steps": 31}),
    document(execution={"repeats": 0}),
    document(execution={"concurrency": "2"}),
    document(benchmark={"limit": 0}),
    document(environment={"sandbox": "remote"}),
    document(model={"api_key_env": "literal key with spaces"}),
    document(model={"model": "a"}, harness={"model": "b"}),
    document(environment="https://example.test/spec.json"),
    {"model": "a", "misspelled_option": 1},
])
def test_invalid_unknown_and_misplaced_fields_fail_closed(tmp_path, value):
    from eval_framework.orchestration import load_run_request

    with pytest.raises(ValueError):
        load_run_request(write_json(tmp_path / "bad.json", value))


@pytest.mark.parametrize("payload", [
    {"api_key": "DO_NOT_ECHO_THIS"},
    {"extra_body": {"nested": [{"Authorization": "DO_NOT_ECHO_THIS"}]}},
    {"extra_body": {"apiKey": "DO_NOT_ECHO_THIS"}},
    {"extra_body": {"token": "DO_NOT_ECHO_THIS"}},
    {"extra_body": {"refresh_token": "DO_NOT_ECHO_THIS"}},
    {"extra_body": {"headers": {"Cookie": "DO_NOT_ECHO_THIS"}}},
    {"base_url": "https://user:DO_NOT_ECHO_THIS@example.test/v1"},
    {"base_url": "https://example.test/v1?api_key=DO_NOT_ECHO_THIS"},
])
def test_secret_values_are_rejected_recursively_without_echo(tmp_path, payload):
    from eval_framework.orchestration import load_run_request

    for value in (payload, document(model=payload)):
        with pytest.raises(ValueError) as exc:
            load_run_request(write_json(tmp_path / "secret.json", value))
        assert "DO_NOT_ECHO_THIS" not in str(exc.value)


@pytest.mark.parametrize("raw", [
    '{"model":"a", "model":"b"}',
    '{"extra_body":{"thinking":{"type":"enabled","type":"disabled"}}}',
])
def test_duplicate_json_keys_are_errors(tmp_path, raw):
    from eval_framework.orchestration import load_run_request

    path = tmp_path / "duplicate.json"
    path.write_text(raw)
    with pytest.raises(ValueError, match="duplicate"):
        load_run_request(path)


@pytest.mark.parametrize("value", [
    {"nanobot_root": "https://example.test/agent"},
    {"python": " "},
])
def test_legacy_runtime_paths_must_also_be_local(tmp_path, value):
    from eval_framework.orchestration import load_run_request

    with pytest.raises(ValueError):
        load_run_request(write_json(tmp_path / "bad-path.json", value))


def test_referenced_interpreter_symlink_keeps_virtual_environment_path(tmp_path):
    from eval_framework.orchestration import load_run_request

    interpreter = tmp_path / "venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(sys.executable)
    path = write_json(tmp_path / "run.json", document(
        environment={"python": "venv/bin/python"},
    ))
    assert load_run_request(path).runtime_config()["python"] == str(interpreter)


def test_invalid_migration_does_not_create_output(tmp_path):
    from eval_framework.orchestration import migrate_legacy_config

    path = write_json(tmp_path / "invalid.json", {"unsupported_option": 1})
    output = tmp_path / "output"
    with pytest.raises(ValueError):
        migrate_legacy_config(path, output)
    assert not output.exists()


def test_migration_cli_preserves_relative_targets_and_refuses_overwrite(tmp_path):
    from eval_framework.orchestration import load_run_request

    old = write_json(tmp_path / "input/old.json", {
        "nanobot_root": "agent", "python": "agent/.venv/bin/python",
        "extra_body": {"thinking": {"type": "disabled"}},
        "max_steps": 7, "module_timeout_seconds": 11,
    })
    output = tmp_path / "output"
    command = [sys.executable, str(ROOT / "scripts/migrate_benchmark_config.py"),
               "--input", str(old), "--output", str(output)]
    first = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    request = load_run_request(output / "run.json")
    assert request.runtime_config() == {
        "nanobot_root": str(tmp_path / "agent"),
        "python": str(tmp_path / "agent/.venv/bin/python"),
        "extra_body": {"thinking": {"type": "disabled"}},
        "max_steps": 7, "module_timeout_seconds": 11,
    }
    assert sorted(p.name for p in output.glob("*.json")) == [
        "benchmark.json", "environment.json", "execution.json", "harness.json",
        "model.json", "run.json",
    ]
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    second = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert second.returncode != 0
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}


def test_composed_config_controls_real_offline_cli_selection_and_trials(tmp_path):
    config = write_json(tmp_path / "run.json", document(
        harness={"max_steps": 7},
        benchmark={"dataset": str(ROOT / "data/benchmarks/file-tools-v2"),
                   "level": "chain", "split": "dev", "limit": 1},
        execution={"repeats": 2, "concurrency": 1},
    ))
    output = tmp_path / "run"
    assert main(["demo", "--config", str(config), "--output", str(output)]) == 0
    result = json.loads((output / "results.json").read_text())
    assert result["summary"]["planned_trials"] == 2
    assert result["summary"]["completed_trials"] == 2
    assert result["identity"]["config"] == {"max_steps": 7}
    assert {t["evaluation_level"] for t in result["trials"]} == {"chain"}


def test_explicit_cli_flags_override_composed_configuration(tmp_path):
    config = write_json(tmp_path / "run.json", document(
        benchmark={"dataset": "missing.jsonl", "level": "module",
                   "split": "holdout", "limit": 2},
        execution={"repeats": 3, "concurrency": 1},
    ))
    output = tmp_path / "run"
    assert main([
        "demo", "--config", str(config), "--output", str(output),
        "--dataset", str(ROOT / "data/benchmarks/file-tools-v1/tasks.jsonl"),
        "--level", "e2e", "--split", "dev", "--limit", "1", "--repeats", "1",
        "--concurrency", "2",
    ]) == 0
    result = json.loads((output / "results.json").read_text())
    assert result["summary"]["completed_trials"] == 1
    assert {t["split"] for t in result["trials"]} == {"dev"}
