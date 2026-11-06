"""Environment 迁移的行为契约：隔离导入、旧语义与独立 worker。"""

import asyncio
import importlib
import json
import subprocess
import sys

import pytest


def test_public_environment_contract_and_error_identity():
    from eval_framework import environments
    from eval_framework.harness.core import tool_router

    assert hasattr(environments, "Environment")
    assert environments.Environment is tool_router.Environment
    assert environments.ToolExecutionError is tool_router.ToolExecutionError
    assert environments.EnvironmentFailure is tool_router.EnvironmentFailure
    assert (
        environments.SandboxFilesEnvironment
        is importlib.import_module(
            "eval_framework.environments.sandbox_files"
        ).SandboxFilesEnvironment
    )


def test_offline_public_import_does_not_load_agent_or_inspect(tmp_path):
    script = """
import eval_framework
import builtins, sys
real_import = builtins.__import__
def checked(name, *args, **kwargs):
    if any(s in name for s in ("nanobot", "minimal_agent", "inspect_ai", "deepeval")):
        raise AssertionError("unexpected runtime import: " + name)
    return real_import(name, *args, **kwargs)
builtins.__import__ = checked
from eval_framework.environments import Environment, FileToolsEnvironment
from eval_framework.environments.base.protocol import ToolExecutionError
from pathlib import Path
world = FileToolsEnvironment(parent=Path(sys.argv[1]))
try:
    world.reset({"a": "first\\r\\n"})
    assert world.step({"name": "list_dir", "arguments": {}}) == ["a"]
    assert world.final_state() == {"a": "first\\r\\n"}
finally:
    world.teardown()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_async_offline_adapter_preserves_sync_and_normalizes_new_interface(tmp_path):
    from eval_framework.environments.base.protocol import ToolExecutionError
    from eval_framework.environments.file_tools import AsyncFileToolsEnvironment

    async def run():
        world = AsyncFileToolsEnvironment(["read_file", "list_dir"], parent=tmp_path)
        try:
            await world.reset({"files": {"b": "two", "a": "one\r\n"}})
            assert await world.step("read_file", {"path": "a"}) == "one\r\n"
            assert await world.step("list_dir", {}) == "a\nb"
            with pytest.raises(ToolExecutionError):
                await world.step("write_file", {"path": "a", "content": "changed"})
            with pytest.raises(ToolExecutionError):
                await world.step("read_file", {"path": "missing"})
            assert await world.snapshot() == {"a": "one\r\n", "b": "two"}
            await world.reset({"files": {"fresh": "new"}})
            assert await world.snapshot() == {"fresh": "new"}
        finally:
            await world.teardown()
            await world.teardown()
        assert not list(tmp_path.iterdir())

    asyncio.run(run())


def test_shared_fs_policy_keeps_absolute_paths_size_limits_and_crlf(tmp_path):
    from eval_framework.environments._fs_utils import safe_path, snapshot_files
    from eval_framework.environments.local_files import safe_path as old_safe_path

    path = tmp_path / "a"
    path.write_bytes(b"a\r\nb\r\n")
    assert old_safe_path(tmp_path, str(path)) == path
    assert safe_path(tmp_path, str(path)) == path
    with pytest.raises(ValueError, match="relative"):
        safe_path(tmp_path, str(path), relative_only=True)
    assert snapshot_files(tmp_path) == {"a": "a\r\nb\r\n"}
    path.write_bytes(b"a" * 2_000_000)
    assert len(snapshot_files(tmp_path)["a"]) == 2_000_000
    path.write_bytes(b"a" * 2_000_001)
    with pytest.raises(ValueError, match="2 MB"):
        snapshot_files(tmp_path)
    assert (
        len(snapshot_files(tmp_path, relative_only=True, max_file_bytes=None)["a"])
        == 2_000_001
    )


@pytest.mark.parametrize("relative_only", [False, True])
def test_shared_fs_rejects_traversal_and_symlinks(tmp_path, relative_only):
    from eval_framework.environments._fs_utils import safe_path, snapshot_files

    for path in ("../outside", "a/../b"):
        with pytest.raises(ValueError):
            safe_path(tmp_path, path, relative_only=relative_only)
    (tmp_path / "link").symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError, match="symbolic"):
        safe_path(tmp_path, "link/child", relative_only=relative_only)
    with pytest.raises(ValueError, match="symbolic"):
        snapshot_files(tmp_path, relative_only=relative_only)


def test_worker_payload_runs_without_evaluator_or_site_packages(tmp_path):
    from eval_framework.environments.file_tools.sandbox_env import build_worker_script

    payload = build_worker_script()

    def request(value):
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-c", payload],
            input=json.dumps(value),
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    assert request({"operation": "reset", "files": {"a": "one\r\n"}}) == {
        "value": {"a": "one\r\n"}
    }
    assert request({"operation": "read_file", "arguments": {"path": "a"}}) == {
        "value": "one\r\n"
    }
    assert "tool_error" in request(
        {"operation": "read_file", "arguments": {"path": str(tmp_path / "workspace/a")}}
    )
    assert request({"operation": "snapshot"}) == {"value": {"a": "one\r\n"}}


def test_legacy_worker_script_still_runs_as_a_file(tmp_path):
    from eval_framework.environments import sandbox_files_worker

    result = subprocess.run(
        [sys.executable, "-I", "-S", sandbox_files_worker.__file__],
        input=json.dumps({"operation": "reset", "files": {"a": "literal ' \\ $"}}),
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"value": {"a": "literal ' \\ $"}}


def test_sandbox_stage_errors_and_rejected_calls_do_not_execute(tmp_path, monkeypatch):
    from inspect_ai.util import ExecResult

    from eval_framework.environments.base.protocol import (
        EnvironmentFailure,
        ToolExecutionError,
    )
    from eval_framework.environments.file_tools import sandbox_env

    class LocalProcessSandbox:
        async def exec(self, command, *, input, **kwargs):
            result = subprocess.run(
                command, input=input, text=True, capture_output=True, cwd=tmp_path
            )
            return ExecResult(
                success=result.returncode == 0,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )

    monkeypatch.setattr(sandbox_env, "sandbox", lambda: LocalProcessSandbox())

    async def run():
        world = sandbox_env.SandboxFilesEnvironment(["read_file", "edit_file"])
        await world.reset({"files": {"a": "original"}})
        for name, arguments in [
            ("read_file", {"path": "missing"}),
            ("read_file", {"path": 12}),
            ("edit_file", {"path": "a", "old_text": "absent", "new_text": "new"}),
            ("reset", {"files": {}}),
            ("write_file", {"path": "a", "content": "new"}),
        ]:
            with pytest.raises(ToolExecutionError):
                await world.step(name, arguments)
        assert await world.snapshot() == {"a": "original"}
        (tmp_path / "workspace/link").symlink_to(tmp_path / "outside")
        with pytest.raises(EnvironmentFailure):
            await world.snapshot()
        with pytest.raises(EnvironmentFailure):
            await world.reset({"files": {"../outside": "bad"}})
        await world.teardown()

    asyncio.run(run())


@pytest.mark.parametrize(
    "response", ["not json", "[]", '{"value": "bad snapshot"}', '{"tool_error": 1}']
)
def test_sandbox_bad_protocol_is_environment_failure(response, monkeypatch):
    from inspect_ai.util import ExecResult

    from eval_framework.environments.base.protocol import EnvironmentFailure
    from eval_framework.environments.file_tools import sandbox_env

    class BrokenSandbox:
        async def exec(self, *args, **kwargs):
            return ExecResult(success=True, returncode=0, stdout=response, stderr="")

    monkeypatch.setattr(sandbox_env, "sandbox", lambda: BrokenSandbox())
    with pytest.raises(EnvironmentFailure):
        asyncio.run(sandbox_env.SandboxFilesEnvironment([]).snapshot())


def test_legacy_nanobot_bridge_reexports_same_class():
    from eval_framework.environments import InspectFileToolsEnvironment
    from eval_framework.integrations.nanobot.environments import (
        InspectFileToolsEnvironment as implementation,
    )

    assert InspectFileToolsEnvironment is implementation


def test_flat_worker_bundle_contains_shared_implementation(tmp_path):
    from eval_framework.integrations.nanobot.sources import worker_source_paths

    for name, source in worker_source_paths().items():
        (tmp_path / name).write_bytes(source.read_bytes())
    script = """
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
import nanobot_runtime
root = Path(sys.argv[1]) / 'workspace'
root.mkdir()
p = nanobot_runtime.safe_path(root, 'a')
p.write_bytes(b'a\\r\\n')
assert nanobot_runtime.snapshot_files(root) == {'a': 'a\\r\\n'}
assert 'eval_framework' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_sandbox_preserves_cancellation_and_inspect_limits(monkeypatch):
    from inspect_ai.util import LimitExceededError

    from eval_framework.environments.file_tools import sandbox_env

    for failure in (
        asyncio.CancelledError(),
        LimitExceededError("token", value=2, limit=1),
    ):

        class InterruptedSandbox:
            async def exec(self, *args, failure=failure, **kwargs):
                raise failure

        monkeypatch.setattr(sandbox_env, "sandbox", lambda: InterruptedSandbox())
        with pytest.raises(type(failure)) as caught:
            asyncio.run(sandbox_env.SandboxFilesEnvironment([]).snapshot())
        assert caught.value is failure


def test_environment_sources_participate_in_runtime_identity(monkeypatch):
    from pathlib import Path

    from eval_framework.benchmark.runner import code_identity
    from eval_framework.integrations.nanobot.sources import integration_source_paths

    root = Path(__file__).resolve().parents[2] / "src/eval_framework"
    read_bytes = Path.read_bytes
    baseline = code_identity(["runner.py"])
    for name in (
        "environments/_fs_utils.py",
        "environments/file_tools/payload.py",
        "environments/file_tools/worker_script.py",
        "integrations/nanobot/environments/inspect_file_tools.py",
    ):
        changed = root / name
        with monkeypatch.context() as patch:
            patch.setattr(
                Path,
                "read_bytes",
                lambda path, changed=changed: (
                    read_bytes(path) + (b"\n# drift" if path == changed else b"")
                ),
            )
            assert code_identity(["runner.py"]) != baseline
    sources = set(integration_source_paths().values())
    assert root / "environments/_fs_utils.py" in sources
    assert root / "integrations/nanobot/environments/inspect_file_tools.py" in sources


def test_demo_domain_runs_in_existing_harness_without_core_changes(tmp_path):
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "examples/simple_retail_environment.py"
    assert path.is_file(), "missing injectable demo domain"
    spec = importlib.util.spec_from_file_location("retail_environment_demo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    row = module.run_demo(tmp_path / "logs")
    assert row["status"] == "completed"
    assert row["final_files"] == {"inventory": {"apple": 1}}
    assert row["evidence_complete"] is True
    assert len([event for event in row["events"] if event["type"] == "tool"]) == 2


def test_legacy_modules_keep_file_helpers_and_exception_names(tmp_path):
    from eval_framework.environments import file_tools, sandbox_files
    from eval_framework.environments.base.protocol import ToolExecutionError

    assert hasattr(file_tools, "safe_path")
    assert hasattr(file_tools, "snapshot_files")
    assert hasattr(sandbox_files, "ToolExecutionError")
    path = file_tools.safe_path(tmp_path, "a")
    path.write_text("ok")
    assert file_tools.snapshot_files(tmp_path) == {"a": "ok"}
    assert sandbox_files.ToolExecutionError is ToolExecutionError


def test_legacy_worker_module_execution_and_flat_import(tmp_path):
    from eval_framework.environments import sandbox_files_worker

    result = subprocess.run(
        [sys.executable, "-m", "eval_framework.environments.sandbox_files_worker"],
        input=json.dumps({"operation": "reset", "files": {"a": "one"}}),
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "module entrypoint did not execute"
    assert json.loads(result.stdout) == {"value": {"a": "one"}}
    script = """
import sys, json
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import sandbox_files_worker as worker
assert worker.safe_path(root=Path('workspace'), value='a') == Path('workspace/a')
assert worker.snapshot(root=Path('workspace')) == {'a': 'one'}
print(json.dumps(worker.execute({'operation': 'snapshot'})))
"""
    from pathlib import Path

    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            script,
            str(Path(sandbox_files_worker.__file__).parent),
        ],
        input="",
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"a": "one"}
