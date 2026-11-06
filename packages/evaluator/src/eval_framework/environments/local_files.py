"""独立本地文件取证与路径约束；仅依赖标准库，可复制到 worker。"""

from __future__ import annotations

from pathlib import Path


def safe_path(workspace: Path, value: str) -> Path:
    """Reject traversal and every symlink component before touching a file."""
    root = workspace.resolve(strict=True)
    requested = Path(value)
    if ".." in requested.parts:
        raise ValueError("parent traversal is forbidden")
    candidate = requested if requested.is_absolute() else root / requested
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("path is outside the task workspace") from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("symbolic links are forbidden in task workspaces")
    if not candidate.resolve(strict=False).is_relative_to(root):
        raise ValueError("resolved path is outside the task workspace")
    return candidate


def snapshot_files(workspace: Path) -> dict[str, str]:
    """Read the task state independently of the Agent's reported answer."""
    result: dict[str, str] = {}
    for path in sorted(workspace.rglob("*")):
        safe_path(workspace, str(path))
        if path.is_file():
            if path.stat().st_size > 2_000_000:
                raise ValueError("task file exceeds the 2 MB evidence limit")
            with path.open(encoding="utf-8", newline="") as stream:
                result[path.relative_to(workspace).as_posix()] = stream.read()
    return result
