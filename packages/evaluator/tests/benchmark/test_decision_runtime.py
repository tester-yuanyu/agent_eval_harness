from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from eval_framework.benchmark.decision_runtime import (
    decision_execution_projection,
    execute_decision_task,
)
from eval_framework.benchmark.tasks import execution_task, load_tasks, validate_task

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / "data/benchmarks/model-decisions-v1"


def test_decision_dataset_private_projection_and_three_variant_families():
    tasks = load_tasks(DATA)
    assert len(tasks) == 24
    assert all(count == 3 for count in Counter(t["family"] for t in tasks).values())
    assert Counter(t["split"] for t in tasks) == {"dev": 18, "holdout": 6}
    assert all(
        t["execution_mode"] == "decision" and t["evaluation_level"] == "module"
        for t in tasks
    )
    for task in tasks:
        projected = execution_task(task)
        assert "oracle" not in projected and "reference" not in projected
        assert "evaluation_level" not in projected and "execution_mode" not in projected
        assert "decision_context" in projected
        assert decision_execution_projection(projected) == projected
    abstentions = [t for t in tasks if t["oracle"]["decision"]["allow_no_tool"]]
    assert len(abstentions) == 6
    assert all(
        not t["required_tools"] and t["oracle"]["decision"]["max_calls"] == 0
        for t in abstentions
    )


def test_decision_private_fields_and_malformed_oracle_rejected():
    with pytest.raises(ValueError, match="non-execution"):
        decision_execution_projection({"prompt": "hello", "oracle": {"decision": {}}})
    task = load_tasks(DATA)[0]
    task["oracle"]["decision"]["max_calls"] = True
    with pytest.raises(ValueError, match="decision"):
        validate_task(task)


def test_decision_generation_is_immutable(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "build_decisions", DATA / "build_dataset.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build_dataset(tmp_path / "data")
    target = tmp_path / "data/tasks.jsonl"
    assert target.read_bytes() == (DATA / "tasks.jsonl").read_bytes()
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="immutable"):
        module.build_dataset(tmp_path / "data")


def test_missing_key_never_runs_model(tmp_path, monkeypatch):
    import eval_framework.benchmark.decision_runtime as runtime

    monkeypatch.setattr(
        runtime,
        "decision_identity",
        lambda config: {"agent": "nanobot", "model": "offline"},
    )
    monkeypatch.delenv("DECISION_TEST_MISSING_KEY", raising=False)
    task = execution_task(load_tasks(DATA)[0])
    result = asyncio.run(
        execute_decision_task(
            task,
            config={
                "nanobot_root": str(tmp_path),
                "api_key_env": "DECISION_TEST_MISSING_KEY",
            },
            workspace=tmp_path,
        )
    )
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "missing_api_key"
    assert not result["events"]


def test_worker_single_decision_does_not_execute_generated_write(tmp_path):
    root = Path(os.environ.get("NANOBOT_TEST_ROOT", "/Users/yuanyu/Desktop/nanobot"))
    python = root / ".venv/bin/python"
    if not python.exists():
        pytest.skip("optional installed nanobot integration")
    workspace, private = tmp_path / "workspace", tmp_path / "private"
    workspace.mkdir()
    private.mkdir()
    (workspace / "input.txt").write_text("keep\n")
    task = {
        "id": "offline-test",
        "prompt": "Create output.txt containing hello",
        "followups": [],
        "fixtures": {"input.txt": "keep\n"},
        "allowed_tools": ["read_file", "write_file", "edit_file", "list_dir"],
        "max_steps": 1,
        "decision_context": "User-provided context only.",
    }
    payload = {
        "task": task,
        "config": {"model": "offline"},
        "workspace": str(workspace),
        "runtime_dir": str(private),
    }
    script = r"""
import asyncio,json,sys
sys.path.insert(0,sys.argv[1])
from decision_worker import run_decision_task
from nanobot.providers.base import LLMResponse,ToolCallRequest
class OfflineProvider:
    def __init__(self): self.calls=0
    async def chat(self,messages,**kwargs):
        self.calls+=1
        assert self.calls==1
        assert {t['function']['name'] for t in kwargs['tools']} == {
            'read_file','write_file','edit_file','list_dir'
        }
        assert 'oracle' not in json.dumps(messages)
        return LLMResponse(
            None,[ToolCallRequest('write1','write_file',
                {'path':'output.txt','content':'hello'})],
            usage={'prompt_tokens':10,'completion_tokens':5}
        )
async def main():
    provider=OfflineProvider()
    result=await run_decision_task(json.loads(sys.argv[2]),provider=provider)
    result['transport_calls']=provider.calls
    print(json.dumps(result))
asyncio.run(main())
"""
    completed = subprocess.run(
        [
            str(python),
            "-c",
            script,
            str(ROOT / "packages/evaluator/src/eval_framework/benchmark"),
            json.dumps(payload),
        ],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["transport_calls"] == 1
    assert result["execution_kind"] == "offline_decision_test"
    assert result["status"] == "completed"
    assert not [e for e in result["events"] if e["type"] == "generation"]
    # The native Inspect bridge, tested separately, owns generation events.
    assert not [e for e in result["events"] if e["type"] == "tool"]
    assert result["decision"]["tool_calls"][0]["name"] == "write_file"
    assert not (workspace / "output.txt").exists()
    assert (workspace / "input.txt").read_text() == "keep\n"
