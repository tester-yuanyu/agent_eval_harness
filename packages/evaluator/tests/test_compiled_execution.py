from __future__ import annotations

import json
from importlib.util import find_spec
from pathlib import Path

import pytest

from eval_framework.capabilities import CapabilityBundle, CapabilityRegistry
from eval_framework.compiled_execution import execute_compiled_suite
from eval_framework.composition import default_plugin_catalog
from eval_framework.contracts.compiler import compile_suite, load_suite_definition
from eval_framework.contracts.store import ContractStore, sha256_bytes
from eval_framework.diagnostics import DiagnosticRegistry
from eval_framework.plugins.builtin.dataset_loaders import LegacyJsonlDatasetLoader
from eval_framework.plugins.catalog import PluginCatalog, PluginCatalogError
from eval_framework.plugins.models import PluginDescriptor, PluginReference
from eval_framework.provider import AdapterOutput, EvaluationPreflightError
from eval_framework.reporting import write_report
from eval_framework.result_loader import load_run_result
from eval_framework.schemas import EvaluationRunResult, ExecutionProfile
from eval_framework.tool_catalog import ToolCatalog

SHA256 = "d" * 64
EMPTY_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


class FixtureProvider:
    provider_id = "mini_agent"
    provider_version = "fixture-v1"
    diagnostics = DiagnosticRegistry()

    def __init__(self, dataset) -> None:
        self.capabilities = CapabilityRegistry(
            CapabilityBundle.load(Path(dataset.capability_bundle_path))
        )
        self.tools = ToolCatalog.from_registry(
            self.capabilities,
            profiles={"legacy": ExecutionProfile(allowed_tools=[])},
        )

    def create_runtime(self, execution, session_id, scope):
        return {"session_id": session_id}

    def run_module(self, runtime, execution):
        return AdapterOutput(
            module_output={
                "intent": "query_information",
                "status": "READY",
                "next_action": "CALL_TOOL",
                "parameters": {
                    "resource_type": "fixture",
                    "environment": "test",
                },
                "missing_parameters": [],
                "reason": "fixture",
            },
            turns=[],
            before_snapshot=None,
            turn_snapshots=[],
            snapshot=None,
            trace_events=[],
        )

    def run_full(self, runtime, execution, scope):
        raise AssertionError("module-only fixture")

    def cleanup(self, runtime):
        runtime["cleaned"] = True

    def classify_exception(self, exc):
        raise AssertionError(f"unexpected fixture exception: {exc}")

    def runtime_metadata(self, runtime):
        return {"client_type": "FixtureProvider"}

    def tool_version(self, runtime):
        return "fixture-tools-v1"


class FixtureProviderFactory:
    provider_id = "mini_agent"

    def __init__(self) -> None:
        self.calls = []

    def create(self, dataset, model_client_factory=None, **kwargs):
        self.calls.append((dataset, model_client_factory, kwargs))
        return FixtureProvider(dataset)


def _descriptor(plugin_id: str, kind: str, fingerprint: str = SHA256):
    return PluginDescriptor(
        plugin_id=plugin_id,
        kind=kind,
        version="1.0.0",
        config_schema=EMPTY_SCHEMA,
        supported_contract_versions=["1.0"],
        implementation_fingerprint=fingerprint,
    )


def _compiled(dataset_path: Path):
    dataset_manifest = dataset_path.with_suffix(".manifest.json")
    dataset_manifest_value = json.loads(dataset_manifest.read_text())
    bundle_root = (
        dataset_path.parent / dataset_manifest_value["capability_bundle"]["path"]
    )
    bundle_manifest = bundle_root / "bundle_manifest.json"
    contract_path = bundle_manifest
    contract = contract_path.read_bytes()
    contract_path.write_bytes(contract)
    suite = {
        "schema_version": "1.0",
        "suite_id": "compiled-execution-fixture",
        "suite_version": "1.0.0",
        "lifecycle_state": "FROZEN",
        "dataset_loader": {
            "plugin_id": "legacy_jsonl_eval_case_v1",
            "version": "1.0.0",
            "config": {},
        },
        "dataset_sources": [
            {
                "path": dataset_path.name,
                "sha256": sha256_bytes(dataset_path.read_bytes()),
            },
            {
                "path": dataset_manifest.name,
                "sha256": sha256_bytes(dataset_manifest.read_bytes()),
            },
        ],
        "provider": {
            "plugin_id": "fixture_provider_v1",
            "version": "1.0.0",
            "config": {},
        },
        "capability_bundle": {
            "contract_id": "fixture-capabilities",
            "version": "1.0",
            "path": str(contract_path.relative_to(dataset_path.parent)),
            "sha256": sha256_bytes(contract),
        },
        "run_config": {
            "run_mode": "framework_self_test",
            "filters": {"case_ids": ["MODULE-1"]},
        },
    }
    suite_path = dataset_path.parent / "suite.json"
    suite_path.write_text(json.dumps(suite), encoding="utf-8")
    factory = FixtureProviderFactory()
    catalog = PluginCatalog()
    catalog.register(
        _descriptor("legacy_jsonl_eval_case_v1", "dataset_loader"),
        LegacyJsonlDatasetLoader(),
    )
    catalog.register(
        _descriptor("fixture_provider_v1", "provider"),
        factory,
    )
    compiled = compile_suite(
        load_suite_definition(suite_path),
        catalog,
        ContractStore(dataset_path.parent),
    )
    return compiled, catalog, factory


def test_execute_compiled_suite_creates_provider_after_compilation_and_adds_provenance(
    dataset_path: Path,
    tmp_path: Path,
) -> None:
    compiled, catalog, factory = _compiled(dataset_path)
    assert factory.calls == []

    result = execute_compiled_suite(compiled, catalog)

    assert len(factory.calls) == 1
    assert result.compiled_suite_sha256 == compiled.compiled_suite_sha256
    assert result.compiled_suite_snapshot == compiled.compiled_suite_snapshot
    assert {item["plugin_id"] for item in result.plugin_fingerprints} == {
        "legacy_jsonl_eval_case_v1",
        "fixture_provider_v1",
    }
    assert result.contract_fingerprints[0]["contract_id"] == ("fixture-capabilities")
    paths = write_report(result, tmp_path / "run")
    manifest = json.loads(Path(paths.manifest).read_text(encoding="utf-8"))
    assert manifest["compiled_suite_sha256"] == compiled.compiled_suite_sha256
    assert manifest["plugin_fingerprints"] == result.plugin_fingerprints


def test_execute_compiled_suite_rejects_catalog_fingerprint_drift(
    dataset_path: Path,
) -> None:
    compiled, _, _ = _compiled(dataset_path)
    drifted = PluginCatalog()
    drifted.register(
        _descriptor("legacy_jsonl_eval_case_v1", "dataset_loader"),
        LegacyJsonlDatasetLoader(),
    )
    drifted.register(
        _descriptor("fixture_provider_v1", "provider", "e" * 64),
        FixtureProviderFactory(),
    )

    with pytest.raises(EvaluationPreflightError) as captured:
        execute_compiled_suite(compiled, drifted)

    assert captured.value.code == "PLUGIN_FINGERPRINT_MISMATCH"


def test_legacy_provider_bridge_does_not_silently_ignore_layered_plugins(
    dataset_path: Path,
) -> None:
    _, catalog, factory = _compiled(dataset_path)
    path = dataset_path.parent / "suite.json"
    value = json.loads(path.read_text())
    value["environment"] = {"plugin_id": "test_environment", "version": "1.0.0"}
    path.write_text(json.dumps(value))
    catalog.register(_descriptor("test_environment", "environment"), object())
    compiled = compile_suite(
        load_suite_definition(path), catalog, ContractStore(path.parent)
    )
    with pytest.raises(EvaluationPreflightError) as captured:
        execute_compiled_suite(compiled, catalog)
    assert captured.value.code == "LAYERED_HARNESS_REQUIRED"
    assert factory.calls == []


def test_old_results_without_compiled_fields_still_load(
    dataset_path: Path,
    tmp_path: Path,
) -> None:
    compiled, catalog, _ = _compiled(dataset_path)
    result = execute_compiled_suite(compiled, catalog)
    payload = result.model_dump(mode="json")
    for field in (
        "compiled_suite_sha256",
        "compiled_suite_snapshot",
        "plugin_fingerprints",
        "contract_fingerprints",
    ):
        payload.pop(field)
    path = tmp_path / "legacy-results.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_run_result(path).result

    assert isinstance(loaded, EvaluationRunResult)
    assert loaded.compiled_suite_sha256 is None
    assert loaded.plugin_fingerprints == []


def test_default_plugin_catalog_registers_stable_builtin_ids() -> None:
    catalog = default_plugin_catalog()

    identities = [
        ("legacy_jsonl_eval_case_v1", "dataset_loader"),
        ("fixture_json_document_v1", "dataset_loader"),
    ]
    if find_spec("minimal_agent") is not None:
        identities.append(("mini_agent_provider_v1", "provider"))
    else:
        with pytest.raises(PluginCatalogError) as captured:
            catalog.resolve(
                PluginReference(plugin_id="mini_agent_provider_v1", version="1.0.0"),
                expected_kind="provider",
                contract_version="1.0",
                field_path="$.provider",
            )
        assert captured.value.code == "PLUGIN_NOT_FOUND"
    for plugin_id, kind in identities:
        registration = catalog.resolve(
            PluginReference(plugin_id=plugin_id, version="1.0.0"),
            expected_kind=kind,
            contract_version="1.0",
            field_path="$.fixture",
        )
        assert registration.descriptor.plugin_id == plugin_id
