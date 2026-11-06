"""文件路径与快照的唯一实现；仅依赖标准库，可装配到独立 worker。"""

from __future__ import annotations

from pathlib import Path, PurePosixPath


def safe_path(workspace: Path, value: str, *, relative_only: bool = False) -> Path:
    """保留旧本地策略；relative_only 保留沙箱只接受相对路径的策略。"""
    if relative_only:
        requested = PurePosixPath(value)
        if requested.is_absolute() or ".." in requested.parts or "\0" in value:
            raise ValueError("path must be relative and inside the workspace")
        root, relative = workspace, requested
    else:
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
            message = (
                "symbolic links are not allowed"
                if relative_only
                else "symbolic links are forbidden in task workspaces"
            )
            raise ValueError(message)
    if not relative_only and not candidate.resolve(strict=False).is_relative_to(root):
        raise ValueError("resolved path is outside the task workspace")
    return current if relative_only else candidate


def snapshot_files(
    workspace: Path,
    *,
    relative_only: bool = False,
    max_file_bytes: int | None = 2_000_000,
) -> dict[str, str]:
    """独立读取 UTF-8 文件证据，保持顺序和原始换行。"""
    result: dict[str, str] = {}
    for path in sorted(workspace.rglob("*")):
        value = path.relative_to(workspace).as_posix() if relative_only else str(path)
        safe_path(workspace, value, relative_only=relative_only)
        if path.is_file():
            if max_file_bytes is not None and path.stat().st_size > max_file_bytes:
                raise ValueError("task file exceeds the 2 MB evidence limit")
            with path.open(encoding="utf-8", newline="") as stream:
                result[path.relative_to(workspace).as_posix()] = stream.read()
    return result
