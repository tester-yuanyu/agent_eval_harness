"""Opt-in raw-model runtime using the existing benchmark Provider boundary."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from eval_contracts.benchmark import TaskInput
from inspect_ai.solver import TaskState

from ...source_identity import (
    capture_identity,
    layer_source_paths,
    runtime_layer_identity,
    source_bytes,
)
from ..prompts import render_prompt
from .agent.base import BaseAgent
from .agent.raw_model_adapter import RawModelAgentAdapter
from .inspect_solver import execute_native_task


class RawModelRuntimeAdapter:
    provider_id = "raw_model"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)
        render_prompt(
            config.get("prompt_version", "harness-v1"), config.get("instructions", "")
        )
        maximum = config.get("max_tool_calls", 40)
        if type(maximum) is not int or not 1 <= maximum <= 300:
            raise ValueError("max_tool_calls must be between 1 and 300")

    @staticmethod
    def _check_mode(mode: str | None) -> None:
        if mode not in {None, "agent"}:
            raise ValueError(
                "raw_model supports agent tasks only; "
                "use the native runtime for module/decision"
            )

    def fingerprint_sources(self) -> list[Path]:
        return list(layer_source_paths().values())

    @capture_identity
    def runtime_identity(self, mode: str | None = None) -> dict[str, Any]:
        self._check_mode(mode)
        _, prompt = render_prompt(
            self.config.get("prompt_version", "harness-v1"),
            self.config.get("instructions", ""),
        )
        return {
            "agent": self.provider_id,
            "orchestrator": "inspect-custom-harness-v1",
            "isolation": self.config.get("sandbox", "docker"),
            "prompt": prompt,
            "execution_layers": runtime_layer_identity(),
            "sources": {
                name: hashlib.sha256(source_bytes(path)).hexdigest()
                for name, path in layer_source_paths().items()
            },
        }

    def needs_model(self, mode: str) -> bool:
        self._check_mode(mode)
        return True

    def execution_kind(self, mode: str) -> str:
        self._check_mode(mode)
        return "harness_raw_model"

    def inspect_model(self) -> Any:
        from ...runtime_model import inspect_model

        return inspect_model(self.config)

    def sandbox_spec(self, output: Path, *, needs_model: bool) -> str:
        kind = self.config.get("sandbox", "docker")
        if kind not in {"local", "docker"}:
            raise ValueError("sandbox must be local or docker")
        self.output = output.parent
        return kind

    def _new_agent(self) -> BaseAgent:
        return RawModelAgentAdapter()

    async def execute(
        self,
        task: dict[str, Any],
        *,
        mode: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.execute_in_inspect(task, mode=mode, config=config)

    async def execute_in_inspect(
        self,
        task: dict[str, Any],
        *,
        mode: str,
        config: dict[str, Any],
        state: TaskState | None = None,
    ) -> dict[str, Any]:
        self._check_mode(mode)
        public = TaskInput(
            task_id=task["id"],
            prompt=task["prompt"],
            followups=task.get("followups", []),
            initial_state={"files": task["fixtures"]},
            tools=task["allowed_tools"],
            max_steps=task.get("max_steps", 12),
        )
        try:
            observation = await execute_native_task(
                public,
                agent=self._new_agent(),
                execution_kind=self.execution_kind(mode),
                max_steps=config.get("max_steps", 12),
                max_tool_calls=config.get("max_tool_calls", 40),
                timeout_seconds=config.get("timeout_seconds", 180),
                max_consecutive_errors=config.get("max_consecutive_errors"),
                prompt_version=config.get("prompt_version", "harness-v1"),
                instructions=config.get("instructions", ""),
                task_state=state,
                evidence_directory=(self.output / "evidence" / uuid4().hex)
                if hasattr(self, "output")
                else None,
            )
        except BaseException as exc:
            if (observation := getattr(exc, "benchmark_observation", None)) is not None:
                observation["runtime_identity"] = self.runtime_identity(mode)
            raise
        observation["runtime_identity"] = self.runtime_identity(mode)
        return observation


class RawModelAdapterFactory:
    def create_adapter(self, *, config: dict[str, Any]) -> RawModelRuntimeAdapter:
        return RawModelRuntimeAdapter(config)


class NanobotComponentRuntimeAdapter(RawModelRuntimeAdapter):
    """Provider boundary for the in-process BaseAgent component profile."""

    provider_id = "nanobot_component"

    def _new_agent(self) -> BaseAgent:
        from .agent.nanobot_adapter import NanobotComponentAdapter

        return NanobotComponentAdapter(self.config)

    def fingerprint_sources(self) -> list[Path]:
        from .agent.nanobot_adapter import component_sources

        return super().fingerprint_sources() + list(
            component_sources(self.config).values()
        )

    @capture_identity
    def runtime_identity(self, mode: str | None = None) -> dict[str, Any]:
        from .agent.nanobot_adapter import component_identity

        return {
            **super().runtime_identity(mode),
            "nanobot": component_identity(self.config),
        }

    def execution_kind(self, mode: str) -> str:
        self._check_mode(mode)
        return "harness_nanobot_component"


class NanobotComponentAdapterFactory:
    def create_adapter(
        self, *, config: dict[str, Any]
    ) -> NanobotComponentRuntimeAdapter:
        return NanobotComponentRuntimeAdapter(config)
