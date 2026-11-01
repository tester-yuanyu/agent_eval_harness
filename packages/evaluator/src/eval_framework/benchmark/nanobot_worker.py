"""Private subprocess entrypoint using nanobot's real SDK and AgentLoop."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

# The worker runs directly under nanobot's interpreter, without installing the
# evaluator and its independent dependency graph in that environment.
sys.path.insert(0, str(Path(__file__).parent))
from nanobot_runtime import (  # noqa: E402
    TOKENIZER_SHA256,
    TOKENIZER_URL,
    safe_path,
    snapshot_files,
    utc_now,
)


def public_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep API conversation data; omit provider-private continuation/reasoning."""
    keys = {"role", "content", "tool_calls", "tool_call_id", "name"}
    return [
        {key: deepcopy(value) for key, value in message.items() if key in keys}
        for message in messages
    ]


class Journal:
    def __init__(self, path: Path, secret: str = "") -> None:
        self.path = path
        self.secret = secret
        self.events: list[dict[str, Any]] = []
        self.turn_id: str | None = None
        self.turn_index: int | None = None

    def write(self, event: dict[str, Any]) -> None:
        text = json.dumps(event, ensure_ascii=False, default=str)
        if self.secret:
            text = text.replace(self.secret, "[REDACTED]")
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(text + "\n")
            stream.flush()

    def start(
        self, kind: str, name: str, input_value: Any, **extra: Any
    ) -> dict[str, Any]:
        event = {
            "id": uuid4().hex,
            "type": kind,
            "name": name,
            "start_time": utc_now(),
            "end_time": None,
            "input": deepcopy(input_value),
            "output": None,
            "usage": {},
            "parent_id": self.turn_id,
            "turn": self.turn_index,
            **extra,
        }
        self.events.append(event)
        self.write(event)
        return event

    def finish(self, event: dict[str, Any], output: Any, **extra: Any) -> None:
        event.update(end_time=utc_now(), output=deepcopy(output), **extra)
        self.write(event)


def strict_tools(workspace: Path, allowed: list[str]) -> list[Any]:
    from nanobot.agent.tools.base import ToolResult
    from nanobot.agent.tools.filesystem import (
        EditFileTool,
        ListDirTool,
        ReadFileTool,
        WriteFileTool,
    )

    class StrictPath:
        async def execute(self, **kwargs: Any) -> Any:
            try:
                value = kwargs.get("path")
                if value is None and self.name == "list_dir":
                    value = "."
                if value is None:
                    return ToolResult.error("Error: path is required")
                path = safe_path(workspace, str(value))
                # Absolutizing also prevents nanobot's missing-file fallback to
                # bundled skills/<name> from reading outside the benchmark.
                kwargs["path"] = str(path)
                return await super().execute(**kwargs)
            except (OSError, ValueError) as exc:
                return ToolResult.error(f"Error: workspace policy: {exc}")

        def _resolve_read(self, path: str) -> Path:
            return safe_path(workspace, path)

        def _resolve_write(self, path: str) -> Path:
            return safe_path(workspace, path)

    classes = {
        "read_file": ReadFileTool,
        "write_file": WriteFileTool,
        "edit_file": EditFileTool,
        "list_dir": ListDirTool,
    }
    result = []
    for name in allowed:
        tool_class = type(
            f"Benchmark{classes[name].__name__}", (StrictPath, classes[name]), {}
        )
        result.append(
            tool_class(
                workspace=workspace, allowed_dir=workspace, restrict_to_workspace=True
            )
        )
    return result


async def run_task(payload: dict[str, Any], *, provider: Any = None) -> dict[str, Any]:
    """Run an execution projection; dependency injection is for offline tests."""
    from loguru import logger

    logger.remove()
    from nanobot.agent.hook import AgentHook
    from nanobot.agent.loop import AgentLoop
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.bus.queue import MessageBus
    from nanobot.config.loader import set_config_path
    from nanobot.config.schema import ToolsConfig
    from nanobot.nanobot import Nanobot
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.openai_compat_provider import OpenAICompatProvider
    from nanobot.security.workspace_access import WorkspaceScopeResolver
    from nanobot.session.manager import JsonlSessionStore, SessionManager

    task, config = payload["task"], payload["config"]
    workspace = Path(payload["workspace"]).resolve(strict=True)
    private = Path(payload["runtime_dir"]).resolve(strict=True)
    private_workspace = private / "agent"
    private_workspace.mkdir(exist_ok=True)
    set_config_path(private / "config.json")
    secret = os.environ.get(config.get("api_key_env", "DEEPSEEK_API_KEY"), "")
    journal = Journal(private / "events.jsonl", secret)
    if config.get("tokenizer_mode", "cl100k_base") == "byte_fallback":
        import nanobot.utils.helpers as helpers

        def byte_fallback() -> Any:
            raise RuntimeError("configured offline byte-count fallback")

        helpers._get_token_encoding = byte_fallback
    else:
        import hashlib
        import tempfile

        cache = Path(
            config.get("tokenizer_cache_dir")
            or Path(tempfile.gettempdir()) / "data-gym-cache"
        )
        tokenizer = cache / hashlib.sha1(TOKENIZER_URL.encode()).hexdigest()
        if (
            not tokenizer.exists()
            or hashlib.sha256(tokenizer.read_bytes()).hexdigest() != TOKENIZER_SHA256
        ):
            raise RuntimeError(
                "verified tokenizer cache missing; run prepare_tokenizer first "
                "or select byte_fallback"
            )
        os.environ["TIKTOKEN_CACHE_DIR"] = str(cache)

    class InstrumentedProvider(OpenAICompatProvider):
        def _parse(self, response: Any) -> Any:
            self.response_model = getattr(response, "model", None)
            return super()._parse(response)

        async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
            public = {
                key: deepcopy(value)
                for key, value in kwargs.items()
                if key
                in {
                    "tools",
                    "model",
                    "max_tokens",
                    "temperature",
                    "reasoning_effort",
                    "tool_choice",
                }
            }
            event = journal.start(
                "generation",
                str(kwargs.get("model") or config["model"]),
                {"messages": public_messages(messages), **public},
            )
            try:
                response = await super().chat(messages, **kwargs)
                output = {
                    "content": response.content,
                    "finish_reason": response.finish_reason,
                    "tool_calls": [
                        {"id": call.id, "name": call.name, "arguments": call.arguments}
                        for call in response.tool_calls
                    ],
                }
                extra: dict[str, Any] = {
                    "usage": dict(response.usage),
                    "model": config["model"],
                    "response_model": getattr(self, "response_model", None),
                }
                if response.finish_reason == "error":
                    extra["error"] = (
                        response.content or response.error_kind or "provider error"
                    )
                journal.finish(event, output, **extra)
                return response
            except BaseException as exc:
                journal.finish(event, None, error=type(exc).__name__)
                raise

    class EvidenceHook(AgentHook):
        def __init__(self) -> None:
            super().__init__(reraise=True)
            self.calls: dict[str, dict[str, Any]] = {}

        def snapshot(self, prefix: str) -> dict[str, Any]:
            try:
                return {f"{prefix}_files": snapshot_files(workspace)}
            except (OSError, ValueError, UnicodeError) as exc:
                # Preserve the failed measurement. A later final snapshot must
                # never silently fill in the missing intermediate state.
                return {
                    f"{prefix}_files": None,
                    f"{prefix}_snapshot_errors": [
                        {"code": type(exc).__name__, "message": str(exc)}
                    ],
                }

        def normalized_input(self, params: Any) -> Any:
            normalized = deepcopy(params)
            if isinstance(normalized, dict) and isinstance(normalized.get("path"), str):
                try:
                    normalized["path"] = (
                        safe_path(workspace, normalized["path"])
                        .relative_to(workspace.resolve())
                        .as_posix()
                    )
                except (OSError, ValueError):
                    pass
            return normalized

        async def before_execute_tool(
            self, context: Any, tool_call: Any, tool: Any, params: Any
        ) -> None:
            self.calls[tool_call.id] = journal.start(
                "tool",
                tool_call.name,
                params,
                tool_call_id=tool_call.id,
                execution_started=True,
                tool_schema=deepcopy(tool.parameters),
                normalized_input=self.normalized_input(params),
                snapshot_timing="immediately_before_and_after_execution",
                **self.snapshot("before"),
            )

        async def after_execute_tool(
            self, context: Any, tool_call: Any, tool: Any, params: Any, result: Any
        ) -> None:
            is_error = bool(getattr(result, "is_error", False))
            journal.finish(
                self.calls.pop(tool_call.id),
                str(result),
                is_error=is_error,
                tool_error=is_error,
                **self.snapshot("after"),
            )

        async def on_execute_tool_error(
            self, context: Any, tool_call: Any, tool: Any, params: Any, error: Any
        ) -> None:
            event = self.calls.pop(tool_call.id, None)
            if event is None:
                event = journal.start(
                    "tool",
                    tool_call.name,
                    params,
                    tool_call_id=tool_call.id,
                    tool_schema=deepcopy(tool.parameters) if tool else None,
                    normalized_input=self.normalized_input(params),
                    before_files=None,
                )
            journal.finish(
                event,
                str(error),
                error=str(error),
                is_error=True,
                tool_error=True,
                **self.snapshot("after"),
            )

        async def after_iteration(self, context: Any) -> None:
            # nanobot's pre-validation rejection bypasses tool execution hooks.
            # Preserve those failed attempts without claiming a tool ran.
            captured = {
                event.get("tool_call_id")
                for event in journal.events
                if event["type"] == "tool"
            }
            for call, detail in zip(
                context.tool_calls, context.tool_events, strict=False
            ):
                if call.id not in captured:
                    tool = registry.get(call.name)
                    event = journal.start(
                        "tool",
                        call.name,
                        call.arguments,
                        tool_call_id=call.id,
                        execution_started=False,
                        tool_schema=deepcopy(tool.parameters) if tool else None,
                        normalized_input=self.normalized_input(call.arguments),
                        snapshot_timing="after_iteration_rejection_record",
                        before_files=None,
                    )
                    journal.finish(
                        event,
                        detail.get("detail"),
                        error=detail.get("detail"),
                        is_error=True,
                        tool_error=True,
                        **self.snapshot("after"),
                    )

    class FileOnlyAgentLoop(AgentLoop):
        def _register_default_tools(self, **_kwargs: Any) -> None:
            # Deliberately disable plugin discovery, MCP, shell, channels and
            # messaging before any default tool can be instantiated.
            return None

    if provider is None:
        provider = InstrumentedProvider(
            api_key=secret,
            api_base=config.get("base_url"),
            default_model=config["model"],
            api_type="chat_completions",
            extra_body=config.get("extra_body"),
        )
    provider.generation = GenerationSettings(
        temperature=float(config.get("temperature", 0)),
        max_tokens=int(config.get("max_tokens", 2048)),
    )
    registry = ToolRegistry()
    allowed = task.get(
        "allowed_tools", ["read_file", "write_file", "edit_file", "list_dir"]
    )
    for tool in strict_tools(workspace, allowed):
        registry.register(tool)
    session_store = JsonlSessionStore(
        private_workspace, sessions_root=private / "sessions"
    )
    # Disable the historical global-session fallback in this unique instance.
    session_store.legacy_sessions_dir = private / "legacy-sessions"
    sessions = SessionManager(
        private_workspace, store=session_store, sessions_root=private / "sessions"
    )
    loop = FileOnlyAgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=private_workspace,
        model=config["model"],
        max_iterations=min(
            int(task.get("max_steps", 12)), int(config.get("max_steps", 12))
        ),
        context_window_tokens=100_000,
        max_tool_result_chars=64_000,
        fail_on_tool_error=False,
        restrict_to_workspace=True,
        session_manager=sessions,
        tool_registry=registry,
        session_ttl_minutes=0,
        idle_compact_check_interval_seconds=0,
        disabled_skills=[
            path.name
            for path in (Path(config["nanobot_root"]) / "nanobot" / "skills").iterdir()
            if path.is_dir()
        ],
        tools_config=ToolsConfig(restrict_to_workspace=True),
    )
    # The SDK's own memory/session files stay private. Its turn workspace is
    # the fixture directory, so model-facing paths and real tools agree.
    loop.workspace_scopes = WorkspaceScopeResolver(
        default_workspace=workspace, default_restrict_to_workspace=True
    )
    bot = Nanobot(loop)
    turns, errors = [], []
    status, stop_reason = "completed", "stop"
    prompts = [task["prompt"], *task.get("followups", [])]
    if not all(isinstance(prompt, str) for prompt in prompts):
        raise ValueError("followups must be user-message strings")
    try:
        for index, prompt in enumerate(prompts):
            journal.turn_index = index + 1
            event = journal.start("turn", f"turn-{index + 1}", prompt)
            journal.turn_id = event["id"]
            instruction = config.get("instructions", "")
            message = (
                f"{instruction}\n\n{prompt}" if instruction and index == 0 else prompt
            )
            response = await bot.run(
                message,
                session_key=f"benchmark:{task['id']}",
                channel="cli",
                chat_id="benchmark",
                ephemeral=False,
                hooks=[EvidenceHook()],
            )
            snapshot = snapshot_files(workspace)
            turn = {
                "input": prompt,
                "output": response.content,
                "snapshot": snapshot,
                "stop_reason": response.stop_reason,
                "usage": dict(response.usage),
            }
            turns.append(turn)
            journal.finish(
                event,
                response.content,
                snapshot=snapshot,
                usage=dict(response.usage),
                stop_reason=response.stop_reason,
            )
            stop_reason = response.stop_reason or "stop"
            if response.error:
                provider_errors = [
                    item
                    for item in journal.events
                    if item["type"] == "generation" and item.get("error")
                ]
                kind = "provider" if provider_errors else "agent"
                errors.append(
                    {"kind": kind, "code": "run_error", "message": response.error}
                )
                if kind == "provider":
                    status = "error"
                    break
            if "max" in stop_reason or "budget" in stop_reason:
                stop_reason = "max_steps"
                break
            journal.turn_id = None
    finally:
        await loop.aclose()
    return {
        "status": status,
        "turns": turns,
        "stop_reason": stop_reason,
        "errors": errors,
    }


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        result = asyncio.run(run_task(payload))
    except Exception as exc:
        result = {
            "status": "error",
            "turns": [],
            "errors": [
                {
                    "kind": "environment",
                    "code": type(exc).__name__,
                    "message": str(exc),
                },
            ],
        }
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
