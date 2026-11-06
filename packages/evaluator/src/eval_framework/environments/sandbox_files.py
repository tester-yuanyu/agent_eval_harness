"""Framework-owned file tools; all filesystem effects use Inspect sandbox APIs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from inspect_ai.util import sandbox

from ..harness.core.tool_router import EnvironmentFailure, ToolExecutionError
from .file_tools import validate_fixtures


def _schema(name: str, description: str, fields: tuple[str, ...], *, optional=False):
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {field: {"type": "string"} for field in fields},
            "required": [] if optional else list(fields),
        },
    }


class SandboxFilesEnvironment:
    """One instance per sample; local sandbox is not OS-level isolation."""

    def __init__(self, allowed_tools: list[str]) -> None:
        schemas = [
            _schema("read_file", "Read a UTF-8 file", ("path",)),
            _schema("write_file", "Write a UTF-8 file", ("path", "content")),
            _schema(
                "edit_file",
                "Replace one matching occurrence",
                ("path", "old_text", "new_text"),
            ),
            _schema(
                "list_dir", "List entries in a directory", ("path",), optional=True
            ),
        ]
        known = {s["name"] for s in schemas}
        if not set(allowed_tools) <= known:
            raise ValueError("unknown file tool in task policy")
        self.schemas = [s for s in schemas if s["name"] in allowed_tools]
        self.script = Path(__file__).with_name("sandbox_files_worker.py").read_text()

    def tool_schemas(self) -> list[dict[str, Any]]:
        from copy import deepcopy

        return deepcopy(self.schemas)

    async def _request(self, request: dict) -> Any:
        result = await sandbox().exec(
            ["python3", "-I", "-c", self.script],
            input=json.dumps(request),
            timeout=30,
            timeout_retry=False,
        )
        if not result.success:
            raise EnvironmentFailure(result.stderr or "sandbox file operation failed")
        response = json.loads(result.stdout)
        if "tool_error" in response:
            raise ToolExecutionError(response["tool_error"])
        return response["value"]

    async def reset(self, initial_state: dict[str, Any]) -> None:
        if set(initial_state) != {"files"}:
            raise ValueError("file environment expects initial_state.files")
        files = validate_fixtures(initial_state["files"])
        actual = await self._request({"operation": "reset", "files": files})
        if actual != files:
            raise EnvironmentFailure("initial workspace differs from declared fixtures")

    async def step(self, name: str, arguments: dict[str, Any]) -> str:
        return await self._request({"operation": name, "arguments": arguments})

    async def snapshot(self) -> dict[str, str]:
        return await self._request({"operation": "snapshot"})

    async def teardown(self) -> None:
        # Inspect owns and removes the sandbox; no host filesystem mutation.
        pass
