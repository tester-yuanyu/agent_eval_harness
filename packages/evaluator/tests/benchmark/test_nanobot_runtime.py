from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from eval_framework.benchmark import nanobot_runtime as runtime


def test_execution_projection_excludes_oracle_and_rejects_extra_tools():
    with pytest.raises(ValueError, match="non-execution"):
        runtime.execution_projection(
            {"id": "one", "prompt": "read", "oracle": {"answer": "secret"}}
        )
    with pytest.raises(ValueError, match="filesystem"):
        runtime.execution_projection(
            {"id": "one", "prompt": "read", "allowed_tools": ["exec"]}
        )


def test_snapshots_are_independent_and_reject_symlinks(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "input.txt").write_text("before")
    before = runtime.snapshot_files(root)
    (root / "input.txt").write_text("after")
    assert before == {"input.txt": "before"}
    assert runtime.snapshot_files(root) == {"input.txt": "after"}
    (root / "outside").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="symbolic"):
        runtime.snapshot_files(root)
    with pytest.raises(ValueError, match="traversal"):
        runtime.safe_path(root, "../escape")


def test_worker_timeout_kills_child_and_keeps_independent_state(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("initial")
    worker = tmp_path / "slow_worker.py"
    worker.write_text(r"""
import json, sys, time, os
from pathlib import Path

p = json.load(sys.stdin)
Path(p["workspace"], "pid").write_text(str(os.getpid()))
Path(p["workspace"], "a.txt").write_text("partial")
Path(p["runtime_dir"], "events.jsonl").write_text(
    json.dumps(
        {
            "id": "one",
            "type": "generation",
            "name": "model",
            "input": {},
            "output": None,
            "usage": {},
            "start_time": "2026-01-01T00:00:00+00:00",
            "end_time": None,
        }
    )
    + "\n"
)
time.sleep(20)
""")
    monkeypatch.setattr(
        runtime,
        "runtime_identity",
        lambda _config: {"agent": "nanobot", "model": "offline"},
    )
    monkeypatch.setattr(runtime, "__file__", str(tmp_path / "nanobot_runtime.py"))
    worker.rename(tmp_path / "nanobot_worker.py")
    monkeypatch.setenv("BENCHMARK_TEST_KEY", "not-a-real-key")
    observation = asyncio.run(
        runtime.execute_task(
            {"id": "timeout", "prompt": "read"},
            workspace=workspace,
            config={
                "nanobot_root": str(tmp_path),
                "python": sys.executable,
                "model": "offline",
                "api_key_env": "BENCHMARK_TEST_KEY",
                "timeout_seconds": 0.3,
            },
        )
    )
    assert observation["status"] == "timeout"
    assert observation["before_files"] == {"a.txt": "initial"}
    assert observation["final_files"]["a.txt"] == "partial"
    assert observation["events"][0]["incomplete"] is True
    with pytest.raises(ProcessLookupError):
        os.kill(int(observation["final_files"]["pid"]), 0)


def test_real_nanobot_loop_offline_multiturn_and_tool_containment(tmp_path):
    """Run genuine upstream code with a deterministic, no-network transport."""
    root = Path(os.environ.get("NANOBOT_TEST_ROOT", "/Users/yuanyu/Desktop/nanobot"))
    python = root / ".venv/bin/python"
    if not python.exists():
        pytest.skip(
            "set NANOBOT_TEST_ROOT to exercise the optional real SDK integration"
        )
    workspace, private = tmp_path / "workspace", tmp_path / "private"
    workspace.mkdir()
    private.mkdir()
    (workspace / "input.txt").write_text("original value")
    module_dir = Path(runtime.__file__).parent
    script = r"""
import asyncio, json, sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from nanobot_worker import run_task, strict_tools
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.base import LLMResponse, ToolCallRequest

payload = json.loads(sys.argv[2])
import nanobot.utils.helpers as helpers


def offline_tokenizer():
    raise RuntimeError("offline tokenizer fallback")


helpers._get_token_encoding = offline_tokenizer
calls = []


async def chat(self, messages, **kwargs):
    calls.append(messages)
    assert {x["function"]["name"] for x in kwargs.get("tools", [])} <= {
        "read_file",
        "write_file",
        "edit_file",
        "list_dir",
    }
    index = len(calls)
    if index == 1:
        return LLMResponse(
            None,
            [ToolCallRequest("read1", "read_file", {"path": "input.txt"})],
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )
    if index == 2:
        return LLMResponse(
            None,
            [
                ToolCallRequest(
                    "write1",
                    "write_file",
                    {"path": "output.txt", "content": "transformed value"},
                )
            ],
            usage={"prompt_tokens": 12, "completion_tokens": 7},
        )
    if index == 3:
        return LLMResponse(
            "Created output.txt", usage={"prompt_tokens": 15, "completion_tokens": 5}
        )
    assert any(m.get("content") == "Created output.txt" for m in messages), (
        "session history did not survive"
    )
    return LLMResponse(
        "The previous output was transformed value",
        usage={"prompt_tokens": 20, "completion_tokens": 6},
    )


OpenAICompatProvider.chat = chat


async def main():
    result = await run_task(payload)
    tools = {
        t.name: t
        for t in strict_tools(Path(payload["workspace"]), ["read_file", "write_file"])
    }
    outside = await tools["read_file"].execute(
        path=str(Path(payload["runtime_dir"]) / "secret.txt")
    )
    builtin = await tools["read_file"].execute(path="skills/github/SKILL.md")
    result["containment"] = {"outside": str(outside), "builtin": str(builtin)}
    print(json.dumps(result))


asyncio.run(main())
"""
    payload = {
        "task": {
            "id": "offline-real",
            "prompt": "Read input and create output",
            "followups": ["What did you write?"],
            "allowed_tools": ["read_file", "write_file", "edit_file", "list_dir"],
            "max_steps": 8,
        },
        "config": {
            "nanobot_root": str(root),
            "model": "offline",
            "max_steps": 8,
            "tokenizer_mode": "byte_fallback",
        },
        "workspace": str(workspace),
        "runtime_dir": str(private),
    }
    completed = subprocess.run(
        [str(python), "-c", script, str(module_dir), json.dumps(payload)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    observed = json.loads(completed.stdout)
    assert observed["status"] == "completed", observed
    assert len(observed["turns"]) == 2
    assert observed["turns"][1]["snapshot"]["output.txt"] == "transformed value"
    assert "workspace policy" in observed["containment"]["outside"]
    assert "Error" in observed["containment"]["builtin"]
    assert set(runtime.snapshot_files(workspace)) == {"input.txt", "output.txt"}
    events = runtime._journal_events(private / "events.jsonl")
    assert len([event for event in events if event["type"] == "generation"]) == 4
    assert len([event for event in events if event["type"] == "tool"]) == 2
    assert all(event["end_time"] >= event["start_time"] for event in events)
    assert (
        sum(
            event["usage"].get("prompt_tokens", 0)
            for event in events
            if event["type"] == "generation"
        )
        == 57
    )
