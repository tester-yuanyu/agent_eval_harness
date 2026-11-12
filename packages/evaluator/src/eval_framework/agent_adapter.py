"""Optional Inspect execution boundary for registered evaluation Providers.

EvaluationProvider keeps its existing lifecycle. Domain projections are trusted
Python integrations, never import paths or executable expressions in task data.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import signal
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .provider import AdapterOutput, EvaluationProvider
from .schemas import ExecutionSpec, TestScope
from .source_identity import capture_identity, source_bytes

SandboxSpec = str | tuple[str, str]


class AgentAdapter(Protocol):
    provider_id: str

    def fingerprint_sources(self) -> Sequence[Path]: ...

    def runtime_identity(self, mode: str | None = None) -> dict[str, Any]: ...

    def needs_model(self, mode: str) -> bool: ...

    def execution_kind(self, mode: str) -> str: ...

    def inspect_model(self) -> Any: ...

    def sandbox_spec(self, output: Path, *, needs_model: bool) -> SandboxSpec: ...

    async def execute(
        self, task: dict[str, Any], *, mode: str, config: dict[str, Any]
    ) -> dict[str, Any]: ...


class AgentAdapterFactory(Protocol):
    def create_adapter(self, *, config: dict[str, Any]) -> AgentAdapter: ...


@capture_identity
def adapter_identity(adapter: AgentAdapter) -> dict[str, Any]:
    """Bind the declared implementation closure without recording host paths."""
    declared = list(adapter.fingerprint_sources())
    implementation = inspect.getsourcefile(type(adapter))
    if not declared or implementation is None:
        raise ValueError("adapter requires inspectable implementation sources")
    declared.append(Path(implementation))
    files = {}
    for index, root in enumerate(dict.fromkeys(declared)):
        root = Path(root).resolve(strict=True)
        for path in sorted(root.rglob("*")) if root.is_dir() else [root]:
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(root).as_posix() if root.is_dir() else path.name
            files[f"{index}:{relative}"] = hashlib.sha256(
                source_bytes(path)
            ).hexdigest()
    return {"provider_id": adapter.provider_id, "sources": files}


class EvaluationProviderAdapter:
    """Reuse a synchronous Provider through an Inspect-managed offline worker.

    A trusted factory supplies the worker command and domain projections, never
    task data. The worker instantiates the existing Provider and calls
    execute_provider_request. This bridge has no live model transport or OS
    isolation; Inspect terminates the worker on timeout/cancellation.
    """

    def __init__(
        self,
        provider_id: str,
        *,
        provider_version: str,
        command: Sequence[str],
        project_execution: Callable[
            [dict[str, Any], str], tuple[ExecutionSpec, TestScope]
        ],
        project_observation: Callable[[AdapterOutput], dict[str, Any]],
        identity: Callable[[], dict[str, Any]],
        sources: Sequence[Path],
    ) -> None:
        if not sources:
            raise ValueError(
                "Provider adapter requires declared implementation sources"
            )
        if not command or not Path(command[0]).is_absolute():
            raise ValueError("Provider worker requires an absolute executable")
        self.provider_id = provider_id
        self.provider_version = provider_version
        self.command = tuple(command)
        self.project_execution = project_execution
        self.project_observation = project_observation
        self._identity = identity
        self._sources = tuple(sources)

    def fingerprint_sources(self) -> Sequence[Path]:
        sources = list(self._sources)
        for implementation in (
            type(self),
            self.project_execution,
            self.project_observation,
            self._identity,
        ):
            source = inspect.getsourcefile(implementation)
            if source is None:
                raise ValueError(
                    "Provider adapter implementation source is unavailable"
                )
            sources.append(Path(source))
        return tuple(dict.fromkeys(sources))

    def runtime_identity(self, mode: str | None = None) -> dict[str, Any]:
        return {
            **self._identity(),
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "isolation": "local-no-os-isolation",
            "worker_command_sha256": hashlib.sha256(
                json.dumps(self.command).encode()
            ).hexdigest(),
        }

    def needs_model(self, mode: str) -> bool:
        return False

    def execution_kind(self, mode: str) -> str:
        return "offline_provider"

    def inspect_model(self) -> str:
        return "mockllm/model"

    def sandbox_spec(self, output: Path, *, needs_model: bool) -> SandboxSpec:
        return "local"

    async def execute(
        self, task: dict[str, Any], *, mode: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        from inspect_ai.util import sandbox

        if config.get("sandbox", "local") != "local":
            raise ValueError("local Provider bridge cannot supply a Docker sandbox")

        execution, scope = self.project_execution(task, mode)
        timeout = min(
            execution.timeout_seconds, float(config.get("timeout_seconds", 180))
        )
        execution = execution.model_copy(
            update={
                "timeout_seconds": timeout,
                "max_steps": min(execution.max_steps, int(config.get("max_steps", 12))),
            }
        )
        request = {"execution": execution.model_dump(mode="json"), "scope": scope}
        # Offline workers must not inherit model/service credentials or import paths.
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            in {"PATH", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR"}
        }
        environment["DEEPEVAL_TELEMETRY_OPT_OUT"] = "YES"
        completed = await sandbox().exec(
            ["env", "-i", *[f"{k}={v}" for k, v in environment.items()], *self.command],
            input=json.dumps(request),
            timeout=timeout,
        )
        if not completed.success:
            raise RuntimeError(
                f"Provider worker exited with code {completed.returncode}"
            )
        result = json.loads(completed.stdout)
        if (result["provider_id"], result["provider_version"]) != (
            self.provider_id,
            self.provider_version,
        ):
            raise ValueError("Provider worker identity differs from registered adapter")
        output = AdapterOutput(**result["output"])
        observation = dict(self.project_observation(output))
        observation["runtime_metadata"] = result["runtime_metadata"]
        observation["runtime_identity"] = self.runtime_identity(mode)
        if not output.execution_completed or output.evidence_status != "COMPLETE":
            observation["evidence_complete"] = False
        return observation


def execute_provider_request(
    provider: EvaluationProvider, request: dict[str, Any]
) -> dict[str, Any]:
    """Worker-side reuse of the existing Provider lifecycle and AdapterOutput.

    A trusted entry point reads one JSON request from stdin, constructs its
    Provider through the existing registry/factory, then prints this JSON result.
    Logging belongs on stderr. Provider construction cannot be selected by data.
    """
    if set(request) != {"execution", "scope"}:
        raise ValueError("Provider worker accepts only public execution and scope")
    execution = ExecutionSpec.model_validate(request["execution"])
    scope = request["scope"]
    if scope not in {"module", "link", "end_to_end"}:
        raise ValueError("unsupported Provider scope")
    # Inspect local terminates the immediate worker. Propagate SIGTERM through
    # the Provider's exception path so its own subprocess/session cleanup runs.
    # This helper belongs in a dedicated worker's main thread, not a thread pool.
    previous = signal.signal(signal.SIGTERM, _terminate_provider_worker)
    try:
        runtime = provider.create_runtime(execution, uuid4().hex, scope)
        try:
            output = (
                provider.run_module(runtime, execution)
                if scope == "module"
                else provider.run_full(runtime, execution, scope)
            )
            return {
                "provider_id": provider.provider_id,
                "provider_version": provider.provider_version,
                "output": asdict(output),
                "runtime_metadata": provider.runtime_metadata(runtime),
            }
        finally:
            provider.cleanup(runtime)
    finally:
        signal.signal(signal.SIGTERM, previous)


class ProviderWorkerTerminated(RuntimeError):
    """Cancellation must unwind Provider-owned resources before worker exit."""


def _terminate_provider_worker(signum: int, frame: Any) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise ProviderWorkerTerminated("Inspect terminated the Provider worker")
