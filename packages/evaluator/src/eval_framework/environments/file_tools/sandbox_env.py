"""新 Harness 的文件环境；所有文件操作通过 Inspect sandbox 执行。"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from inspect_ai.util import LimitExceededError, sandbox

from ..base.protocol import EnvironmentFailure, ToolExecutionError
from .offline_env import validate_fixtures
from .payload import build_worker_script as build_worker_script
from .schemas import file_tool_schemas, validate_call


class SandboxFilesEnvironment:
    """每个 sample 一个实例；Inspect local backend 不提供 OS 级隔离。"""

    def __init__(self, allowed_tools: list[str]) -> None:
        self.schemas = file_tool_schemas(allowed_tools)
        self.script = build_worker_script()

    def tool_schemas(self) -> list[dict[str, Any]]:
        return deepcopy(self.schemas)

    async def _request(self, request: dict[str, Any]) -> Any:
        try:
            result = await sandbox().exec(
                ["python3", "-I", "-c", self.script],
                input=json.dumps(request),
                timeout=30,
                timeout_retry=False,
            )
            if not result.success:
                raise EnvironmentFailure(
                    result.stderr or "sandbox file operation failed"
                )
            response = json.loads(result.stdout)
            if not isinstance(response, dict):
                raise EnvironmentFailure("invalid file worker response")
            if set(response) == {"tool_error"} and isinstance(
                response["tool_error"], str
            ):
                raise ToolExecutionError(response["tool_error"])
            if set(response) != {"value"}:
                raise EnvironmentFailure("invalid file worker response")
            return response["value"]
        except (ToolExecutionError, EnvironmentFailure, LimitExceededError):
            raise
        except Exception as exc:
            raise EnvironmentFailure(str(exc)) from exc

    async def reset(self, initial_state: dict[str, Any]) -> None:
        try:
            if not isinstance(initial_state, dict) or set(initial_state) != {"files"}:
                raise ValueError("file environment expects initial_state.files")
            files = validate_fixtures(initial_state["files"])
            actual = await self._request({"operation": "reset", "files": files})
            if actual != files:
                raise EnvironmentFailure(
                    "initial workspace differs from declared fixtures"
                )
        except ValueError as exc:
            raise EnvironmentFailure(str(exc)) from exc

    async def step(self, name: str, arguments: dict[str, Any]) -> str:
        validate_call(self.schemas, name, arguments)
        result = await self._request({"operation": name, "arguments": arguments})
        if not isinstance(result, str):
            raise EnvironmentFailure("invalid file tool result")
        return result

    async def snapshot(self) -> dict[str, str]:
        try:
            result = await self._request({"operation": "snapshot"})
            if not isinstance(result, dict) or any(
                not isinstance(k, str) or not isinstance(v, str)
                for k, v in result.items()
            ):
                raise EnvironmentFailure("invalid file snapshot")
            return result
        except ToolExecutionError as exc:
            raise EnvironmentFailure(str(exc)) from exc

    async def teardown(self) -> None:
        # Inspect 负责清理沙箱，不能在日志持久化前删除证据。
        pass
