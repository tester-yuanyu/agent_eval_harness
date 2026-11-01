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


def test_snapshot_preserves_crlf_evidence(tmp_path):
    (tmp_path / "fixture.txt").write_bytes(b"a\r\nb\r\n")
    assert runtime.snapshot_files(tmp_path) == {"fixture.txt": "a\r\nb\r\n"}


@pytest.mark.parametrize("native_sample", [False, True])
def test_worker_timeout_kills_child_and_keeps_independent_state(
    tmp_path, monkeypatch, native_sample
):
    monkeypatch.setenv("BENCHMARK_PRIVATE_VALUE", "must-not-enter-worker")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("initial")
    import shutil

    from eval_framework.benchmark import inspect_runtime

    shutil.copy(Path(runtime.__file__), tmp_path / "nanobot_runtime.py")
    worker = tmp_path / "slow_worker.py"
    worker.write_text(r"""
import json, sys, time, os
from pathlib import Path

p = json.load(sys.stdin)
assert "BENCHMARK_PRIVATE_VALUE" not in os.environ
Path(p["workspace"], "pid").write_text(str(os.getpid()))
Path(p["workspace"], "a.txt").write_text("partial")
Path(p["runtime_dir"], "events.jsonl").write_text(
    json.dumps(
        {
            "id": "one",
            "type": "tool",
            "name": "write_file",
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
        inspect_runtime, "__file__", str(tmp_path / "inspect_runtime.py")
    )
    worker.rename(tmp_path / "module_worker.py")
    observation = asyncio.run(
        inspect_runtime.execute_boundary(
            {"id": "timeout", "prompt": "read"},
            mode="module",
            identity={"agent": "test"},
            workspace=workspace,
            config={
                "nanobot_root": str(tmp_path),
                "python": sys.executable,
                "model": "offline",
                "api_key_env": "BENCHMARK_TEST_KEY",
                "timeout_seconds": 1 if native_sample else 10,
                "module_timeout_seconds": 20 if native_sample else 0.3,
                "sandbox": "local",
            },
        )
    )
    assert observation["status"] == "timeout", observation
    assert observation["errors"][0]["kind"] == "agent"
    assert observation["before_files"] == {"a.txt": "initial"}
    assert observation["final_files"]["a.txt"] == "partial"
    assert observation["events"][0]["incomplete"] is True
    with pytest.raises(ProcessLookupError):
        os.kill(int(observation["final_files"]["pid"]), 0)
    from eval_framework.benchmark.metrics import score_task

    assessment = score_task(
        {
            "id": "timeout",
            "prompt": "read",
            "followups": [],
            "fixtures": {"a.txt": "initial"},
            "allowed_tools": ["write_file"],
            "required_tools": [],
            "oracle": {"expected_files": {"a.txt": "done"}},
        },
        observation,
    )
    assert assessment["validity"] == "VALID", assessment
    assert assessment["verdict"] == "FAIL", assessment


def test_real_nanobot_loop_offline_multiturn_and_tool_containment(
    tmp_path, monkeypatch
):
    """Run genuine upstream code with a deterministic, no-network transport."""
    root = Path(os.environ.get("NANOBOT_TEST_ROOT", "/Users/yuanyu/Desktop/nanobot"))
    python = root / ".venv/bin/python"
    if not python.exists():
        pytest.skip(
            "set NANOBOT_TEST_ROOT to exercise the optional real SDK integration"
        )
    workspace, private = tmp_path / "workspace", tmp_path / "private"
    monkeypatch.setenv("INSPECT_BRIDGE_API_KEY", "inspect")
    workspace.mkdir()
    private.mkdir()
    (private / "secret.txt").write_text("PRIVATE-SENTINEL-MUST-NOT-BE-READ")
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
                        {"path": "output.txt", "content": "transformed value inspect"},
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
            "api_key_env": "INSPECT_BRIDGE_API_KEY",
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
    assert observed["turns"][1]["snapshot"]["output.txt"] == "transformed value inspect"
    assert "Error" in observed["containment"]["outside"]
    assert "PRIVATE-SENTINEL" not in observed["containment"]["outside"]
    assert "secret.txt" not in runtime.snapshot_files(workspace)
    assert "Error" in observed["containment"]["builtin"]
    assert set(runtime.snapshot_files(workspace)) == {"input.txt", "output.txt"}
    events = list(
        {
            event["id"]: event
            for event in (
                json.loads(line)
                for line in (private / "events.jsonl").read_text().splitlines()
            )
        }.values()
    )
    assert events[-1]["snapshot"]["output.txt"] == "transformed value inspect"
    assert not [event for event in events if event["type"] == "generation"]
    # Model logging is now validated through the real Inspect bridge integration.
    assert len([event for event in events if event["type"] == "tool"]) == 2
    assert all(event["end_time"] >= event["start_time"] for event in events)


def test_provider_failure_stops_followups_and_media_paths_are_denied(tmp_path):
    root = Path(os.environ.get("NANOBOT_TEST_ROOT", "/Users/yuanyu/Desktop/nanobot"))
    python = root / ".venv/bin/python"
    if not python.exists():
        pytest.skip("optional installed nanobot integration")
    workspace, private = tmp_path / "workspace", tmp_path / "private"
    workspace.mkdir()
    (private / "media").mkdir(parents=True)
    (private / "media/sentinel.txt").write_text("PRIVATE-MEDIA-SENTINEL")
    payload = {
        "task": {
            "id": "error",
            "prompt": "Create output.txt",
            "followups": ["Now read it"],
            "allowed_tools": ["write_file"],
            "max_steps": 1,
        },
        "config": {
            "nanobot_root": str(root),
            "model": "offline",
            "tokenizer_mode": "byte_fallback",
        },
        "workspace": str(workspace),
        "runtime_dir": str(private),
    }
    script = r"""
import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from nanobot_worker import run_task,strict_tools
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.base import LLMResponse
from nanobot.config.loader import set_config_path
class Provider(OpenAICompatProvider):
    calls=0
    async def chat(self,*args,**kwargs):
        self.calls+=1
        return LLMResponse(
            content="Provider rejected credentials", finish_reason="error",
            error_kind="authentication", error_should_retry=False)
async def main():
    p=json.loads(sys.argv[2])
    provider=Provider(api_key="offline",default_model="offline")
    observed=await run_task(p,provider=provider)
    (Path(p["workspace"])/"escape").symlink_to(Path(p["runtime_dir"])/"media/sentinel.txt")
    set_config_path(Path(p["runtime_dir"])/"config.json")
    tool=strict_tools(Path(p["workspace"]),["read_file"])[0]
    media=str(Path(p["runtime_dir"])/"media/sentinel.txt")
    observed["media"]=str(await tool.execute(path=media))
    observed["symlink"]=str(await tool.execute(path="escape"))
    observed["calls"]=provider.calls
    print(json.dumps(observed))
asyncio.run(main())
"""
    completed = subprocess.run(
        [
            str(python),
            "-c",
            script,
            str(Path(runtime.__file__).parent),
            json.dumps(payload),
        ],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    observed = json.loads(completed.stdout)
    assert observed["status"] == "error", observed
    assert observed["errors"][0]["kind"] == "provider"
    assert observed["calls"] == 1
    assert len(observed["turns"]) == 1
    assert "PRIVATE-MEDIA-SENTINEL" not in observed["media"]
    assert "Error" in observed["media"]
    assert "PRIVATE-MEDIA-SENTINEL" not in observed["symlink"]
    assert "Error" in observed["symlink"]
