"""Single nanobot provider call against genuine tool schemas, with no tool execution."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from nanobot_runtime import snapshot_files  # noqa: E402
from nanobot_worker import Journal, strict_tools  # noqa: E402

SYSTEM = (
    "You are selecting the next action at an isolated tool-decision boundary. "
    "Use only the supplied public context and available tool schemas. "
    "Return at most one tool call if the request calls for a concrete file operation; "
    "otherwise answer or ask for clarification without a tool call. "
    "Use the relative paths supplied by the user. Do not claim a tool has executed. "
    "There is no subsequent tool result in this decision round."
)


async def run_decision_task(
    payload: dict[str, Any], *, provider: Any = None
) -> dict[str, Any]:
    from loguru import logger
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.providers.openai_compat_provider import OpenAICompatProvider

    logger.remove()
    task, config = payload["task"], payload["config"]
    workspace = Path(payload["workspace"]).resolve(strict=True)
    private = Path(payload["runtime_dir"]).resolve(strict=True)
    secret = os.environ.get(config.get("api_key_env", "DEEPSEEK_API_KEY"), "")
    kind = "offline_decision_test" if provider is not None else "real_model_decision"
    journal = Journal(private / "events.jsonl", secret)
    registry = ToolRegistry()
    for tool in strict_tools(workspace, task["allowed_tools"]):
        registry.register(tool)
    messages = [{"role": "system", "content": SYSTEM}]
    context = task.get("decision_context", "")
    if context:
        messages.append(
            {
                "role": "user",
                "content": "Public context supplied by the user:\n" + context,
            }
        )
    messages.append({"role": "user", "content": task["prompt"]})

    class MeasuredProvider(OpenAICompatProvider):
        def _parse(self, response: Any) -> Any:
            self.response_model = getattr(response, "model", None)
            return super()._parse(response)

    if provider is None:
        provider = MeasuredProvider(
            api_key=secret,
            api_base=config.get("base_url"),
            default_model=config["model"],
            api_type="chat_completions",
            extra_body=config.get("extra_body"),
        )
    settings = {
        "model": config["model"],
        "tools": registry.get_definitions(),
        "temperature": float(config.get("temperature", 0)),
        "max_tokens": int(config.get("max_tokens", 2048)),
        "tool_choice": "auto",
    }
    turn = journal.start("turn", "single-model-decision", task["prompt"], turn=1)
    journal.turn_id = turn["id"]
    event = journal.start(
        "generation", config["model"], {"messages": messages, **settings}, turn=1
    )
    errors = []
    decision = None
    output = ""
    try:
        response = await provider.chat(messages, **settings)
        decision = {
            "content": response.content,
            "tool_calls": [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in response.tool_calls
            ],
        }
        generated = {**decision, "finish_reason": response.finish_reason}
        error = (
            response.content or response.error_kind or "provider error"
            if response.finish_reason == "error"
            else None
        )
        journal.finish(
            event,
            generated,
            usage=dict(response.usage),
            model=config["model"],
            response_model=getattr(provider, "response_model", None),
            error=error,
        )
        if error:
            errors.append(
                {
                    "kind": "provider",
                    "code": response.error_kind or "provider_error",
                    "message": str(error),
                }
            )
        output = response.content or json.dumps(
            decision["tool_calls"], ensure_ascii=False
        )
    except Exception as exc:
        journal.finish(event, None, error=type(exc).__name__)
        errors.append(
            {"kind": "provider", "code": type(exc).__name__, "message": str(exc)}
        )
    final = snapshot_files(workspace)
    journal.finish(turn, output, snapshot=final)
    return {
        "status": "error" if errors else "completed",
        "execution_kind": kind,
        "errors": errors,
        "events": journal.events,
        "decision": decision,
        "turns": [{"input": task["prompt"], "output": output, "snapshot": final}],
        "final_files": final,
        "usage": dict(event.get("usage", {})),
    }


if __name__ == "__main__":
    print(
        json.dumps(
            asyncio.run(run_decision_task(json.load(sys.stdin))), ensure_ascii=False
        )
    )
