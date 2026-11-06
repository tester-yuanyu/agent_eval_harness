"""跨层边界回归：离线读取与比较不能依赖执行运行时。"""

import json
import subprocess
import sys


def test_comparison_works_without_loading_benchmark_execution():
    script = """
import eval_framework
import builtins
real_import = builtins.__import__
def checked(name, *args, **kwargs):
    if name.startswith(("inspect_ai", "deepeval", "nanobot", "minimal_agent")):
        raise AssertionError("execution dependency: " + name)
    return real_import(name, *args, **kwargs)
builtins.__import__ = checked
from eval_framework.aggregator.comparison import compare_runs
run = {
    "identity": {"dataset": "fixture", "scoring_version": "v1"},
    "planned_case_ids": ["one"], "trials_per_case": 1,
    "trials": [{"case_id": "one", "trial": 1, "split": "dev", "category": "test",
                "assessment": {"verdict": "PASS", "validity": "VALID"},
                "observation": {"usage": {}, "events": []}, "latency_seconds": 1}],
}
result = compare_runs(run, run)
assert result["pass_rate_delta"] == 0
assert result["baseline"]["completed_trials"] == 1
try:
    compare_runs(run, {**run, "trials": []})
except ValueError as exc:
    assert "incomplete" in str(exc)
else:
    raise AssertionError("accepted incomplete run")
import sys
assert "eval_framework.benchmark.runner" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_digest_preserves_historical_json_bytes():
    import hashlib

    from eval_framework.benchmark.runner import digest

    value = {"中文": [True, None, 1.0], "a": "line\nvalue"}
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert digest(value) == hashlib.sha256(raw.encode()).hexdigest()


def test_domain_and_reference_remain_offline_and_answer_free():
    from pathlib import Path

    from eval_framework.benchmark.domains.file_tools import (
        dataset_identity,
        execution_task,
        load_tasks,
    )
    from eval_framework.benchmark.scorers.reference_runner import reference_observation

    root = Path(__file__).resolve().parents[4]
    for name in ("file-tools-v1", "file-tools-v2"):
        dataset = root / "data/benchmarks" / name
        if not dataset.exists():
            continue
        manifest = json.loads((dataset / "manifest.json").read_text())
        assert dataset_identity(dataset) == manifest
        tasks = load_tasks(dataset)
        for task in tasks:
            public = execution_task(task)
            assert not {"oracle", "reference", "checkpoints"} & public.keys()
            if task.get("execution_mode", "agent") != "agent":
                continue
            expected = reference_observation(task)
            changed = {**task, "oracle": {"poison": "must never be read"}}
            assert reference_observation(changed) == expected


def test_dataset_reader_preserves_utf8_crlf_and_raw_digest(tmp_path):
    import hashlib

    from eval_framework.benchmark.datasets.io import file_sha256, read_jsonl_bytes

    raw = b'{"text": "a\\r\\nb"}\r\n\r\n' + '{"text": "中文"}\n'.encode()
    path = tmp_path / "tasks.jsonl"
    path.write_bytes(raw)
    assert read_jsonl_bytes(raw) == [{"text": "a\r\nb"}, {"text": "中文"}]
    assert file_sha256(path) == hashlib.sha256(raw).hexdigest()
    assert path.read_bytes() == raw


def test_environment_file_operations_do_not_import_nanobot_runtime(tmp_path):
    script = """
import eval_framework
import builtins
from pathlib import Path
real_import = builtins.__import__
def checked(name, *args, **kwargs):
    if "nanobot" in name:
        raise AssertionError("agent coupling: " + name)
    return real_import(name, *args, **kwargs)
builtins.__import__ = checked
from eval_framework.environments.local_files import safe_path, snapshot_files
import sys
root = Path(sys.argv[1])
path = safe_path(root, "fixture.txt")
path.write_bytes(b"a\\r\\nb\\r\\n")
assert snapshot_files(root) == {"fixture.txt": "a\\r\\nb\\r\\n"}
try:
    safe_path(root, "../outside")
except ValueError:
    pass
else:
    raise AssertionError("accepted traversal")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_docker_worker_bundle_imports_without_site_packages(tmp_path):
    from pathlib import Path

    from eval_framework.benchmark.inspect_docker import prepare_docker_sandbox

    root = tmp_path / "source"
    (root / "nanobot").mkdir(parents=True)
    (root / "nanobot/__init__.py").write_text("")
    (root / "pyproject.toml").write_text('[project]\nname="fixture"\nversion="1"\n')
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    _, compose = prepare_docker_sandbox(
        {"nanobot_root": str(root), "tokenizer_mode": "byte_fallback"},
        tmp_path / "build",
    )
    bundle = Path(compose).parent / "harness"
    script = """
import sys
sys.path.insert(0, sys.argv[1])
import nanobot_runtime, nanobot_worker, module_worker, decision_worker
import local_files
assert nanobot_runtime.snapshot_files is local_files.snapshot_files
prepared = nanobot_runtime.prepare_tokenizer({"tokenizer_mode": "byte_fallback"})
assert prepared["mode"] == "byte_fallback"
assert "eval_framework" not in sys.modules
assert "nanobot" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script, str(bundle)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_moved_implementations_remain_bound_to_run_identity(monkeypatch):
    from pathlib import Path

    from eval_framework.benchmark.runner import code_identity
    from eval_framework.integrations.nanobot.sources import integration_source_paths

    framework = Path(__file__).resolve().parents[2] / "src/eval_framework"
    original_read = Path.read_bytes
    baseline = code_identity(["runner.py", "tasks.py", "oracle.py"])
    for name in (
        "benchmark/identity.py",
        "benchmark/run_context.py",
        "benchmark/domains/file_tools.py",
        "benchmark/datasets/io.py",
        "benchmark/scorers/reference_runner.py",
        "aggregator/comparison.py",
        "environments/local_files.py",
        "integrations/nanobot/nanobot_sdk.py",
        "integrations/nanobot/sources.py",
    ):
        changed = framework / name
        with monkeypatch.context() as patch:
            patch.setattr(
                Path,
                "read_bytes",
                lambda path, changed=changed: (
                    original_read(path) + (b"\n# drift" if path == changed else b"")
                ),
            )
            assert code_identity(["runner.py", "tasks.py", "oracle.py"]) != baseline, (
                name
            )
    sources = set(integration_source_paths().values())
    assert framework / "environments/local_files.py" in sources
    assert framework / "integrations/nanobot/nanobot_sdk.py" in sources


def test_adapter_identity_detects_moved_sdk_changes(monkeypatch):
    from pathlib import Path

    from eval_framework.agent_adapter import adapter_identity
    from eval_framework.benchmark.adapters import NanobotAdapter, NanobotRuntimeAdapter
    from eval_framework.integrations.nanobot import nanobot_sdk

    assert NanobotAdapter is NanobotRuntimeAdapter
    adapter = NanobotAdapter({})
    before = adapter_identity(adapter)
    changed = Path(nanobot_sdk.__file__)
    original_read = Path.read_bytes
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda path: (
            original_read(path) + (b"\n# sdk drift" if path == changed else b"")
        ),
    )
    assert adapter_identity(adapter) != before
