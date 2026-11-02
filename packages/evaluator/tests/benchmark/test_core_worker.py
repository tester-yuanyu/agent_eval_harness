"""Actual worker integration, network/write containment and public-only input."""

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
NANOBOT = Path(os.environ.get("NANOBOT_TEST_ROOT", "/Users/yuanyu/Desktop/nanobot"))
PYTHON = NANOBOT / ".venv/bin/python"


def test_worker_implementation_exists():
    assert importlib.util.find_spec("eval_framework.benchmark.core_worker") is not None


def run_worker(tmp_path, operations, *, extras=None, fixtures=None):
    if not PYTHON.exists():
        pytest.skip("real nanobot interpreter unavailable")
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    for path, content in (fixtures or {}).items():
        target = workspace / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    public = {"settings": {}, "operations": operations, **(extras or {})}
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": f"{ROOT}/packages/evaluator/src:{NANOBOT}",
        "DEEPEVAL_TELEMETRY_OPT_OUT": "YES",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [
            str(PYTHON),
            str(
                ROOT / "packages/evaluator/src/eval_framework/benchmark/core_worker.py"
            ),
        ],
        input=json.dumps(
            {
                "task": public,
                "workspace": str(workspace),
                "runtime_dir": str(tmp_path / "runtime"),
            }
        ),
        text=True,
        capture_output=True,
        env=env,
        timeout=60,
    )
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


def op(name, **args):
    return {"id": name.replace(".", "-"), "operation": name, "input": args}


def test_real_memory_persistence_and_session_object_reload(tmp_path):
    observation = run_worker(
        tmp_path,
        [
            op("memory.append", entry="persisted", session_key="a"),
            op("memory.reload"),
            op("memory.read", since_cursor=0),
            op("session.add", key="a:b", role="user", content="hello"),
            op("session.save", key="a:b"),
            op("session.reload", key="a:b"),
            op("session.history", key="a:b"),
        ],
    )
    assert observation["status"] == "completed", observation
    assert observation["execution_kind"] == "real_core_module"
    assert observation["events"][2]["output"][0]["content"] == "persisted"
    assert observation["events"][-1]["output"] == [{"role": "user", "content": "hello"}]
    assert observation["usage"] == {} and observation["errors"] == []


@pytest.mark.parametrize(
    "extras",
    [
        {"oracle": {"answer": 1}},
        {"id": "private"},
        {"settings": {"config_path": "/tmp/user"}},
    ],
)
def test_worker_rejects_private_projection(tmp_path, extras):
    result = run_worker(tmp_path, [op("memory.latest")], extras=extras)
    assert result["status"] == "error"
    assert result["events"] == [] and result["errors"]


def test_worker_refuses_symlink_escape(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "memory").symlink_to(outside, target_is_directory=True)
    result = run_worker(tmp_path, [op("memory.write", content="must not write")])
    assert result["status"] == "error"
    assert not (outside / "MEMORY.md").exists()


def test_network_and_outside_writes_are_blocked_in_child_process(tmp_path):
    import sys

    worker_directory = ROOT / "packages/evaluator/src/eval_framework/benchmark"
    workspace = tmp_path / "workspace"
    runtime = tmp_path / "runtime"
    workspace.mkdir()
    runtime.mkdir()
    code = """
import json, socket, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from core_worker import install_safety_guards
workspace, runtime, outside = map(Path, sys.argv[2:])
install_safety_guards(workspace, runtime)
blocked = []
for name, action in [("network", lambda: socket.socket().connect(("127.0.0.1", 9))),
                     ("write", lambda: outside.write_text("forbidden"))]:
    try:
        action()
    except PermissionError:
        blocked.append(name)
print(json.dumps(blocked))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(worker_directory),
            str(workspace),
            str(runtime),
            str(tmp_path / "outside"),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["network", "write"]
    assert not (tmp_path / "outside").exists()


def test_expected_component_exception_has_event_and_next_operation_continues(tmp_path):
    # MEMORY.md is a directory. This is a valid public fixture state, so the
    # actual API exception must be recorded rather than silently passed.
    workspace = tmp_path / "workspace"
    (workspace / "memory/MEMORY.md").mkdir(parents=True)
    result = run_worker(tmp_path, [op("memory.read_long"), op("memory.latest")])
    assert result["status"] == "completed"
    assert result["events"][0]["output"] is None
    assert result["events"][0]["error"]["type"] == "IsADirectoryError"
    assert result["events"][1]["output"] == 0
