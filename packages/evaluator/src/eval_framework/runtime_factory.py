"""Build a fresh minimal-agent runtime for exactly one evaluation case."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from minimal_agent.runtime import MinimalAgent, ToolRegistry
from minimal_agent.runtime.model_client import ModelClient

from .errors import EvaluationPreflightError
from .schemas import ExecutionSpec

ModelClientFactory = Callable[[ExecutionSpec], ModelClient]
ToolRegistryFactory = Callable[[frozenset[str]], ToolRegistry]


class StateEnvironment(Protocol):
    registry: ToolRegistry

    def snapshot(self) -> dict[str, Any]: ...

    def cleanup(self) -> None: ...


EnvironmentFactory = Callable[[frozenset[str]], StateEnvironment]


class StateObservationError(RuntimeError):
    """The evaluator could not independently read the configured environment."""


@dataclass
class Runtime:
    agent: MinimalAgent
    model_client: ModelClient
    registry: ToolRegistry
    session_id: str
    evidence_sink: Any = None
    environment: StateEnvironment | None = None

    def snapshot(self) -> dict[str, Any] | None:
        try:
            return self.environment.snapshot() if self.environment is not None else None
        except Exception as exc:
            raise StateObservationError("Environment state observation failed") from exc

    def cleanup(self) -> None:
        if self.environment is not None:
            self.environment.cleanup()


class RuntimeFactory:
    def __init__(
        self,
        model_client_factory: ModelClientFactory,
        tool_registry_factory: ToolRegistryFactory | None = None,
        *,
        environment_factory: EnvironmentFactory | None = None,
    ) -> None:
        self._model_client_factory = model_client_factory
        self._tool_registry_factory = tool_registry_factory
        if environment_factory is not None and tool_registry_factory is not None:
            raise ValueError("choose environment_factory or tool_registry_factory")
        self._environment_factory = environment_factory

    def create(
        self,
        execution: ExecutionSpec,
        *,
        session_id: str,
        allowed_tools: frozenset[str],
        evidence_sink: Any = None,
    ) -> Runtime:
        environment = None
        if self._environment_factory is not None:
            environment = self._environment_factory(allowed_tools)
            registry = environment.registry
        elif self._tool_registry_factory is None:
            if allowed_tools:
                raise EvaluationPreflightError(
                    "NATIVE_TOOL_HANDLER_REQUIRED",
                    f"native handlers are required for tools {sorted(allowed_tools)}",
                )
            registry = ToolRegistry()
        else:
            registry = self._tool_registry_factory(allowed_tools)
        try:
            client = self._model_client_factory(execution)
            agent = MinimalAgent(
                client,
                registry,
                max_steps=execution.max_steps,
                evidence_sink=evidence_sink,
            )
        except BaseException:
            if environment is not None:
                environment.cleanup()
            raise
        return Runtime(
            agent=agent,
            model_client=client,
            registry=registry,
            session_id=session_id,
            evidence_sink=evidence_sink,
            environment=environment,
        )


def model_metadata(client: Any) -> dict[str, Any]:
    metadata = getattr(client, "metadata", None)
    if callable(metadata):
        return {"client_type": type(client).__name__, **metadata()}
    return {"client_type": type(client).__name__, "model": "not_configured"}
