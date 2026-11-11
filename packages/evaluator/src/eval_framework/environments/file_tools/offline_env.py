"""Independent local file fixtures for framework-owned, offline execution."""

from __future__ import annotations

import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from .._fs_utils import safe_path, snapshot_files
from .schemas import TOOLS, file_tool_schemas


def validate_fixtures(initial_state: dict[str, str]) -> dict[str, str]:
    if not isinstance(initial_state, dict):
        raise ValueError("initial state must be a file-content mapping")
    for name, content in initial_state.items():
        if not isinstance(name, str) or not isinstance(content, str):
            raise ValueError("fixture names and contents must be text")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("fixture path must be inside the sample workspace")
    return dict(initial_state)


class FileToolsEnvironment:
    """Own a fresh temporary workspace per reset; this is not an OS sandbox.

    ``reset`` accepts a bare ``{relative_path: text}`` map. TaskSpec callers
    explicitly pass ``task.initial_state["files"]`` at this domain boundary.
    This synchronous API is retained for offline tests and legacy callers.
    The production Harness uses SandboxFilesEnvironment.
    """

    def __init__(self, *, parent: Path | None = None) -> None:
        self.parent = parent
        self._temporary: tempfile.TemporaryDirectory | None = None

    def tool_schemas(self) -> list[dict[str, Any]]:
        return file_tool_schemas([tool[0] for tool in TOOLS])

    @property
    def workspace(self) -> Path:
        if self._temporary is None:
            raise RuntimeError("reset the environment before use")
        return Path(self._temporary.name)

    def reset(self, initial_state: dict[str, str]) -> None:
        self.teardown()
        fixtures = validate_fixtures(initial_state)
        self._temporary = tempfile.TemporaryDirectory(
            prefix="harness-", dir=self.parent
        )
        try:
            for name, content in fixtures.items():
                path = safe_path(self.workspace, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8", newline="")
            self.snapshot()
        except BaseException:
            self.teardown()
            raise

    def step(self, action: dict[str, Any]) -> Any:
        name, arguments = action["name"], action["arguments"]
        path = safe_path(self.workspace, arguments.get("path", "."))
        if name == "read_file":
            with path.open(encoding="utf-8", newline="") as stream:
                return stream.read()
        if name == "write_file":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(arguments["content"], encoding="utf-8", newline="")
            return "File written"
        if name == "edit_file":
            with path.open(encoding="utf-8", newline="") as stream:
                content = stream.read()
            old = arguments["old_text"]
            if not old or content.count(old) != 1:
                raise ValueError("edit requires one nonempty matching occurrence")
            path.write_text(
                content.replace(old, arguments["new_text"], 1),
                encoding="utf-8",
                newline="",
            )
            return "File edited"
        if name == "list_dir":
            entries = sorted(path.iterdir())
            for entry in entries:
                safe_path(self.workspace, str(entry))
            return [entry.name for entry in entries]
        raise ValueError("unsupported file operation")

    def snapshot(self) -> dict[str, str]:
        return snapshot_files(self.workspace)

    def final_state(self) -> dict[str, str]:
        return self.snapshot()

    def teardown(self) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
