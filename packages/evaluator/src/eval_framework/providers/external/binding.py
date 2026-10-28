"""Trusted runtime bindings and fixed external-adapter dispatch."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from ...schema_base import StrictModel

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CODE_SUFFIXES = {".cjs", ".js", ".mjs", ".py", ".sh"}


class RuntimeBinding(StrictModel):
    """Trusted local configuration kept separate from candidate datasets."""

    version: Literal["1.0"]
    agent_id: str = Field(min_length=1)
    adapter: Literal["static", "nanobot_local", "stdio"]
    agent_root: Path | None = None
    python: Path | None = None
    argv: list[str] | None = None
    env_names: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_output_bytes: int = Field(default=1_000_000, gt=0)

    @field_validator("agent_root", "python")
    @classmethod
    def absolute_paths(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("runtime paths must be absolute")
        return value

    @field_validator("argv")
    @classmethod
    def valid_argv(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not value or any(not isinstance(item, str) or not item for item in value):
            raise ValueError("argv must contain non-empty strings")
        return value

    @field_validator("env_names")
    @classmethod
    def valid_env_names(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("env_names must be unique")
        if any(_ENV_NAME.fullmatch(item) is None for item in value):
            raise ValueError("env_names must contain names, not values")
        return value

    @model_validator(mode="after")
    def adapter_contract(self) -> Self:
        if self.adapter == "static":
            if self.agent_root is not None or self.python is not None or self.argv:
                raise ValueError("static binding cannot configure an agent runtime")
            if self.env_names:
                raise ValueError("static binding cannot expose environment variables")
        elif self.adapter == "nanobot_local":
            if self.agent_root is None or self.python is None:
                raise ValueError("nanobot_local requires agent_root and python")
            if self.argv is not None:
                raise ValueError("nanobot_local uses the fixed evaluator worker")
            if self.env_names:
                raise ValueError("nanobot_local cannot expose personal environment")
        elif self.argv is None:
            raise ValueError("stdio requires argv")
        return self


class RuntimeFileIdentity(StrictModel):
    """Hash identity for one evaluator-selected executable source file."""

    path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def absolute_file(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("runtime file paths must be absolute")
        return value


def snapshot_runtime_binding(binding: RuntimeBinding) -> list[RuntimeFileIdentity]:
    """Snapshot the bounded executable closure selected by a trusted binding."""

    return [
        RuntimeFileIdentity(
            path=path,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in _runtime_paths(binding)
    ]


def runtime_paths(binding: RuntimeBinding) -> tuple[Path, ...]:
    """Return the fixed runtime files whose hashes must be rechecked."""

    return _runtime_paths(binding)


def _runtime_paths(binding: RuntimeBinding) -> tuple[Path, ...]:
    if binding.adapter == "static":
        return ()
    paths: list[Path] = []
    if binding.python is not None:
        paths.append(_existing_file(binding.python, "python"))
    if binding.adapter == "nanobot_local":
        root = binding.agent_root
        if root is None:
            raise ValueError("nanobot_local requires agent_root")
        paths.extend(
            _existing_file(root / relative, relative)
            for relative in (
                "nanobot/sdk/types.py",
                "nanobot/runtime_context.py",
            )
        )
    elif binding.python is not None:
        script = Path((binding.argv or [""])[0])
        if not script.is_absolute():
            raise ValueError("stdio Python worker script must be an absolute path")
        paths.append(_existing_file(script, "argv[0]"))
    else:
        paths.append(_resolve_stdio_executable(binding))
    if binding.adapter == "stdio":
        paths.extend(
            _existing_file(candidate, f"argv[{index}]")
            for index, item in enumerate(binding.argv or ())
            if (candidate := Path(item)).is_absolute()
            and candidate.suffix.lower() in _CODE_SUFFIXES
        )
    unique = {path.resolve(): path.resolve() for path in paths}
    return tuple(sorted(unique.values(), key=str))


def _existing_file(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"{label} is not a file: {path}")
    return resolved


def resolve_stdio_executable(binding: RuntimeBinding) -> Path:
    """Resolve a stdio executable without consulting runtime shell behavior."""

    return _resolve_stdio_executable(binding)


def _resolve_stdio_executable(binding: RuntimeBinding) -> Path:
    executable = (binding.argv or [""])[0]
    resolved = (
        Path(executable)
        if Path(executable).is_absolute()
        else Path(found)
        if (found := shutil.which(executable)) is not None
        else None
    )
    if resolved is None:
        raise ValueError(f"stdio executable {executable!r} cannot be resolved")
    return _existing_file(resolved, "argv[0]")


def binding_supports(
    binding: RuntimeBinding,
    execution_payload: Any,
) -> tuple[bool, str | None]:
    """Return fixed adapter support without upgrading unknown operations."""

    if not isinstance(execution_payload, dict):
        return False, "adapter_input must be an object"
    allowed_keys = {"input", "preconditions", "source_files"}
    extras = set(execution_payload) - allowed_keys
    if extras:
        return False, f"adapter_input has unsupported fields {sorted(extras)}"
    operation_input = execution_payload.get("input")
    preconditions = execution_payload.get("preconditions")
    if not isinstance(operation_input, dict):
        return False, "adapter_input.input must be an object"
    if not isinstance(preconditions, list):
        return False, "adapter_input.preconditions must be an array"
    source_files = execution_payload.get("source_files")
    if source_files is not None and not _valid_source_files(source_files):
        return False, "adapter_input.source_files must contain path and sha256 only"
    operation = operation_input.get("operation")
    if not isinstance(operation, str) or not operation:
        return False, "adapter_input.input.operation must be a non-empty string"
    if "oracle" in operation_input or "expected" in operation_input:
        return False, "adapter input cannot contain oracle or expected values"

    if binding.adapter == "stdio":
        return True, None
    if binding.adapter == "static":
        if preconditions:
            return False, "static adapter requires empty preconditions"
        if operation == "validate_schema":
            if not isinstance(operation_input.get("schema"), dict):
                return False, "static validate_schema requires an inline schema"
            if "instance" not in operation_input:
                return False, "static validate_schema requires instance"
            if set(operation_input) != {"operation", "schema", "instance"}:
                return False, "static validate_schema input has unsupported fields"
            return True, None
        if operation == "inspect_snapshot":
            if "declared_value" not in operation_input:
                return False, "static inspect_snapshot requires declared_value"
            if set(operation_input) != {"operation", "declared_value"}:
                return False, "static inspect_snapshot input has unsupported fields"
            return True, None
        return False, f"static does not support {operation}"

    entrypoint = operation_input.get("entrypoint")
    if (
        operation == "construct_and_serialize"
        and set(operation_input)
        == {"operation", "class_name", "arguments", "serializer"}
        and operation_input.get("class_name") == "RunResult"
        and operation_input.get("serializer") == "dataclasses.asdict"
        and isinstance(operation_input.get("arguments"), dict)
        and set(operation_input["arguments"]) == {"content"}
    ):
        return True, None
    if (
        operation == "invoke_module"
        and set(operation_input) == {"operation", "entrypoint", "arguments"}
        and entrypoint == "result_from_response"
        and isinstance(operation_input.get("arguments"), dict)
        and set(operation_input["arguments"]) == {"response", "capture"}
    ):
        return True, None
    label = f"{operation}/{entrypoint}" if entrypoint else operation
    return False, f"nanobot_local does not support {label}"


def _valid_source_files(value: object) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256"}
            or not isinstance(item.get("path"), str)
            or not item["path"]
            or not isinstance(item.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
        ):
            return False
    return True
