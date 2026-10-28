"""Provider implementation for explicit external runtime bindings."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema.validators import validator_for
from referencing import Registry

from ...capabilities import CapabilityRegistry
from ...dataset_validator import validate_dataset as validate_core_dataset
from ...diagnostics import DiagnosticRegistry
from ...errors import EvaluationPreflightError
from ...provider import AdapterOutput, ProviderExceptionInfo
from ...schemas import (
    DatasetBundle,
    ExecutionProfile,
    ExecutionSpec,
    TestScope,
    ValidationIssue,
    ValidationReport,
)
from ...tool_catalog import ToolCatalog
from .binding import (
    RuntimeBinding,
    RuntimeFileIdentity,
    binding_supports,
    resolve_stdio_executable,
    runtime_paths,
)


class ExternalAdapterError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ExternalRuntime:
    execution: ExecutionSpec
    session_id: str
    scope: TestScope


class ExternalProvider:
    evidence_rules_version = "external-returned-observations-v1"
    trace_rules: tuple[Any, ...] = ()
    environment_state_available = False

    def __init__(
        self,
        binding: RuntimeBinding,
        capabilities: CapabilityRegistry,
        *,
        execution_profiles: dict[str, ExecutionProfile],
        runtime_files: list[RuntimeFileIdentity] | None = None,
    ) -> None:
        self.binding = binding
        self.provider_id = binding.agent_id
        self.provider_version = f"external-binding-{binding.version}"
        self.capabilities = capabilities
        self.tools = ToolCatalog.from_registry(
            capabilities,
            profiles=execution_profiles,
        )
        self.diagnostics = DiagnosticRegistry()
        self._runtime_files = tuple(runtime_files or ())

    def create_runtime(
        self,
        execution: ExecutionSpec,
        session_id: str,
        scope: TestScope,
    ) -> ExternalRuntime:
        payload = execution.adapter_input
        supported, reason = binding_supports(self.binding, payload)
        if not supported:
            raise ExternalAdapterError("OPERATION_UNSUPPORTED", reason)
        return ExternalRuntime(execution=execution, session_id=session_id, scope=scope)

    def run_module(
        self,
        runtime: object,
        execution: ExecutionSpec,
    ) -> AdapterOutput:
        self._runtime(runtime, execution)
        return self._run(execution)

    def run_full(
        self,
        runtime: object,
        execution: ExecutionSpec,
        scope: TestScope,
    ) -> AdapterOutput:
        resolved = self._runtime(runtime, execution)
        if resolved.scope != scope:
            raise TypeError("external runtime scope does not match invocation")
        return self._run(execution)

    def _run(self, execution: ExecutionSpec) -> AdapterOutput:
        payload = execution.adapter_input
        if self.binding.adapter == "static":
            observations = _run_static(payload)
        elif self.binding.adapter == "nanobot_local":
            _verify_nanobot_sources(self.binding, payload)
            worker = Path(__file__).with_name("nanobot_worker.py")
            observations = _run_json_process(
                [str(self.binding.python), "-I", "-B", str(worker)],
                {
                    "protocol_version": "1.0",
                    "agent_root": str(self.binding.agent_root),
                    "adapter_input": payload,
                },
                binding=self.binding,
                runtime_files=self._runtime_files,
                timeout_seconds=min(
                    self.binding.timeout_seconds,
                    execution.timeout_seconds,
                ),
            )
        else:
            command = _stdio_command(self.binding)
            observations = _run_json_process(
                command,
                {
                    "protocol_version": "1.0",
                    "execution": execution.model_dump(mode="json"),
                },
                binding=self.binding,
                runtime_files=self._runtime_files,
                timeout_seconds=min(
                    self.binding.timeout_seconds,
                    execution.timeout_seconds,
                ),
            )
        return AdapterOutput(
            module_output=None,
            turns=[],
            before_snapshot=None,
            turn_snapshots=[],
            snapshot=None,
            observations=observations,
            evidence_status="UNAVAILABLE",
        )

    def cleanup(self, runtime: object) -> None:
        if not isinstance(runtime, ExternalRuntime):
            raise TypeError("ExternalProvider received an incompatible runtime")

    def classify_exception(self, exc: Exception) -> ProviderExceptionInfo:
        code = exc.code if isinstance(exc, ExternalAdapterError) else type(exc).__name__
        if isinstance(exc, ExternalAdapterError):
            if exc.code == "ADAPTER_PROCESS_FAILED":
                execution_status = "AGENT_EXCEPTION"
            elif exc.code == "ADAPTER_TIMEOUT":
                execution_status = "OUTER_TIMEOUT"
            else:
                execution_status = "EVALUATOR_ERROR"
        else:
            execution_status = "AGENT_EXCEPTION"
        return ProviderExceptionInfo(
            execution_status=execution_status,
            exception={"type": type(exc).__name__, "code": code, "message": str(exc)},
        )

    def runtime_metadata(self, runtime: object) -> dict[str, Any]:
        resolved = self._runtime(runtime)
        metadata: dict[str, Any] = {
            "adapter": self.binding.adapter,
            "binding_version": self.binding.version,
            "agent_id": self.binding.agent_id,
            "env_names": list(self.binding.env_names),
        }
        if self.binding.python is not None:
            metadata["interpreter"] = str(self.binding.python)
        source_files = (resolved.execution.adapter_input or {}).get("source_files")
        if source_files:
            metadata["source_files"] = source_files
        if self._runtime_files:
            metadata["runtime_files"] = [
                item.model_dump(mode="json") for item in self._runtime_files
            ]
        return metadata

    def tool_version(self, runtime: object) -> str:
        self._runtime(runtime)
        return self.capabilities.bundle.capability_bundle_sha256

    @staticmethod
    def _runtime(
        runtime: object,
        execution: ExecutionSpec | None = None,
    ) -> ExternalRuntime:
        if not isinstance(runtime, ExternalRuntime):
            raise TypeError("ExternalProvider received an incompatible runtime")
        if execution is not None and runtime.execution is not execution:
            raise TypeError("external runtime execution does not match invocation")
        return runtime


class ExternalProviderFactory:
    """Create a provider from a trusted binding; there is no fixed provider ID."""

    def fingerprint_sources(self, **config: Any) -> list[Path]:
        sources = [Path(__file__).resolve().parent]
        if config.get("runtime_files") is not None:
            sources.extend(
                item.path for item in _parse_runtime_files(config["runtime_files"])
            )
            return sources
        raw_binding = config.get("binding")
        if raw_binding is None:
            return sources
        binding = RuntimeBinding.model_validate(raw_binding)
        if binding.python is not None and binding.python.is_file():
            sources.append(binding.python)
        if binding.adapter == "nanobot_local" and binding.agent_root is not None:
            for relative in (
                "nanobot/sdk/types.py",
                "nanobot/runtime_context.py",
            ):
                source = binding.agent_root / relative
                if source.is_file():
                    sources.append(source)
        elif binding.adapter == "stdio":
            for item in binding.argv or ():
                candidate = Path(item)
                if candidate.is_absolute() and candidate.is_file():
                    sources.append(candidate)
        return sources

    def validate_dataset(
        self,
        dataset: DatasetBundle,
        **config: Any,
    ) -> ValidationReport:
        try:
            binding = RuntimeBinding.model_validate(config.get("binding"))
            runtime_files = _parse_runtime_files(config.get("runtime_files"))
            _verify_runtime_files(binding, runtime_files)
            registry = _load_registry(dataset, binding, config.get("bundle_override"))
            tools = ToolCatalog.from_registry(
                registry,
                profiles=dataset.execution_profiles,
            )
            report = validate_core_dataset(dataset, registry, tools)
            if dataset.provider_id not in {"unknown", binding.agent_id}:
                report.issues.append(
                    ValidationIssue(
                        case_id=None,
                        field_path="provider_id",
                        message=(
                            f"dataset provider {dataset.provider_id!r} does not match "
                            f"binding agent {binding.agent_id!r}"
                        ),
                    )
                )
            for case in dataset.cases:
                supported, reason = binding_supports(
                    binding,
                    case.execution.adapter_input,
                )
                if not supported:
                    report.issues.append(
                        ValidationIssue(
                            case_id=case.case_id,
                            field_path="execution.adapter_input",
                            message=reason,
                        )
                    )
            report.valid = not report.issues
            return report
        except Exception as exc:
            return ValidationReport(
                valid=False,
                issues=[
                    ValidationIssue(
                        case_id=None,
                        field_path="binding",
                        message=str(exc),
                    )
                ],
            )

    def create(
        self,
        dataset: DatasetBundle,
        model_client_factory: Any = None,
        **config: Any,
    ) -> ExternalProvider:
        del model_client_factory
        binding = RuntimeBinding.model_validate(config.get("binding"))
        runtime_files = _parse_runtime_files(config.get("runtime_files"))
        report = self.validate_dataset(dataset, **config)
        if not report.valid:
            message = "; ".join(issue.message for issue in report.issues)
            raise EvaluationPreflightError("EXTERNAL_BINDING_INVALID", message)
        registry = _load_registry(dataset, binding, config.get("bundle_override"))
        return ExternalProvider(
            binding,
            registry,
            execution_profiles=dataset.execution_profiles,
            runtime_files=runtime_files,
        )


def _load_registry(
    dataset: DatasetBundle,
    binding: RuntimeBinding,
    bundle_override: object,
) -> CapabilityRegistry:
    from ...capability_loader import load_capability_bundle

    bundle_path = bundle_override or dataset.capability_bundle_path
    if bundle_path is None:
        raise EvaluationPreflightError(
            "CAPABILITY_BUNDLE_REQUIRED",
            "dataset has no resolved capability bundle",
            evidence_path=dataset.manifest_path,
        )
    bundle = load_capability_bundle(
        Path(str(bundle_path)),
        expected_sha256=(
            dataset.capability_bundle_sha256
            if dataset.capability_bundle_path is not None
            else None
        ),
    )
    if bundle.provider_id != binding.agent_id:
        raise EvaluationPreflightError(
            "CAPABILITY_PROVIDER_MISMATCH",
            f"capability provider {bundle.provider_id!r} != {binding.agent_id!r}",
            evidence_path=str(bundle_path),
        )
    return CapabilityRegistry(bundle)


def _run_static(payload: dict[str, Any]) -> dict[str, Any]:
    operation_input = payload["input"]
    if operation_input["operation"] == "inspect_snapshot":
        return {"declared_value": operation_input["declared_value"]}
    schema = operation_input["schema"]
    validator_class = validator_for(schema)
    validator_class.check_schema(schema)
    validator = validator_class(schema, registry=Registry())
    return {
        "schema_validation": {
            "valid": not any(validator.iter_errors(operation_input["instance"]))
        }
    }


def _verify_nanobot_sources(
    binding: RuntimeBinding,
    payload: dict[str, Any],
) -> None:
    source_files = payload.get("source_files")
    if not isinstance(source_files, list):
        raise ExternalAdapterError(
            "SOURCE_HASH_REQUIRED",
            "nanobot_local requires source_files metadata",
        )
    root = binding.agent_root
    if root is None:
        raise ExternalAdapterError("BINDING_INVALID", "nanobot agent_root is missing")
    for relative in ("nanobot/sdk/types.py", "nanobot/runtime_context.py"):
        expected = next(
            (
                item
                for item in source_files
                if isinstance(item, dict) and item.get("path") == relative
            ),
            None,
        )
        if expected is None or not isinstance(expected.get("sha256"), str):
            raise ExternalAdapterError(
                "SOURCE_HASH_REQUIRED",
                f"nanobot_local requires {relative} sha256",
            )
        source = (root / relative).resolve()
        try:
            source.relative_to(root.resolve())
            actual = hashlib.sha256(source.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise ExternalAdapterError("SOURCE_FILE_INVALID", str(exc)) from exc
        if actual != expected["sha256"]:
            raise ExternalAdapterError(
                "SOURCE_HASH_MISMATCH",
                f"{relative} does not match the trusted source hash",
            )


def _run_json_process(
    command: list[str],
    request: dict[str, Any],
    *,
    binding: RuntimeBinding,
    runtime_files: tuple[RuntimeFileIdentity, ...],
    timeout_seconds: float,
) -> dict[str, Any]:
    _verify_runtime_files(binding, list(runtime_files))
    environment = {
        name: os.environ[name]
        for name in binding.env_names
        if name in os.environ
    }
    encoded = json.dumps(request, ensure_ascii=False).encode("utf-8")
    with tempfile.TemporaryDirectory(prefix="agent-evaluator-external-") as cwd:
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                cwd=cwd,
                start_new_session=True,
            )
        except OSError as exc:
            raise ExternalAdapterError("ADAPTER_START_FAILED", str(exc)) from exc
        stdout, stderr = _communicate_bounded(
            process,
            encoded,
            timeout_seconds=timeout_seconds,
            max_output_bytes=binding.max_output_bytes,
        )
    if process.returncode != 0:
        raise ExternalAdapterError(
            "ADAPTER_PROCESS_FAILED",
            f"adapter exited with status {process.returncode}",
        )
    try:
        response = json.loads(stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalAdapterError(
            "PROTOCOL_RESPONSE_INVALID",
            "adapter response is not one JSON object",
        ) from exc
    if (
        not isinstance(response, dict)
        or set(response) != {"protocol_version", "observations"}
        or response.get("protocol_version") != "1.0"
        or not isinstance(response.get("observations"), dict)
    ):
        raise ExternalAdapterError(
            "PROTOCOL_RESPONSE_INVALID",
            "adapter response must contain only protocol_version 1.0 and observations",
        )
    return response["observations"]


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def _parse_runtime_files(value: object) -> list[RuntimeFileIdentity]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("runtime_files must be an array")
    return [RuntimeFileIdentity.model_validate(item) for item in value]


def _verify_runtime_files(
    binding: RuntimeBinding,
    identities: list[RuntimeFileIdentity],
) -> None:
    try:
        required = runtime_paths(binding)
        by_path = {item.path.resolve(): item for item in identities}
    except (OSError, ValueError) as exc:
        raise ExternalAdapterError(
            "RUNTIME_FILE_INVALID",
            "a bound runtime file is missing or unreadable",
        ) from exc
    if len(by_path) != len(identities) or set(by_path) != set(required):
        raise ExternalAdapterError(
            "RUNTIME_FILES_INVALID",
            "runtime_files do not match the selected executable closure",
        )
    for path in required:
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ExternalAdapterError(
                "RUNTIME_FILE_INVALID",
                "a bound runtime file is missing or unreadable",
            ) from exc
        if actual != by_path[path].sha256:
            raise ExternalAdapterError(
                "RUNTIME_FILE_MISMATCH",
                f"runtime file hash changed: {path}",
            )


def _stdio_command(binding: RuntimeBinding) -> list[str]:
    if binding.python is not None:
        return [str(binding.python), *(binding.argv or [])]
    _, *arguments = binding.argv or []
    return [str(resolve_stdio_executable(binding)), *arguments]


def _communicate_bounded(
    process: subprocess.Popen[bytes],
    encoded: bytes,
    *,
    timeout_seconds: float,
    max_output_bytes: int,
) -> tuple[bytes, bytes]:
    if process.stdin is None or process.stdout is None or process.stderr is None:
        raise ExternalAdapterError("ADAPTER_PROCESS_INVALID", "missing process pipes")
    deadline = time.monotonic() + timeout_seconds
    streams = (process.stdin, process.stdout, process.stderr)
    try:
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
        chunks: dict[str, list[bytes]] = {"stdout": [], "stderr": []}
        total = 0
        input_offset = 0
        with selectors.DefaultSelector() as selector:
            if encoded:
                selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            else:
                process.stdin.close()
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                for key, _ in selector.select(min(remaining, 0.1)):
                    if key.data == "stdin":
                        try:
                            written = os.write(
                                key.fileobj.fileno(),
                                encoded[input_offset : input_offset + 65_536],
                            )
                        except BrokenPipeError:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                            continue
                        except BlockingIOError:
                            continue
                        input_offset += written
                        if input_offset == len(encoded):
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                        continue
                    try:
                        chunk = os.read(key.fileobj.fileno(), 65_536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > max_output_bytes:
                        raise OverflowError
                    chunks[key.data].append(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        process.wait(timeout=remaining)
        return b"".join(chunks["stdout"]), b"".join(chunks["stderr"])
    except (TimeoutError, subprocess.TimeoutExpired) as exc:
        _kill_process_group(process)
        process.wait()
        raise ExternalAdapterError(
            "ADAPTER_TIMEOUT",
            f"adapter exceeded {timeout_seconds:g} seconds",
        ) from exc
    except OverflowError as exc:
        _kill_process_group(process)
        process.wait()
        raise ExternalAdapterError(
            "OUTPUT_LIMIT_EXCEEDED",
            f"adapter output exceeded {max_output_bytes} bytes",
        ) from exc
    except Exception:
        _kill_process_group(process)
        process.wait()
        raise
    finally:
        for stream in streams:
            if not stream.closed:
                stream.close()
