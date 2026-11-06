"""文件领域；同步 API 用于兼容，沙箱环境用于新 Harness。"""

from .._fs_utils import safe_path, snapshot_files
from .offline_env import FileToolsEnvironment, validate_fixtures

__all__ = [
    "FileToolsEnvironment",
    "AsyncFileToolsEnvironment",
    "SandboxFilesEnvironment",
    "validate_fixtures",
    "safe_path",
    "snapshot_files",
]


def __getattr__(name: str):
    if name == "SandboxFilesEnvironment":
        from .sandbox_env import SandboxFilesEnvironment

        return SandboxFilesEnvironment
    if name == "AsyncFileToolsEnvironment":
        from .offline_adapter import AsyncFileToolsEnvironment

        return AsyncFileToolsEnvironment
    raise AttributeError(name)
