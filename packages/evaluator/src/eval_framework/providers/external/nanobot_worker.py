"""Isolated fixed worker for the narrow Nanobot SDK value-object contract."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any


def _fixture_map(preconditions: list[object]) -> dict[str, dict[str, Any]]:
    fixtures: dict[str, dict[str, Any]] = {}
    for value in preconditions:
        if not isinstance(value, dict):
            raise ValueError("preconditions must contain objects")
        name = value.get("fixture")
        if not isinstance(name, str) or not name:
            raise ValueError("precondition fixture must be named")
        if name in fixtures:
            raise ValueError(f"duplicate fixture {name!r}")
        fixtures[name] = {key: item for key, item in value.items() if key != "fixture"}
    return fixtures


def _resolve(value: object, fixtures: dict[str, dict[str, Any]]) -> object:
    if isinstance(value, dict) and set(value) == {"fixture_ref"}:
        name = value["fixture_ref"]
        if not isinstance(name, str) or name not in fixtures:
            raise ValueError(f"unknown fixture reference {name!r}")
        return SimpleNamespace(**fixtures[name])
    return value


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    agent_root = Path(payload["agent_root"])
    sdk_types = _load_bound_sdk_types(agent_root)

    adapter_input = payload["adapter_input"]
    operation_input = adapter_input["input"]
    operation = operation_input["operation"]
    if operation == "construct_and_serialize":
        result = sdk_types.RunResult(**operation_input["arguments"])
    elif operation == "invoke_module":
        fixtures = _fixture_map(adapter_input["preconditions"])
        arguments = operation_input["arguments"]
        result = sdk_types.result_from_response(
            _resolve(arguments.get("response"), fixtures),
            _resolve(arguments.get("capture"), fixtures),
        )
    else:  # The parent validates the whitelist before starting this worker.
        raise ValueError(f"unsupported operation {operation!r}")
    return {"result": dataclasses.asdict(result)}


def _load_bound_sdk_types(agent_root: Path) -> ModuleType:
    """Execute only the two hash-bound modules, without package initializers."""

    package = ModuleType("nanobot")
    package.__path__ = []  # type: ignore[attr-defined]
    sdk_package = ModuleType("nanobot.sdk")
    sdk_package.__path__ = []  # type: ignore[attr-defined]
    sys.modules["nanobot"] = package
    sys.modules["nanobot.sdk"] = sdk_package

    _load_module_from_path(
        "nanobot.runtime_context",
        agent_root / "nanobot/runtime_context.py",
    )
    return _load_module_from_path(
        "nanobot.sdk.types",
        agent_root / "nanobot/sdk/types.py",
    )


def _load_module_from_path(module_name: str, path: Path) -> ModuleType:
    """Load one evaluator-selected module path under a fixed module name."""

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load bound module {module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    request = json.load(sys.stdin)
    if set(request) != {"protocol_version", "agent_root", "adapter_input"}:
        raise ValueError("invalid worker request")
    if request["protocol_version"] != "1.0":
        raise ValueError("unsupported protocol version")
    json.dump(
        {"protocol_version": "1.0", "observations": execute(request)},
        sys.stdout,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    main()
