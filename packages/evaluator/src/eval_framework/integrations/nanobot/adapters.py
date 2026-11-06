"""nanobot 的三种执行边界；旧 provider 仅负责兼容分派。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...agent_adapter import SandboxSpec


def _sources() -> list[Path]:
    from .sources import integration_source_paths

    benchmark = Path(__file__).resolve().parents[2] / "benchmark"
    return (
        [Path(__file__), Path(__file__).with_name("inspect_bridge.py")]
        + [
            benchmark / name
            for name in (
                "adapters.py",
                "module_runtime.py",
                "decision_runtime.py",
                "inspect_runtime.py",
                "inspect_docker.py",
            )
        ]
        + list(integration_source_paths().values())
    )


class _ModeAdapter:
    mode: str
    kind: str
    provider_id: str

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)

    def _check_mode(self, mode: str | None) -> None:
        if mode is not None and mode != self.mode:
            raise ValueError(f"{self.provider_id} does not support mode {mode!r}")

    def fingerprint_sources(self) -> list[Path]:
        return _sources()

    def needs_model(self, mode: str) -> bool:
        self._check_mode(mode)
        return self.mode != "module"

    def execution_kind(self, mode: str) -> str:
        self._check_mode(mode)
        return self.kind

    def inspect_model(self) -> Any:
        if self.mode == "module":
            raise ValueError("module mode does not use a model")
        from ...benchmark.inspect_runtime import inspect_model

        return inspect_model(self.config)

    def sandbox_spec(self, output: Path, *, needs_model: bool) -> SandboxSpec:
        from ...benchmark.inspect_runtime import sandbox_spec

        return sandbox_spec(self.config, output, needs_model=needs_model)


class NanobotModuleAdapter(_ModeAdapter):
    provider_id, mode, kind = "nanobot_module", "module", "real_module"

    def runtime_identity(self, mode: str | None = None) -> dict:
        self._check_mode(mode)
        from ...benchmark.module_runtime import module_identity

        return module_identity(self.config)

    async def execute(self, task: dict, *, mode: str, config: dict) -> dict:
        self._check_mode(mode)
        from ...benchmark.module_runtime import execute_module_task

        return await execute_module_task(task, config=config, workspace=None)


class NanobotDecisionAdapter(_ModeAdapter):
    provider_id, mode, kind = "nanobot_decision", "decision", "real_model_decision"

    def runtime_identity(self, mode: str | None = None) -> dict:
        self._check_mode(mode)
        from ...benchmark.decision_runtime import decision_identity

        return decision_identity(self.config)

    async def execute(self, task: dict, *, mode: str, config: dict) -> dict:
        self._check_mode(mode)
        from ...benchmark.decision_runtime import execute_decision_task

        return await execute_decision_task(task, config=config, workspace=None)


class NanobotAgentAdapter(_ModeAdapter):
    provider_id, mode, kind = "nanobot_agent", "agent", "real_agent"

    def runtime_identity(self, mode: str | None = None) -> dict:
        self._check_mode(mode)
        from ...benchmark.nanobot_runtime import runtime_identity

        return runtime_identity(self.config)

    async def execute(self, task: dict, *, mode: str, config: dict) -> dict:
        self._check_mode(mode)
        from ...benchmark.nanobot_runtime import execute_task

        return await execute_task(task, config=config, workspace=None)


class NanobotRuntimeAdapter:
    """provider=nanobot 的历史多模式入口，始终使用当前 config 分派。"""

    provider_id = "nanobot"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)

    def _adapter(self, mode: str | None = None) -> _ModeAdapter:
        adapters = {
            "module": NanobotModuleAdapter,
            "decision": NanobotDecisionAdapter,
            "agent": NanobotAgentAdapter,
        }
        selected = mode if mode is not None else "agent"
        if selected not in adapters:
            raise ValueError(f"unsupported execution mode: {selected}")
        return adapters[selected](self.config)

    def fingerprint_sources(self) -> list[Path]:
        return _sources()

    def runtime_identity(self, mode: str | None = None) -> dict:
        return self._adapter(mode).runtime_identity(mode)

    def needs_model(self, mode: str) -> bool:
        return self._adapter(mode).needs_model(mode)

    def execution_kind(self, mode: str) -> str:
        return self._adapter(mode).execution_kind(mode)

    def inspect_model(self) -> Any:
        return self._adapter().inspect_model()

    def sandbox_spec(self, output: Path, *, needs_model: bool) -> SandboxSpec:
        return self._adapter().sandbox_spec(output, needs_model=needs_model)

    async def execute(self, task: dict, *, mode: str, config: dict) -> dict:
        return await self._adapter(mode).execute(task, mode=mode, config=config)


NanobotAdapter = NanobotRuntimeAdapter


class NanobotAdapterFactory:
    def __init__(self, adapter_type=NanobotRuntimeAdapter):
        self.adapter_type = adapter_type

    def create_adapter(self, *, config: dict):
        return self.adapter_type(config)
