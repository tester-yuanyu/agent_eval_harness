"""Environment 公共 API；新路径使用 SandboxFilesEnvironment。"""

from .base import Environment, EnvironmentFailure, ToolExecutionError
from .file_tools import FileToolsEnvironment

__all__ = [
    "Environment",
    "EnvironmentFailure",
    "ToolExecutionError",
    "FileToolsEnvironment",
    "AsyncFileToolsEnvironment",
    "SandboxFilesEnvironment",
    "InspectFileToolsEnvironment",
]


def __getattr__(name: str):
    if name in {"SandboxFilesEnvironment", "AsyncFileToolsEnvironment"}:
        from . import file_tools

        return getattr(file_tools, name)
    if name == "InspectFileToolsEnvironment":
        from .inspect_file_tools import InspectFileToolsEnvironment

        return InspectFileToolsEnvironment
    raise AttributeError(name)
