"""mini_agent implementation of the neutral evaluation Provider contract."""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
from typing import Any

import minimal_agent
from minimal_agent.runtime import (
    DeepSeekModelClient,
    OpenAIModelClient,
)
from minimal_agent.runtime.model_client import (
    InvalidModelOutputError,
    ModelInvocationError,
    ModelTimeoutError,
)

from ...capabilities import (
    CapabilityBundle,
    CapabilityBundleError,
    CapabilityRegistry,
)
from ...dataset_validator import validate_dataset
from ...diagnostics import DiagnosticRegistry
from ...mini_agent_adapter import MiniAgentAdapter
from ...provider import (
    AdapterOutput,
    EvaluationPreflightError,
    ProviderExceptionInfo,
    ensure_capability_compatibility,
)
from ...runtime_factory import (
    ModelClientFactory,
    Runtime,
    RuntimeFactory,
    StateObservationError,
    ToolRegistryFactory,
    model_metadata,
)
from ...schemas import (
    DatasetBundle,
    ExecutionProfile,
    ExecutionSpec,
    TestScope,
    ValidationIssue,
    ValidationReport,
)
from ...tool_catalog import (
    ExecutionProfileError,
    ToolCatalog,
    ToolCatalogError,
)
from .capability_adapter import load_mini_agent_capability_bundle
from .diagnostics import (
    MiniAgentParameterDiagnosticRule,
    MiniAgentQueryUserDiagnosticRule,
)
from .runtime_binding import MiniAgentRuntimeBindingFactory
from .state_environment import GIFT_CONTRACT, GiftSQLiteEnvironment
from .trace_rules import MiniAgentConfirmationTraceRule


def model_client_factory_from_env() -> ModelClientFactory:
    provider = os.getenv("MODEL_PROVIDER", "openai").strip().lower()
    clients = {
        "openai": OpenAIModelClient,
        "deepseek": DeepSeekModelClient,
    }
    if provider not in clients:
        raise ValueError("MODEL_PROVIDER must be one of: deepseek, openai")
    client_class = clients[provider]
    return lambda execution: client_class.from_env(
        timeout_seconds=execution.timeout_seconds
    )


class MiniAgentProvider:
    provider_id = "mini_agent"
    evidence_rules_version = "mini-agent-events-v1"

    def __init__(
        self,
        capabilities: CapabilityRegistry,
        model_client_factory: ModelClientFactory,
        *,
        execution_profiles: dict[str, ExecutionProfile],
        current_capabilities: CapabilityRegistry | None = None,
        tool_registry_factory: ToolRegistryFactory | None = None,
        environment: str | None = None,
    ) -> None:
        self.capabilities = capabilities
        self.tools = ToolCatalog.from_registry(
            capabilities,
            profiles=execution_profiles,
        )
        self.diagnostics = DiagnosticRegistry()
        self.diagnostics.register("query_user", MiniAgentQueryUserDiagnosticRule())
        self.diagnostics.register(
            "query_gift",
            MiniAgentParameterDiagnosticRule("query_gift"),
        )
        self.trace_rules = (MiniAgentConfirmationTraceRule(),)
        if environment not in {None, "gift_sqlite_v1"}:
            raise EvaluationPreflightError("ENVIRONMENT_UNSUPPORTED", str(environment))
        self.environment_state_available = environment is not None
        self.environment_version = environment
        if environment:
            _validate_environment_contract(capabilities, execution_profiles)
        environment_factory = GiftSQLiteEnvironment if environment else None
        if environment_factory is not None and tool_registry_factory is not None:
            raise ValueError(
                "environment and tool_registry_factory are mutually exclusive"
            )
        runtime_binding = None
        if (
            environment_factory is None
            and tool_registry_factory is None
            and capabilities.bundle.bundle_format_version == "3.0"
        ):
            runtime_binding = MiniAgentRuntimeBindingFactory(capabilities)
            tool_registry_factory = runtime_binding
        self._factory = RuntimeFactory(
            model_client_factory,
            tool_registry_factory,
            environment_factory=environment_factory,
        )
        if current_capabilities is not None:
            ensure_capability_compatibility(
                capabilities,
                current_capabilities,
                expected_provider_id=self.provider_id,
            )
        elif environment_factory is not None:
            verifier = MiniAgentRuntimeBindingFactory(capabilities)
            for profile in execution_profiles.values():
                fixture = environment_factory(frozenset(profile.allowed_tools))
                try:
                    verifier.verify_registry(fixture.registry)
                finally:
                    fixture.cleanup()
        elif runtime_binding is not None:
            profile_tools = {
                frozenset(profile.allowed_tools)
                for profile in execution_profiles.values()
            }
            for allowed_tools in profile_tools:
                runtime_binding(allowed_tools)
        else:
            ensure_capability_compatibility(
                capabilities,
                _load_current_capabilities(),
                expected_provider_id=self.provider_id,
            )
        try:
            self.provider_version = importlib.metadata.version("minimal-agent")
        except importlib.metadata.PackageNotFoundError:
            self.provider_version = "unknown"

    @classmethod
    def from_dataset(
        cls,
        dataset: DatasetBundle,
        model_client_factory: ModelClientFactory,
        *,
        bundle_override: str | Path | None = None,
        verify_current: bool = True,
        environment: str | None = None,
    ) -> MiniAgentProvider:
        bundle_path = bundle_override or dataset.capability_bundle_path
        if bundle_path is None:
            raise EvaluationPreflightError(
                "CAPABILITY_BUNDLE_REQUIRED",
                "dataset has no resolved capability bundle",
                evidence_path=dataset.manifest_path,
            )
        try:
            bundle = load_mini_agent_capability_bundle(
                Path(bundle_path),
                expected_sha256=(
                    dataset.capability_bundle_sha256
                    if dataset.capability_bundle_path is not None
                    else None
                ),
            )
            if dataset.capability_bundle_path is not None:
                if (
                    dataset.capability_bundle_sha256 is not None
                    and bundle.capability_bundle_sha256
                    != dataset.capability_bundle_sha256
                ):
                    raise EvaluationPreflightError(
                        "CAPABILITY_BUNDLE_INVALID",
                        "dataset capability bundle hash mismatch",
                        evidence_path=str(bundle_path),
                    )
            else:
                _verify_legacy_snapshot_bindings(dataset, bundle)
            registry = CapabilityRegistry(bundle)
            return cls(
                registry,
                model_client_factory,
                execution_profiles=dataset.execution_profiles,
                current_capabilities=None if verify_current else registry,
                environment=environment,
            )
        except EvaluationPreflightError:
            raise
        except ExecutionProfileError as exc:
            raise EvaluationPreflightError(
                "EXECUTION_PROFILE_INVALID",
                str(exc),
                evidence_path=dataset.manifest_path,
            ) from exc
        except (CapabilityBundleError, ToolCatalogError, OSError, ValueError) as exc:
            raise EvaluationPreflightError(
                "CAPABILITY_BUNDLE_INVALID",
                str(exc),
                evidence_path=str(bundle_path),
            ) from exc

    def create_runtime(
        self,
        execution: ExecutionSpec,
        session_id: str,
        scope: TestScope,
        *,
        evidence_sink=None,
    ) -> Runtime:
        self.validate_execution(execution, scope)
        available = self.tools.tools_for_profile(execution.tool_profile)
        allowed = (
            frozenset(execution.allowed_tools)
            if execution.allowed_tools is not None
            else available
        )
        if scope == "module":
            allowed = frozenset()
        return self._factory.create(
            execution,
            session_id=session_id,
            allowed_tools=allowed,
            evidence_sink=evidence_sink,
        )

    def create_observed_runtime(self, execution, session_id, scope, sink):
        return self.create_runtime(
            execution,
            session_id,
            scope,
            evidence_sink=sink,
        )

    def evidence_issues(self, output, events):
        valid = [e for e in events if e.get("validation_status") == "VALID"]
        issues = []
        if output.module_output is not None and not any(
            e["event_type"] == "intent_decided" for e in valid
        ):
            issues.append({"kind": "partial", "code": "INTENT_EVIDENCE_MISSING"})
        for turn in output.turns:
            observed = [e for e in valid if e.get("run_id") == turn["run_id"]]
            if not any(e["event_type"] == "run_finished" for e in observed):
                issues.append({"kind": "partial", "code": "RUN_END_EVIDENCE_MISSING"})
            for call in turn.get("tool_calls", []):
                matches = [
                    e
                    for e in observed
                    if e["payload"].get("call_id") == call["call_id"]
                ]
                if not any(e["event_type"] == "tool_requested" for e in matches):
                    issues.append({"kind": "partial", "code": "TOOL_EVIDENCE_MISSING"})
        return issues

    def run_module(self, runtime: object, execution: ExecutionSpec) -> AdapterOutput:
        resolved = _runtime(runtime)
        try:
            return MiniAgentAdapter(resolved).run_module(execution)
        except Exception as exc:
            exc.__dict__["adapter_output"] = AdapterOutput(
                None,
                [],
                None,
                [],
                None,
                (
                    resolved.agent.intent_trace_snapshot()
                    if resolved.evidence_sink is None
                    else None
                ),
            )
            raise

    def run_full(
        self, runtime: object, execution: ExecutionSpec, scope: TestScope
    ) -> AdapterOutput:
        return MiniAgentAdapter(_runtime(runtime)).run_full(execution, scope)

    def cleanup(self, runtime: object) -> None:
        _runtime(runtime).cleanup()

    def classify_exception(self, exc: Exception) -> ProviderExceptionInfo:
        if isinstance(exc, StateObservationError):
            status = "EVALUATOR_ERROR"
        elif isinstance(exc, ModelTimeoutError):
            status = "MODEL_TIMEOUT"
        elif isinstance(exc, InvalidModelOutputError):
            status = "MODEL_OUTPUT_ERROR"
        elif isinstance(exc, ModelInvocationError):
            status = "MODEL_INVOCATION_ERROR"
        else:
            status = "AGENT_EXCEPTION"
        return ProviderExceptionInfo(
            execution_status=status,
            exception=_exception_payload(exc),
            output=getattr(exc, "adapter_output", None),
        )

    def runtime_metadata(self, runtime: object) -> dict[str, Any]:
        metadata = model_metadata(_runtime(runtime).model_client)
        if self.environment_version:
            metadata["evaluation_environment"] = self.environment_version
            metadata["state_source"] = "provider_sqlite"
        return metadata

    def tool_version(self, runtime: object) -> str:
        _runtime(runtime)
        version = self.capabilities.bundle.capability_bundle_sha256
        return (
            f"{version}:{self.environment_version}"
            if self.environment_version
            else version
        )

    @staticmethod
    def validate_execution(execution: ExecutionSpec, scope: TestScope) -> None:
        _validate_execution(execution, scope)


class MiniAgentProviderFactory:
    provider_id = "mini_agent"

    def fingerprint_sources(self) -> list[Path]:
        return [
            Path(__file__).resolve().parents[2],
            Path(minimal_agent.__file__).parent,
        ]

    def validate_dataset(
        self,
        dataset: DatasetBundle,
        *,
        bundle_override: str | Path | None = None,
        environment: str | None = None,
        **_: Any,
    ) -> ValidationReport:
        bundle_path = bundle_override or dataset.capability_bundle_path
        if bundle_path is None:
            return validate_dataset(dataset)
        try:
            bundle = load_mini_agent_capability_bundle(
                Path(bundle_path),
                expected_sha256=(
                    dataset.capability_bundle_sha256
                    if dataset.capability_bundle_path is not None
                    else None
                ),
            )
            if dataset.capability_bundle_path is not None:
                if (
                    dataset.capability_bundle_sha256 is not None
                    and bundle.capability_bundle_sha256
                    != dataset.capability_bundle_sha256
                ):
                    raise EvaluationPreflightError(
                        "CAPABILITY_BUNDLE_INVALID",
                        "dataset capability bundle hash mismatch",
                    )
            else:
                _verify_legacy_snapshot_bindings(dataset, bundle)
            registry = CapabilityRegistry(bundle)
            tools = ToolCatalog.from_registry(
                registry,
                profiles=dataset.execution_profiles,
            )
            if environment not in {None, "gift_sqlite_v1"}:
                raise EvaluationPreflightError(
                    "ENVIRONMENT_UNSUPPORTED", str(environment)
                )
            if environment:
                _validate_environment_contract(registry, dataset.execution_profiles)
            report = validate_dataset(
                dataset,
                registry,
                tools,
                environment_state_available=environment is not None,
            )
            for case in dataset.cases:
                try:
                    _validate_execution(case.execution, case.test_scope)
                    if (
                        environment
                        and case.execution.tool_profile in dataset.execution_profiles
                        and set(tools.tools_for_profile(case.execution.tool_profile))
                        - {
                            "add_gift_to_backpack",
                        }
                    ):
                        raise EvaluationPreflightError(
                            "ENVIRONMENT_UNSUPPORTED_TOOLS",
                            "gift_sqlite_v1 supports add_gift_to_backpack only",
                        )
                except EvaluationPreflightError as exc:
                    report.issues.append(
                        ValidationIssue(
                            case_id=case.case_id,
                            field_path="execution",
                            message=str(exc),
                        )
                    )
            report.valid = not report.issues
            return report
        except (
            EvaluationPreflightError,
            CapabilityBundleError,
            ToolCatalogError,
        ) as exc:
            return ValidationReport(
                valid=False,
                issues=[
                    ValidationIssue(
                        case_id=None,
                        field_path="capability_bundle",
                        message=str(exc),
                    )
                ],
            )

    def create(
        self,
        dataset: DatasetBundle,
        model_client_factory: ModelClientFactory | None = None,
        *,
        bundle_override: str | Path | None = None,
        verify_current: bool = True,
        environment: str | None = None,
    ) -> MiniAgentProvider:
        return MiniAgentProvider.from_dataset(
            dataset,
            model_client_factory or model_client_factory_from_env(),
            bundle_override=bundle_override,
            verify_current=verify_current,
            environment=environment,
        )


def _validate_environment_contract(capabilities, profiles) -> None:
    if not any(
        GIFT_CONTRACT.name in profile.allowed_tools for profile in profiles.values()
    ):
        return
    document = next(
        (
            document
            for document in capabilities.bundle.documents
            if document.snapshot_id == GIFT_CONTRACT.snapshot_id
        ),
        None,
    )
    if (
        document is None
        or document.contract_version != GIFT_CONTRACT.version
        or document.payload.get("implementation_profile") != "test_fixture"
        or document.payload.get("function_schema", {}).get("parameters")
        != GIFT_CONTRACT.arguments_model.model_json_schema()
    ):
        raise EvaluationPreflightError(
            "ENVIRONMENT_CONTRACT_MISMATCH",
            "gift_sqlite_v1 requires the frozen gift-sqlite-v1 test-fixture contract",
        )


def _validate_execution(execution: ExecutionSpec, scope: TestScope) -> None:
    if scope in {"module", "link"} and execution.user_responses:
        raise EvaluationPreflightError(
            "EXECUTION_BOUNDARY_UNSUPPORTED",
            f"{scope} scope supports one call, not user_responses; use end_to_end",
        )
    if execution.fault_injection:
        raise EvaluationPreflightError(
            "FAULT_INJECTION_UNSUPPORTED",
            "mini_agent fault injection is not implemented",
        )


def _runtime(value: object) -> Runtime:
    if not isinstance(value, Runtime):
        raise TypeError("MiniAgentProvider received an incompatible runtime")
    return value


def _load_current_capabilities() -> CapabilityRegistry:
    root = Path(minimal_agent.__file__).resolve().parents[2] / "capabilities"
    return CapabilityRegistry(load_mini_agent_capability_bundle(root))


def _verify_legacy_snapshot_bindings(
    dataset: DatasetBundle, bundle: CapabilityBundle
) -> None:
    expected = {
        item.get("snapshot_id"): item.get("snapshot_sha256")
        for item in dataset.legacy_capability_snapshots
        if isinstance(item, dict)
    }
    actual = {item.snapshot_id: item.snapshot_sha256 for item in bundle.documents}
    mismatched = [
        snapshot_id
        for snapshot_id, digest in expected.items()
        if snapshot_id not in actual or actual[snapshot_id] != digest
    ]
    if not expected or mismatched:
        raise EvaluationPreflightError(
            "CAPABILITY_BUNDLE_INVALID",
            "legacy capability snapshot bindings do not match explicit override",
            evidence_path=dataset.manifest_path,
        )


def _exception_payload(exc: Exception) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(exc),
    }
    diagnostic = getattr(exc, "diagnostic", None)
    if isinstance(diagnostic, dict) and diagnostic:
        payload["diagnostic"] = diagnostic
    return payload
