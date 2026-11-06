"""Execution bridge from an immutable CompiledSuite to the existing Runner."""

from __future__ import annotations

from typing import Any

from .contracts.compiler import compiled_snapshot
from .contracts.models import CompiledSuite
from .contracts.store import canonical_json_bytes, sha256_bytes
from .errors import EvaluationPreflightError
from .plugins.catalog import PluginCatalog, PluginCatalogError
from .plugins.models import PluginReference
from .runner import run_provider_evaluation
from .schemas import EvaluationRunResult


def execute_compiled_suite(
    compiled: CompiledSuite,
    catalog: PluginCatalog,
    *,
    model_client_factory: Any = None,
    legacy_judge_client: Any = None,
    output_dir=None,
) -> EvaluationRunResult:
    try:
        current_snapshot = compiled_snapshot(compiled)
    except (OSError, ValueError) as exc:
        raise EvaluationPreflightError(
            "COMPILED_SUITE_INTEGRITY_ERROR",
            f"compiled Suite inputs are unavailable: {exc}",
        ) from exc
    if (
        current_snapshot != compiled.compiled_suite_snapshot
        or sha256_bytes(canonical_json_bytes(current_snapshot))
        != compiled.compiled_suite_sha256
    ):
        raise EvaluationPreflightError(
            "COMPILED_SUITE_INTEGRITY_ERROR",
            "compiled Suite contents changed after compilation",
        )
    layered = {
        item.kind for item in compiled.plugins
        if item.kind in {"environment", "tool_router", "user_simulator", "scorer"}
    }
    if layered:
        raise EvaluationPreflightError(
            "LAYERED_HARNESS_REQUIRED",
            "The legacy Provider bridge cannot consume layered plugins: "
            f"{', '.join(sorted(layered))}. Use eval_framework.harness with "
            "explicit environment, router, simulator and trusted scoring instead.",
        )
    provider_snapshot = next(
        (item for item in compiled.plugins if item.kind == "provider"),
        None,
    )
    if provider_snapshot is None:
        raise EvaluationPreflightError(
            "COMPILED_SUITE_INVALID",
            "compiled Suite has no Provider plugin snapshot",
        )
    try:
        registration = catalog.resolve(
            PluginReference(
                plugin_id=provider_snapshot.plugin_id,
                version=provider_snapshot.version,
                config=provider_snapshot.config,
            ),
            expected_kind="provider",
            contract_version=compiled.schema_version,
            field_path="$.provider",
        )
    except PluginCatalogError as exc:
        raise EvaluationPreflightError(exc.code, str(exc)) from exc
    if (
        registration.descriptor.implementation_fingerprint
        != provider_snapshot.implementation_fingerprint
    ):
        raise EvaluationPreflightError(
            "PLUGIN_FINGERPRINT_MISMATCH",
            f"Provider plugin {provider_snapshot.plugin_id!r} "
            "changed after compilation",
        )
    provider = registration.implementation.create(
        compiled.dataset,
        model_client_factory,
        **dict(registration.config),
        **compiled.runtime_provider_config,
    )
    result = run_provider_evaluation(
        compiled.dataset,
        compiled.run_config,
        provider,
        judge_client=legacy_judge_client,
        output_dir=output_dir,
    )
    plugin_fingerprints = [
        {
            "kind": item.kind,
            "plugin_id": item.plugin_id,
            "version": item.version,
            "implementation_fingerprint": item.implementation_fingerprint,
        }
        for item in compiled.plugins
    ]
    contract_fingerprints = [
        {
            "contract_id": item.contract_id,
            "version": item.version,
            "sha256": item.sha256,
        }
        for item in compiled.contracts
    ]
    return result.model_copy(
        update={
            "compiled_suite_sha256": compiled.compiled_suite_sha256,
            "compiled_suite_snapshot": compiled.compiled_suite_snapshot,
            "plugin_fingerprints": plugin_fingerprints,
            "contract_fingerprints": contract_fingerprints,
        }
    )
