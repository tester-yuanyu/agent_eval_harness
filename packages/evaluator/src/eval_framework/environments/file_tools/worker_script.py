"""Standard-library file operations executed by Inspect inside its sandbox.

This is an environment operation, not an Agent worker or a second trace store.
The program is passed as code to sandbox.exec; task values enter only as JSON.
"""

from __future__ import annotations

import json
import sys
from functools import partial
from pathlib import Path

if __package__:
    from .._fs_utils import safe_path as _safe_path
    from .._fs_utils import snapshot_files
else:
    from _environment_fs_utils import safe_path as _safe_path
    from _environment_fs_utils import snapshot_files

# 策略保持沙箱历史行为：相对路径，不新增文件大小限制。
safe_path = partial(_safe_path, relative_only=True)
snapshot = partial(snapshot_files, relative_only=True, max_file_bytes=None)


def execute(request: dict) -> object:
    root = Path("workspace").absolute()
    if root.is_symlink():
        raise ValueError("workspace must not be a symbolic link")
    root.mkdir(exist_ok=True)
    operation = request["operation"]
    if operation == "reset":
        # Inspect provisions a fresh sample directory. Never delete pre-existing
        # content here; compare it to declared fixtures in the caller instead.
        for name, content in request["files"].items():
            path = safe_path(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="")
        return snapshot(root)
    if operation == "snapshot":
        return snapshot(root)
    args = request["arguments"]
    path = safe_path(root, args.get("path", "."))
    if operation == "read_file":
        with path.open(encoding="utf-8", newline="") as handle:
            return handle.read()
    if operation == "write_file":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8", newline="")
        return "File written"
    if operation == "edit_file":
        with path.open(encoding="utf-8", newline="") as handle:
            content = handle.read()
        old = args["old_text"]
        if not old or content.count(old) != 1:
            raise ValueError("edit requires one nonempty matching occurrence")
        path.write_text(
            content.replace(old, args["new_text"], 1), encoding="utf-8", newline=""
        )
        return "File edited"
    if operation == "list_dir":
        entries = sorted(path.iterdir())
        for entry in entries:
            safe_path(root, entry.relative_to(root).as_posix())
        return "\n".join(entry.name for entry in entries)
    raise ValueError("unknown operation")


def main() -> None:
    try:
        value = execute(json.load(sys.stdin))
        result = {"value": value}
    except (
        ValueError,
        FileNotFoundError,
        IsADirectoryError,
        NotADirectoryError,
    ) as exc:
        result = {"tool_error": str(exc)}
    # Other OSErrors (ENOSPC, EIO, permissions) are infrastructure failures.
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
