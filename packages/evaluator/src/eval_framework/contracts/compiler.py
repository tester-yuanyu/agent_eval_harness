"""Deterministic Suite compilation before any Agent runtime is created."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from ..errors import EvaluationPreflightError
from ..plugins.catalog import (
    PluginCatalog,
    PluginCatalogError,
    PluginRegistration,
)
from ..schemas import DatasetBundle, ValidationReport
from .models import (
    CompilationIssue,
    CompiledSuite,
    ContractReference,
    DatasetSource,
    LoadedSuiteDefinition,
    ResolvedContract,
    ResolvedPluginSnapshot,
    ResolvedSource,
    SourceFingerprint,
    SuiteDefinition,
)
from .store import (
    ContractStore,
    ContractStoreError,
    canonical_json_bytes,
    sha256_bytes,
)


class SuiteCompilationError(EvaluationPreflightError):
    def __init__(self, issues: list[CompilationIssue]) -> None:
        self.issues = tuple(
            sorted(issues, key=lambda item: (item.field_path, item.code, item.message))
        )
        super().__init__(
            "SUITE_COMPILATION_FAILED",
            "; ".join(
                f"{item.field_path}: {item.code}: {item.message}"
                for item in self.issues
            ),
            evidence_refs=[ref for item in self.issues for ref in item.evidence_refs],
        )


def load_suite_definition(path: str | Path) -> LoadedSuiteDefinition:
    source_path = Path(path).expanduser().resolve()
    try:
        raw = source_path.read_bytes()
        value = json.loads(raw)
        definition = SuiteDefinition.model_validate(value)
    except ValidationError as exc:
        issues = []
        for detail in exc.errors(include_url=False):
            location = list(detail.get("loc", ()))
            value = detail.get("input")
            if location and location[-1] == "path" and isinstance(value, str):
                candidate = PurePosixPath(value)
                if candidate.is_absolute() or ".." in candidate.parts:
                    field_path = "$" + "".join(
                        f"[{part}]" if isinstance(part, int) else f".{part}"
                        for part in location
                    )
                    issues.append(
                        CompilationIssue(
                            code="SOURCE_PATH_OUTSIDE_ROOT",
                            field_path=field_path,
                            message=f"source {value!r} resolves outside the Suite root",
                            evidence_refs=[value],
                        )
                    )
        if not issues:
            issues = [
                CompilationIssue(
                    code="SUITE_DEFINITION_INVALID",
                    field_path="$",
                    message=str(exc),
                    evidence_refs=[str(source_path)],
                )
            ]
        raise SuiteCompilationError(issues) from exc
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise SuiteCompilationError(
            [
                CompilationIssue(
                    code="SUITE_DEFINITION_INVALID",
                    field_path="$",
                    message=str(exc),
                    evidence_refs=[str(source_path)],
                )
            ]
        ) from exc
    return LoadedSuiteDefinition(
        definition=definition,
        source_path=source_path,
        root=source_path.parent,
        source_sha256=sha256_bytes(raw),
        origin="file",
    )


def _plugin_issue(exc: PluginCatalogError) -> CompilationIssue:
    return CompilationIssue(
        code=exc.code,
        field_path=exc.field_path or "$",
        message=str(exc),
    )


def _store_issue(
    exc: ContractStoreError,
    *,
    field_path: str,
) -> CompilationIssue:
    return CompilationIssue(
        code=exc.code,
        field_path=field_path,
        message=str(exc),
        evidence_refs=exc.evidence_refs,
    )


def _contract_references(
    definition: SuiteDefinition,
) -> list[tuple[str, ContractReference]]:
    names = (
        "capability_bundle",
        "assertion_profile",
        "trace_profile",
        "judge_profile",
        "report_profile",
        "gate_policy",
    )
    return [
        (name, reference)
        for name in names
        if (reference := getattr(definition, name)) is not None
    ]


def _runtime_provider_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(config)
    override = snapshot.pop("bundle_override", None)
    if override is not None:
        root = Path(override).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise OSError(f"capability bundle override is not a directory: {root}")
        files = []
        for candidate in sorted(root.rglob("*")):
            if not candidate.is_file():
                continue
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise OSError(
                    f"capability bundle file escapes override root: {candidate}"
                )
            files.append(
                {
                    "path": str(candidate.relative_to(root)),
                    "sha256": sha256_bytes(candidate.read_bytes()),
                }
            )
        snapshot["bundle_override_sha256"] = sha256_bytes(canonical_json_bytes(files))
    return snapshot


def compiled_snapshot(compiled: CompiledSuite) -> dict[str, Any]:
    """Rebuild the canonical identity from the current compiled values."""
    dataset_snapshot = compiled.dataset.model_dump(mode="json")
    for path_field in ("path", "manifest_path", "capability_bundle_path"):
        dataset_snapshot.pop(path_field, None)
    return {
        "schema_version": compiled.schema_version,
        "suite_id": compiled.suite_id,
        "suite_version": compiled.suite_version,
        "lifecycle_state": compiled.lifecycle_state,
        "definition": compiled.definition,
        "plugins": [item.model_dump(mode="json") for item in compiled.plugins],
        "contracts": [item.model_dump(mode="json") for item in compiled.contracts],
        "sources": [item.model_dump(mode="json") for item in compiled.sources],
        "run_config": compiled.run_config.model_dump(mode="json"),
        "dataset": dataset_snapshot,
        "runtime_provider_config": _runtime_provider_snapshot(
            compiled.runtime_provider_config
        ),
    }


def compile_suite(
    definition: LoadedSuiteDefinition,
    catalog: PluginCatalog,
    contract_store: ContractStore,
) -> CompiledSuite:
    suite = definition.definition
    issues: list[CompilationIssue] = []
    if definition.origin == "file" and (
        suite.judge_profile is not None or suite.run_config.judge is not None
    ):
        issues.append(
            CompilationIssue(
                code="PROFILE_STAGE_NOT_MIGRATED",
                field_path="$.judge_profile",
                message="authored Suite Judge profiles migrate in milestone 2",
            )
        )
    registrations: dict[str, PluginRegistration[Any]] = {}
    for name, reference, kind in (
        ("dataset_loader", suite.dataset_loader, "dataset_loader"),
        ("provider", suite.provider, "provider"),
    ):
        try:
            registrations[name] = catalog.resolve(
                reference,
                expected_kind=kind,
                contract_version=suite.schema_version,
                field_path=f"$.{name}",
            )
        except PluginCatalogError as exc:
            issues.append(_plugin_issue(exc))

    sources: list[ResolvedSource] = []
    for index, source in enumerate(suite.dataset_sources):
        try:
            sources.append(contract_store.resolve_source(source))
        except ContractStoreError as exc:
            issues.append(
                _store_issue(exc, field_path=f"$.dataset_sources[{index}].path")
            )

    contracts: list[ResolvedContract] = []
    for name, reference in _contract_references(suite):
        try:
            contracts.append(contract_store.load_contract(reference))
        except ContractStoreError as exc:
            issues.append(_store_issue(exc, field_path=f"$.{name}.path"))

    dependency_sources: list[ResolvedSource] = []
    capability_contract = next(
        (
            item
            for item in contracts
            if suite.capability_bundle is not None
            and item.contract_id == suite.capability_bundle.contract_id
        ),
        None,
    )
    if capability_contract is not None:
        content = capability_contract.content
        is_agent_contract = (
            PurePosixPath(capability_contract.logical_path).name == "agent.json"
            and content.get("snapshot_type") == "agent"
            and content.get("snapshot_format_version") == "3.0"
        )
        if is_agent_contract:
            required = {
                "agent_id": content.get("agent_id"),
                "snapshot_format_version": content.get(
                    "snapshot_format_version"
                ),
                "capability_bundle_sha256": content.get(
                    "capability_bundle_sha256"
                ),
            }
        else:
            required = {
                "provider_id": content.get("provider_id"),
                "bundle_format_version": content.get("bundle_format_version"),
                "capability_bundle_sha256": content.get(
                    "capability_bundle_sha256"
                ),
                "files": content.get("files"),
            }
        invalid_fields = []
        for name, value in required.items():
            if name == "files":
                if not isinstance(value, list):
                    invalid_fields.append(name)
            elif not isinstance(value, str) or not value:
                invalid_fields.append(name)
        bundle_hash = required["capability_bundle_sha256"]
        if isinstance(bundle_hash, str) and (
            len(bundle_hash) != 64
            or any(character not in "0123456789abcdef" for character in bundle_hash)
        ):
            invalid_fields.append("capability_bundle_sha256")
        if invalid_fields:
            issues.append(
                CompilationIssue(
                    code="CAPABILITY_CONTRACT_INVALID",
                    field_path="$.capability_bundle",
                    message="invalid capability contract fields: "
                    f"{sorted(set(invalid_fields))}",
                )
            )
        elif not is_agent_contract:
            files = required["files"]
            assert isinstance(files, list)
            contract_parent = PurePosixPath(capability_contract.logical_path).parent
            for index, entry in enumerate(files):
                field_path = f"$.capability_bundle.files[{index}]"
                if not isinstance(entry, dict):
                    issues.append(
                        CompilationIssue(
                            code="CONTRACT_INVALID",
                            field_path=field_path,
                            message="capability bundle file entry must be an object",
                        )
                    )
                    continue
                relative = entry.get("path")
                digest = entry.get("sha256")
                if not isinstance(relative, str) or not isinstance(digest, str):
                    issues.append(
                        CompilationIssue(
                            code="CONTRACT_INVALID",
                            field_path=field_path,
                            message="capability bundle file requires path and sha256",
                        )
                    )
                    continue
                logical_path = str(contract_parent / PurePosixPath(relative))
                try:
                    dependency_sources.append(
                        contract_store.resolve_source(
                            DatasetSource(path=logical_path, sha256=digest)
                        )
                    )
                except (ContractStoreError, ValidationError) as exc:
                    if isinstance(exc, ContractStoreError):
                        suffix = (
                            "sha256"
                            if exc.code == "SOURCE_FINGERPRINT_MISMATCH"
                            else "path"
                        )
                        issues.append(
                            _store_issue(exc, field_path=f"{field_path}.{suffix}")
                        )
                    else:
                        issues.append(
                            CompilationIssue(
                                code="SOURCE_PATH_OUTSIDE_ROOT",
                                field_path=f"{field_path}.path",
                                message=str(exc),
                                evidence_refs=[relative],
                            )
                        )

    try:
        runtime_provider_snapshot = _runtime_provider_snapshot(
            definition.runtime_provider_config
        )
    except OSError as exc:
        issues.append(
            CompilationIssue(
                code="SOURCE_NOT_FOUND",
                field_path="$.runtime_provider_config.bundle_override",
                message=str(exc),
            )
        )

    if issues:
        raise SuiteCompilationError(issues)

    loader_registration = registrations["dataset_loader"]
    try:
        dataset = loader_registration.implementation.load(
            sources,
            filters=suite.run_config.filters,
            config=loader_registration.config,
        )
    except Exception as exc:
        raise SuiteCompilationError(
            [
                CompilationIssue(
                    code="DATASET_LOAD_FAILED",
                    field_path="$.dataset_sources",
                    message=str(exc),
                    evidence_refs=[source.logical_path for source in sources],
                )
            ]
        ) from exc
    if not isinstance(dataset, DatasetBundle):
        raise SuiteCompilationError(
            [
                CompilationIssue(
                    code="LOADER_OUTPUT_INVALID",
                    field_path="$.dataset_loader",
                    message="dataset Loader did not return DatasetBundle",
                )
            ]
        )

    if (
        definition.origin == "file"
        and suite.capability_bundle is None
        and dataset.capability_bundle_path is not None
    ):
        raise SuiteCompilationError(
            [
                CompilationIssue(
                    code="CAPABILITY_CONTRACT_REQUIRED",
                    field_path="$.capability_bundle",
                    message=(
                        "authored Suites must declare the capability contract "
                        "used by execution"
                    ),
                )
            ]
        )

    provider_registration = registrations["provider"]
    provider_id = getattr(provider_registration.implementation, "provider_id", None)
    capability = capability_contract
    capability_provider = None
    if capability is not None:
        capability_provider = capability.content.get("provider_id")
        if capability_provider is None:
            capability_provider = capability.content.get("agent_id")
    identities = {
        item
        for item in (dataset.provider_id, provider_id, capability_provider)
        if isinstance(item, str) and item and item != "unknown"
    }
    if len(identities) > 1:
        raise SuiteCompilationError(
            [
                CompilationIssue(
                    code="CAPABILITY_CONTRACT_MISMATCH",
                    field_path="$.provider",
                    message=f"provider identities disagree: {sorted(identities)}",
                )
            ]
        )

    if capability is not None:
        bundle_hash = capability.content.get("capability_bundle_sha256")
        if isinstance(bundle_hash, str):
            if (
                dataset.capability_bundle_sha256 is not None
                and dataset.capability_bundle_sha256 != bundle_hash
            ):
                raise SuiteCompilationError(
                    [
                        CompilationIssue(
                            code="CAPABILITY_CONTRACT_MISMATCH",
                            field_path="$.capability_bundle",
                            message=(
                                "explicit capability contract does not match "
                                "the dataset binding"
                            ),
                        )
                    ]
                )
            bundle_manifest = (definition.root / capability.logical_path).resolve()
            bundle_path = bundle_manifest.parent
            if not bundle_path.is_relative_to(definition.root.resolve()):
                raise SuiteCompilationError(
                    [
                        CompilationIssue(
                            code="SOURCE_PATH_OUTSIDE_ROOT",
                            field_path="$.capability_bundle.path",
                            message="capability bundle resolves outside the Suite root",
                            evidence_refs=[capability.logical_path],
                        )
                    ]
                )
            dataset = dataset.model_copy(
                update={
                    "provider_id": capability_provider or dataset.provider_id,
                    "capability_bundle_path": str(bundle_path),
                    "capability_bundle_sha256": bundle_hash,
                },
                deep=True,
            )

    preflight = getattr(provider_registration.implementation, "validate_dataset", None)
    if callable(preflight):
        preflight_config = {
            **dict(provider_registration.config),
            **definition.runtime_provider_config,
        }
        try:
            report = preflight(dataset, **preflight_config)
        except Exception as exc:
            raise SuiteCompilationError(
                [
                    CompilationIssue(
                        code="DATASET_SEMANTIC_INVALID",
                        field_path="$.dataset_sources",
                        message=str(exc),
                    )
                ]
            ) from exc
        if not isinstance(report, ValidationReport):
            raise SuiteCompilationError(
                [
                    CompilationIssue(
                        code="PROVIDER_PREFLIGHT_OUTPUT_INVALID",
                        field_path="$.provider",
                        message=(
                            "Provider semantic preflight did not return "
                            "ValidationReport"
                        ),
                    )
                ]
            )
        if not report.valid:
            raise SuiteCompilationError(
                [
                    CompilationIssue(
                        code="DATASET_SEMANTIC_INVALID",
                        field_path=(
                            f"$.dataset_sources.{item.field_path}"
                            if item.field_path
                            else "$.dataset_sources"
                        ),
                        message=(
                            f"{item.case_id}: {item.message}"
                            if item.case_id
                            else item.message
                        ),
                    )
                    for item in report.issues
                ]
            )

    plugin_snapshots: list[ResolvedPluginSnapshot] = sorted(
        (catalog.snapshot(item) for item in registrations.values()),
        key=lambda item: (item.kind, item.plugin_id, item.version),
    )
    contract_snapshots = sorted(
        contracts,
        key=lambda item: (item.contract_id, item.version, item.logical_path),
    )
    source_snapshots = [
        SourceFingerprint(logical_path=item.logical_path, sha256=item.sha256)
        for item in [*sources, *dependency_sources]
    ]
    dataset_snapshot = dataset.model_dump(mode="json")
    for path_field in ("path", "manifest_path", "capability_bundle_path"):
        dataset_snapshot.pop(path_field, None)
    snapshot = {
        "schema_version": suite.schema_version,
        "suite_id": suite.suite_id,
        "suite_version": suite.suite_version,
        "lifecycle_state": suite.lifecycle_state,
        "definition": suite.model_dump(mode="json"),
        "plugins": [item.model_dump(mode="json") for item in plugin_snapshots],
        "contracts": [item.model_dump(mode="json") for item in contract_snapshots],
        "sources": [item.model_dump(mode="json") for item in source_snapshots],
        "run_config": suite.run_config.model_dump(mode="json"),
        "dataset": dataset_snapshot,
        "runtime_provider_config": runtime_provider_snapshot,
    }
    return CompiledSuite(
        schema_version=suite.schema_version,
        suite_id=suite.suite_id,
        suite_version=suite.suite_version,
        lifecycle_state=suite.lifecycle_state,
        definition=json.loads(json.dumps(suite.model_dump(mode="json"))),
        dataset=dataset.model_copy(deep=True),
        run_config=suite.run_config.model_copy(deep=True),
        plugins=plugin_snapshots,
        contracts=contract_snapshots,
        sources=source_snapshots,
        compiled_suite_snapshot=json.loads(json.dumps(snapshot)),
        compiled_suite_sha256=sha256_bytes(canonical_json_bytes(snapshot)),
        runtime_provider_config=json.loads(
            json.dumps(definition.runtime_provider_config, default=str)
        ),
    )
