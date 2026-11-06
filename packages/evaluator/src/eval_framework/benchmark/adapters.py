"""Built-in benchmark adapters; the runner only uses the neutral Provider API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..agent_adapter import SandboxSpec


class NanobotRuntimeAdapter:
    provider_id = "nanobot"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)

    def fingerprint_sources(self) -> list[Path]:
        from ..integrations.nanobot.sources import integration_source_paths

        root = Path(__file__).parent
        return [
            root / name
            for name in (
                "adapters.py",
                "nanobot_runtime.py",
                "nanobot_worker.py",
                "module_runtime.py",
                "module_worker.py",
                "decision_runtime.py",
                "decision_worker.py",
                "inspect_runtime.py",
                "inspect_docker.py",
            )
        ] + list(integration_source_paths().values())

    def runtime_identity(self, mode: str | None = None) -> dict[str, Any]:
        from .decision_runtime import decision_identity
        from .module_runtime import module_identity
        from .nanobot_runtime import runtime_identity

        identify = {"module": module_identity, "decision": decision_identity}.get(
            mode, runtime_identity
        )
        return identify(self.config)

    def needs_model(self, mode: str) -> bool:
        if mode not in {"module", "decision", "agent"}:
            raise ValueError(f"unsupported execution mode: {mode}")
        return mode != "module"

    def inspect_model(self) -> Any:
        from .inspect_runtime import inspect_model

        return inspect_model(self.config)

    def execution_kind(self, mode: str) -> str:
        return {
            "module": "real_module",
            "decision": "real_model_decision",
            "agent": "real_agent",
        }[mode]

    def sandbox_spec(self, output: Path, *, needs_model: bool) -> SandboxSpec:
        from .inspect_runtime import sandbox_spec

        return sandbox_spec(self.config, output, needs_model=needs_model)

    async def execute(
        self, task: dict[str, Any], *, mode: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        from .decision_runtime import execute_decision_task
        from .module_runtime import execute_module_task
        from .nanobot_runtime import execute_task

        execute = {
            "module": execute_module_task,
            "decision": execute_decision_task,
            "agent": execute_task,
        }[mode]
        return await execute(task, config=config, workspace=None)


# Historical import remains the exact same runtime class.
NanobotAdapter = NanobotRuntimeAdapter


class NanobotAdapterFactory:
    def create_adapter(self, *, config: dict[str, Any]) -> NanobotAdapter:
        return NanobotAdapter(config)
