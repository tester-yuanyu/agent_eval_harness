"""Real nanobot module subprocess; never imports or constructs an LLM provider."""

from __future__ import annotations

import asyncio
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from nanobot_runtime import snapshot_files  # noqa: E402
from nanobot_worker import FileEvidence, strict_tools  # noqa: E402


async def run_module_task(payload: dict[str, Any]) -> dict[str, Any]:
    from loguru import logger
    from nanobot.agent.tools.registry import ToolRegistry, is_tool_error_result

    logger.remove()
    workspace = Path(payload["workspace"]).resolve(strict=True)
    task = payload["task"]
    registry = ToolRegistry()
    for tool in strict_tools(workspace, task["allowed_tools"]):
        registry.register(tool)
    journal = FileEvidence(Path(payload["runtime_dir"]) / "events.jsonl")
    turn = journal.start("turn", "module-boundary", task["prompt"], turn=1)
    journal.turn_id = turn["id"]
    outputs = []
    for index, call in enumerate(task["module_calls"], 1):
        name, arguments = call["name"], deepcopy(call["arguments"])
        tool = registry.get(name)
        event = journal.start(
            "tool",
            name,
            arguments,
            turn=1,
            module_call=index,
            tool_call_id=f"module-call-{index}",
            tool_schema=deepcopy(tool.parameters) if tool else {},
            before_files=snapshot_files(workspace),
            before_snapshot_errors=[],
            execution_started=False,
        )
        _, normalized, error = registry.prepare_call(name, arguments)
        event["execution_started"] = error is None
        event["normalized_arguments"] = deepcopy(normalized)
        event["normalized_input"] = deepcopy(normalized)
        journal.write(event)
        output = await registry.execute(name, arguments)
        is_error = is_tool_error_result(output)
        journal.finish(
            event,
            str(output),
            after_files=snapshot_files(workspace),
            after_snapshot_errors=[],
            is_error=is_error,
            tool_error=is_error,
            error=str(output) if is_error else None,
        )
        outputs.append(str(output))
    final = snapshot_files(workspace)
    response = "\n".join(outputs)
    journal.finish(turn, response, snapshot=final)
    return {
        "status": "completed",
        "execution_kind": "real_module",
        "errors": [],
        "turns": [{"input": task["prompt"], "output": response, "snapshot": final}],
        "events": journal.events,
        "final_files": final,
        "usage": {},
    }


if __name__ == "__main__":
    print(
        json.dumps(
            asyncio.run(run_module_task(json.load(sys.stdin))), ensure_ascii=False
        )
    )
