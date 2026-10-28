"""Agent-neutral provider contracts and extension points."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from agent_trace_sdk import InspectEvidenceSink

from .capabilities import CapabilityRegistry
from .errors import EvaluationPreflightError
from .phase2_schemas import NormalizedTraceEvent, TraceIssue
from .schemas import (
    AssertionResult,
    CaseResult,
    Diagnosis,
    EvalCase,
    ExecutionSpec,
    ExecutionStatus,
    StrictModel,
    TestScope,
)
from .tool_catalog import ToolCatalog


@dataclass(frozen=True)
class AdapterOutput:
    module_output: dict[str, Any] | None
    turns: list[dict[str, Any]]
    before_snapshot: dict[str, Any] | None
    turn_snapshots: list[dict[str, Any]]
    snapshot: dict[str, Any] | None
    trace_events: list[dict[str, Any]] | None = None
    evidence_status: str | None = None
    execution_completed: bool = True
    evidence_manifest: dict[str, Any] | None = None
    observations: dict[str, Any] | None = None


class DiagnosticOutcome(StrictModel):
    diagnoses: list[Diagnosis]
    consumed_assertions: set[str]


class DiagnosticRule(Protocol):
    def diagnose(
        self,
        case: EvalCase,
        failed: Mapping[str, AssertionResult],
        registry: CapabilityRegistry,
    ) -> DiagnosticOutcome | None: ...


class DiagnosticRouter(Protocol):
    def rules_for(
        self,
        case: EvalCase,
        assertions: Sequence[AssertionResult],
    ) -> tuple[DiagnosticRule, ...]: ...


class TraceRule(Protocol):
    def analyze(
        self,
        timeline: Sequence[NormalizedTraceEvent],
        case: CaseResult,
    ) -> Sequence[TraceIssue]: ...


class ProviderFactory(Protocol):
    def create(
        self,
        dataset: Any,
        model_client_factory: Any = None,
        **kwargs: Any,
    ) -> EvaluationProvider: ...


class ProviderExceptionInfo(StrictModel):
    execution_status: ExecutionStatus
    exception: dict[str, Any]
    output: AdapterOutput | None = None


class ObservedRuntimeProvider(Protocol):
    """Optional extension; legacy EvaluationProvider implementations need not adopt it.

    The runner owns the Sink for the entire Trial, including all turns. Providers
    inject it into their Agent and must not close it after individual turns.
    """

    def create_observed_runtime(
        self,
        execution: ExecutionSpec,
        session_id: str,
        scope: TestScope,
        sink: InspectEvidenceSink,
    ) -> object: ...


@runtime_checkable
class EvaluationProvider(Protocol):
    provider_id: str
    provider_version: str
    capabilities: CapabilityRegistry
    tools: ToolCatalog
    diagnostics: DiagnosticRouter

    def create_runtime(
        self,
        execution: ExecutionSpec,
        session_id: str,
        scope: TestScope,
    ) -> object: ...

    def run_module(
        self, runtime: object, execution: ExecutionSpec
    ) -> AdapterOutput: ...

    def run_full(
        self, runtime: object, execution: ExecutionSpec, scope: TestScope
    ) -> AdapterOutput: ...

    def cleanup(self, runtime: object) -> None: ...

    def classify_exception(self, exc: Exception) -> ProviderExceptionInfo: ...

    def runtime_metadata(self, runtime: object) -> dict[str, Any]: ...

    def tool_version(self, runtime: object) -> str: ...


def ensure_capability_compatibility(
    frozen: CapabilityRegistry,
    current: CapabilityRegistry,
    *,
    expected_provider_id: str,
) -> None:
    differences: list[str] = []
    if frozen.bundle.provider_id != expected_provider_id:
        differences.append(
            f"frozen provider {frozen.bundle.provider_id!r} != {expected_provider_id!r}"
        )
    if current.bundle.provider_id != expected_provider_id:
        differences.append(
            f"current provider {current.bundle.provider_id!r} != "
            f"{expected_provider_id!r}"
        )

    frozen_by_id = {item.snapshot_id: item for item in frozen.bundle.documents}
    current_by_id = {item.snapshot_id: item for item in current.bundle.documents}
    if set(frozen_by_id) != set(current_by_id):
        differences.append("capability snapshot IDs differ")
    for snapshot_id in sorted(set(frozen_by_id) & set(current_by_id)):
        before = frozen_by_id[snapshot_id]
        after = current_by_id[snapshot_id]
        before_major = _contract_major(before.contract_version)
        after_major = _contract_major(after.contract_version)
        if (
            before_major is not None
            and after_major is not None
            and before_major != after_major
        ):
            differences.append(f"{snapshot_id} contract major differs")
        schema_keys = (
            ("input_schema", "output_schema")
            if before.snapshot_type == "module"
            else (("parameters_schema",) if before.capability_id else ())
        )
        for key in schema_keys:
            if before.payload.get(key) != after.payload.get(key):
                differences.append(f"{snapshot_id}.{key} differs")
    if differences:
        raise EvaluationPreflightError(
            "CAPABILITY_CONTRACT_MISMATCH",
            "; ".join(differences),
            evidence_path=frozen.bundle.root,
        )


def _contract_major(value: str) -> int | None:
    match = re.search(r"(?:^|[-_])v?(\d+)\.\d+(?:\.|$)", value)
    return int(match.group(1)) if match else None
