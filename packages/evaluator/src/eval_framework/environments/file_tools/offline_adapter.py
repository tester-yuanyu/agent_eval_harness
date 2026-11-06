"""同步离线环境到新异步契约的适配；生产使用 Inspect 沙箱。"""

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..base.protocol import EnvironmentFailure, ToolExecutionError
from .offline_env import FileToolsEnvironment
from .schemas import file_tool_schemas, validate_call


class AsyncFileToolsEnvironment:
    """测试用异步门面，保留底层同步 API 和本地路径/快照策略。"""

    def __init__(self, allowed_tools: list[str], *, parent: Path | None = None) -> None:
        self._environment = FileToolsEnvironment(parent=parent)
        self._schemas = file_tool_schemas(allowed_tools)

    def tool_schemas(self) -> list[dict[str, Any]]:
        return deepcopy(self._schemas)

    async def reset(self, initial_state: dict[str, Any]) -> None:
        try:
            if not isinstance(initial_state, dict) or set(initial_state) != {"files"}:
                raise ValueError("file environment expects initial_state.files")
            self._environment.reset(initial_state["files"])
        except Exception as exc:
            raise EnvironmentFailure(str(exc)) from exc

    async def step(self, name: str, arguments: dict[str, Any]) -> str:
        validate_call(self._schemas, name, arguments)
        try:
            result = self._environment.step(
                {"name": name, "arguments": deepcopy(arguments)}
            )
            return "\n".join(result) if name == "list_dir" else result
        except (
            ValueError,
            FileNotFoundError,
            IsADirectoryError,
            NotADirectoryError,
        ) as exc:
            raise ToolExecutionError(str(exc)) from exc
        except Exception as exc:
            raise EnvironmentFailure(str(exc)) from exc

    async def snapshot(self) -> dict[str, str]:
        try:
            return self._environment.snapshot()
        except Exception as exc:
            raise EnvironmentFailure(str(exc)) from exc

    async def teardown(self) -> None:
        try:
            self._environment.teardown()
        except Exception as exc:
            raise EnvironmentFailure(str(exc)) from exc
