"""Optional nanobot components without native runtime process-global setup.

The bounded file-task profile uses upstream ContextBuilder and argument parsing.
Memory, skills, plugins, personal bootstrap and native tool execution are disabled.
Only the subprocess runtime represents the full native AgentLoop.
"""

from __future__ import annotations

import hashlib
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from inspect_ai.model import get_model

from ...core.session_state import SessionState
from .base import AgentAction

PROFILE = "nanobot-context-v1"


def source_root(config: dict[str, Any]) -> Path:
    spec = find_spec("nanobot")
    if spec is None or spec.origin is None:
        raise RuntimeError(
            "nanobot_component requires optional nanobot in the evaluator process "
            "environment; install the selected nanobot checkout before launching"
        )
    root = Path(spec.origin).resolve().parent
    if configured := config.get("nanobot_root"):
        if (Path(configured).expanduser().resolve() / "nanobot") != root:
            raise ValueError("nanobot_root does not match the installed/loaded nanobot")
    return root


def component_sources(config: dict[str, Any]) -> dict[str, Path]:
    root = source_root(config)
    # Include imported helpers and template includes, not just context.py.
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in {".py", ".md"}
    }


def component_identity(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": PROFILE,
        "sources": {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in component_sources(config).items()
        },
        "memory": False,
        "skills": False,
        "native_tools": False,
    }


class _DisabledSkills:
    """Instance dependency, never a mutation of nanobot's shared plugin registry."""

    def get_always_skills(self) -> list[str]:
        return []

    def build_skills_summary(self, *, exclude: set[str]) -> str:
        return ""

    def build_explicit_skill_runtime_context(self, message: str) -> None:
        return None


class NanobotComponentAdapter:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        source_root(config or {})
        try:
            context_type = import_module("nanobot.agent.context").ContextBuilder
            self._parse_arguments = import_module(
                "nanobot.providers.base"
            ).parse_tool_arguments
            render = import_module("nanobot.utils.prompt_templates").render_template
        except ImportError as exc:
            raise RuntimeError(
                "nanobot_component optional dependencies are incomplete"
            ) from exc

        class IsolatedContext(context_type):
            def _get_identity(self, channel=None, workspace=None):
                # Stable logical paths: task files are in Inspect's sandbox, not
                # this adapter's host-side private MemoryStore directory.
                return render(
                    "agent/identity.md",
                    workspace_path="/workspace",
                    agent_workspace_path="/workspace",
                    runtime="Inspect-managed file tools",
                    platform_policy="",
                    channel="",
                )

            def _load_bootstrap_files(self, workspace=None):
                return ""

        self._private = TemporaryDirectory(prefix="nanobot-component-")
        self.workspace = Path(self._private.name)
        try:
            self._context = IsolatedContext(self.workspace)
            self._context.skills = _DisabledSkills()
        except BaseException:
            self._private.cleanup()
            raise

    def prepare_prompt(self, public_prompt: str) -> tuple[str, dict[str, Any]]:
        native = self._context.build_system_prompt(
            include_memory=False,
            include_memory_recent_history=False,
        )
        prompt = native + "\n\n" + public_prompt
        return prompt, {
            "profile": PROFILE,
            "native_prompt_sha256": hashlib.sha256(native.encode()).hexdigest(),
            "rendered_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        }

    async def step(self, state: SessionState) -> AgentAction:
        # Reuse native user-content construction, with no plugin or media IO.
        # State is a sample-local copy provided by the loop.
        for message in state.messages:
            if message.role == "user":
                message.content = self._context.build_current_message(message.text)[
                    "content"
                ]
        output = await get_model().generate(input=state.messages, tools=state.tools)
        if not output.choices:
            raise RuntimeError("model returned no choices")
        message = output.message.model_copy(deep=True)
        for call in message.tool_calls or []:
            # Inspect owns wire parsing; retain its parse_error and pass parsed
            # arguments through nanobot's native normalization without coercion.
            arguments = self._parse_arguments(call.arguments)
            if not isinstance(arguments, dict):
                call.parse_error = (
                    call.parse_error or "tool arguments must be an object"
                )
            else:
                call.arguments = arguments
        return AgentAction(message, output.stop_reason, output)

    async def close(self) -> None:
        self._private.cleanup()
