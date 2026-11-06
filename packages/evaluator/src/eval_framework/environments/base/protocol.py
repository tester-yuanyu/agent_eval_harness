"""新 Harness 的领域环境契约；不依赖执行框架或 Agent SDK。"""

from typing import Any, Protocol


class Environment(Protocol):
    def tool_schemas(self) -> list[dict[str, Any]]: ...
    async def reset(self, initial_state: dict[str, Any]) -> None: ...
    async def step(self, name: str, arguments: dict[str, Any]) -> str: ...
    async def snapshot(self) -> dict[str, Any]: ...
    async def teardown(self) -> None: ...


class EnvironmentFailure(RuntimeError):
    """Infrastructure failures must not be presented as model argument errors."""


class ToolExecutionError(ValueError):
    """Expected domain error, safe to feed back to the agent for recovery."""
