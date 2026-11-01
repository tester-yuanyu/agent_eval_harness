from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from eval_framework.benchmark.module_runtime import (
    execute_module_task,
    module_execution_projection,
)
from eval_framework.benchmark.tasks import execution_task, load_tasks

ROOT = Path(__file__).resolve().parents[4]


def test_projection_rejects_private_data_and_unknown_tool():
    with pytest.raises(ValueError, match="non-execution"):
        module_execution_projection({"id": "test", "prompt": "test", "oracle": {}})
    with pytest.raises(ValueError):
        module_execution_projection(
            {
                "id": "test",
                "prompt": "test",
                "module_calls": [{"name": "exec", "arguments": {"command": "true"}}],
            }
        )


def test_all_real_module_cases_have_independent_state_and_expected_error_evidence(
    tmp_path,
):
    source = Path(os.environ.get("NANOBOT_TEST_ROOT", "/Users/yuanyu/Desktop/nanobot"))
    if not (source / ".venv/bin/python").exists():
        pytest.skip("optional installed nanobot integration")
    tasks = [
        t
        for t in load_tasks(ROOT / "data/benchmarks/file-tools-v2")
        if t["evaluation_level"] == "module"
    ]
    representatives = list({t["family"]: t for t in tasks}.values())
    for index, task in enumerate(representatives):
        workspace = tmp_path / str(index)
        workspace.mkdir()
        for path, content in task["fixtures"].items():
            file = workspace / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content, encoding="utf-8")
        observed = asyncio.run(
            execute_module_task(
                execution_task(task),
                config={"nanobot_root": str(source)},
                workspace=workspace,
            )
        )
        assert observed["status"] == "completed", observed
        assert observed["execution_kind"] == "real_module"
        assert observed["evidence_complete"] is True
        assert observed["usage"] == {}
        assert observed["before_files"] == task["fixtures"]
        assert observed["runtime_identity"]["model"] is None
        assert len(observed["turns"]) == 1
        events = [e for e in observed["events"] if e["type"] == "tool"]
        assert len(events) == len(task["module_calls"])
        for event in events:
            assert (
                event["before_files"] is not None and event["after_files"] is not None
            )
            assert event["tool_schema"]["type"] == "object"
            assert event["parent_id"] in {
                e["id"] for e in observed["events"] if e["type"] == "turn"
            }
            assert isinstance(event["is_error"], bool)
        for check in task["oracle"]["module_results"]:
            event = events[check["call"] - 1]
            assert event["is_error"] == check["error"], (task["id"], event)
            assert all(text in event["output"] for text in check["output_contains"]), (
                task["id"],
                event,
            )
        for path, content in task["oracle"]["expected_files"].items():
            assert observed["final_files"].get(path) == content, task["id"]
