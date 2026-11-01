import json
import os
import subprocess
from copy import deepcopy
from pathlib import Path

from eval_framework.benchmark.trajectory import score_trajectory


def evidence():
    return {
        "status": "completed",
        "evidence_complete": True,
        "events": [
            {"id": "t1", "type": "turn", "name": "turn-1", "turn": 1},
            {
                "id": "w1",
                "type": "tool",
                "name": "write_file",
                "parent_id": "t1",
                "turn": 1,
                "execution_started": True,
                "input": {"path": "result.txt", "content": "wrong"},
                "output": "written",
                "end_time": "2026-11-01T00:00:01Z",
                "tool_schema": {
                    "type": "object",
                    "required": ["path", "content"],
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
                "before_files": {},
                "after_files": {"result.txt": "wrong"},
            },
            {"id": "t2", "type": "turn", "name": "turn-2", "turn": 2},
        ],
        "turns": [
            {
                "input": "write first",
                "output": "done",
                "snapshot": {"result.txt": "wrong"},
            },
            {"input": "fix it", "output": "done", "snapshot": {"result.txt": "final"}},
        ],
        "final_files": {"result.txt": "final"},
    }


def task(checkpoints):
    return {
        "id": "case",
        "prompt": "write first",
        "allowed_tools": ["write_file", "edit_file", "read_file"],
        "checkpoints": checkpoints,
    }


def checkpoint(records, name):
    return next(record for record in records if record.get("checkpoint_id") == name)


def test_wrong_intermediate_state_is_not_rescued_by_correct_final_state():
    records = score_trajectory(
        task(
            [
                {
                    "id": "first",
                    "kind": "turn_files",
                    "required": True,
                    "turn": 1,
                    "expected_files": {"result.txt": "first"},
                }
            ]
        ),
        evidence(),
    )
    result = checkpoint(records, "first")
    assert result["score"] == 0
    assert result["success"] is False and result["formal"] is True
    assert result["scope"] == "turn" and result["event_id"] == "t1"
    assert result["backend"] == "deepeval"


def test_missing_snapshot_is_unscored_instead_of_using_final_state():
    observed = evidence()
    del observed["turns"][0]["snapshot"]
    result = checkpoint(
        score_trajectory(
            task(
                [
                    {
                        "id": "first",
                        "kind": "turn_files",
                        "required": True,
                        "turn": 1,
                        "expected_files": {"result.txt": "final"},
                    }
                ]
            ),
            observed,
        ),
        "first",
    )
    assert result["score"] is None and result["success"] is None
    assert result["status"] == "MISSING" and result["formal"] is True


def test_tool_schema_is_structural_not_semantic_argument_correctness():
    records = score_trajectory(
        task(
            [
                {
                    "id": "content",
                    "kind": "tool_args",
                    "required": True,
                    "tool": "write_file",
                    "arguments": {"content": "first"},
                    "turn": 1,
                }
            ]
        ),
        evidence(),
    )
    structural = next(row for row in records if row["name"] == "tool_schema")
    assert structural["score"] == 1 and structural["formal"] is False
    assert checkpoint(records, "content")["score"] == 0
    assert structural["event_id"] == "w1"


def test_argument_subset_allows_additional_arguments_and_later_valid_attempt():
    observed = evidence()
    allowed = deepcopy(observed["events"][1])
    allowed.update(
        id="w2", input={"path": "result.txt", "content": "first", "extra": "retained"}
    )
    observed["events"].insert(2, allowed)
    result = checkpoint(
        score_trajectory(
            task(
                [
                    {
                        "id": "content",
                        "kind": "tool_args",
                        "required": True,
                        "tool": "write_file",
                        "arguments": {"path": "result.txt", "content": "first"},
                    }
                ]
            ),
            observed,
        ),
        "content",
    )
    assert result["score"] == 1 and result["event_id"] == "w2"


def test_tool_order_allows_other_tools_between_required_dependency():
    observed = evidence()
    read = deepcopy(observed["events"][1])
    read.update(id="r1", name="read_file", input={"path": "source.txt"})
    observed["events"].insert(1, read)
    result = checkpoint(
        score_trajectory(
            task(
                [
                    {
                        "id": "dependency",
                        "kind": "tool_order",
                        "required": True,
                        "before": "read_file",
                        "after": "write_file",
                    }
                ]
            ),
            observed,
        ),
        "dependency",
    )
    assert result["score"] == 1
    assert result["scope"] == "chain" and result["event_id"] == "w1"
    assert result["evidence_ids"] == ["r1", "w1"]


def test_absent_call_is_failure_only_when_trace_is_complete():
    check = {
        "id": "read",
        "kind": "tool_args",
        "required": True,
        "tool": "read_file",
        "arguments": {"path": "source.txt"},
    }
    observed = evidence()
    assert checkpoint(score_trajectory(task([check]), observed), "read")["score"] == 0
    observed["evidence_complete"] = False
    result = checkpoint(score_trajectory(task([check]), observed), "read")
    assert result["status"] == "MISSING" and result["score"] is None


def test_rejected_attempt_is_not_successful_checkpoint_execution():
    observed = evidence()
    observed["events"][1]["execution_started"] = False
    check = {
        "id": "write",
        "kind": "tool_args",
        "required": True,
        "tool": "write_file",
        "arguments": {"path": "result.txt"},
    }
    assert checkpoint(score_trajectory(task([check]), observed), "write")["score"] == 0


def test_missing_recorded_schema_is_explicit_unscored_diagnostic():
    observed = evidence()
    del observed["events"][1]["tool_schema"]
    result = next(
        row
        for row in score_trajectory(task([]), observed)
        if row["name"] == "tool_schema"
    )
    assert result["status"] == "MISSING" and result["score"] is None
    assert result["formal"] is False


def test_real_worker_captures_each_tool_before_and_after_state(tmp_path):
    import pytest
    from eval_framework.benchmark import nanobot_runtime

    root = Path(os.environ.get("NANOBOT_TEST_ROOT", "/Users/yuanyu/Desktop/nanobot"))
    python = root / ".venv/bin/python"
    if not python.exists():
        pytest.skip("optional real nanobot interpreter unavailable")
    workspace, private = tmp_path / "workspace", tmp_path / "private"
    workspace.mkdir()
    private.mkdir()
    (workspace / "input.txt").write_text("original")
    payload = {
        "task": {
            "id": "snapshots",
            "prompt": "write",
            "allowed_tools": ["read_file", "write_file"],
            "max_steps": 5,
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
import asyncio, json, sys
sys.path.insert(0, sys.argv[1])
from nanobot_worker import run_task
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.base import LLMResponse, ToolCallRequest
count = 0
async def chat(self, messages, **kwargs):
    global count
    count += 1
    if count == 1:
        args = {"path":"result.txt", "content":"saved"}
        return LLMResponse(None, [ToolCallRequest("write", "write_file", args)])
    if count == 2:
        args = {"path":"result.txt"}
        return LLMResponse(None, [ToolCallRequest("read", "read_file", args)])
    return LLMResponse("done")
OpenAICompatProvider.chat = chat
print(json.dumps(asyncio.run(run_task(json.loads(sys.argv[2])))))
"""
    completed = subprocess.run(
        [
            str(python),
            "-c",
            script,
            str(Path(nanobot_runtime.__file__).parent),
            json.dumps(payload),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    events = nanobot_runtime._journal_events(private / "events.jsonl")
    write, read = [event for event in events if event["type"] == "tool"]
    assert write["before_files"] == {"input.txt": "original"}
    assert write["after_files"] == {"input.txt": "original", "result.txt": "saved"}
    assert read["before_files"] == write["after_files"] == read["after_files"]
    assert write["execution_started"] is True
    assert write["tool_schema"]["properties"]["content"]["type"] == "string"
    assert write["turn"] == 1 and read["turn"] == 1
