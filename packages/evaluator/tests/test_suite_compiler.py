from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_framework.contracts.compiler import (
    SuiteCompilationError,
    compile_suite,
    load_suite_definition,
)
from eval_framework.contracts.store import ContractStore, sha256_bytes
from eval_framework.plugins.builtin.dataset_loaders import JsonDocumentDatasetLoader
from eval_framework.plugins.catalog import PluginCatalog
from eval_framework.plugins.models import PluginDescriptor

SHA256 = "c" * 64
EMPTY_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


class CountingLoader:
    def __init__(self, output=None) -> None:
        self.calls = 0
        self.output = output

    def load(self, sources, *, filters, config):
        self.calls += 1
        if self.output is not None:
            return self.output
        return JsonDocumentDatasetLoader().load(
            sources,
            filters=filters,
            config=config,
        )


class CountingProviderFactory:
    provider_id = "fixture_provider"

    def __init__(self) -> None:
        self.create_calls = 0
        self.model_client_calls = 0

    def create(self, *args, **kwargs):
        self.create_calls += 1
        raise AssertionError("compiler must not create Provider runtime")


def _descriptor(plugin_id: str, kind: str) -> PluginDescriptor:
    return PluginDescriptor(
        plugin_id=plugin_id,
        kind=kind,
        version="1.0.0",
        config_schema=EMPTY_SCHEMA,
        supported_contract_versions=["1.0"],
        implementation_fingerprint=SHA256,
    )


def _dataset_document() -> bytes:
    fixture = Path(__file__).parent / "fixtures" / "json_document_dataset.json"
    value = json.loads(fixture.read_text(encoding="utf-8"))
    value["metadata"]["provider_id"] = "fixture_provider"
    return json.dumps(value, sort_keys=True).encode()


def _write_suite(
    root: Path,
    *,
    source_sha256: str | None = None,
    contract_sha256: str | None = None,
    provider_id: str = "fixture_provider_v1",
    loader_config: dict | None = None,
    reverse_keys: bool = False,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    dataset = _dataset_document()
    (root / "cases.json").write_bytes(dataset)
    contract = json.dumps(
        {
            "provider_id": "fixture_provider",
            "bundle_format_version": "1.0",
            "capability_bundle_sha256": "b" * 64,
            "files": [],
        },
        sort_keys=True,
    ).encode()
    (root / "capabilities.json").write_bytes(contract)
    payload = {
        "schema_version": "1.0",
        "suite_id": "fixture_suite",
        "suite_version": "1.0.0",
        "lifecycle_state": "FROZEN",
        "dataset_loader": {
            "plugin_id": "fixture_json_document_v1",
            "version": "1.0.0",
            "config": loader_config or {},
        },
        "dataset_sources": [
            {
                "path": "cases.json",
                "sha256": source_sha256 or sha256_bytes(dataset),
            }
        ],
        "provider": {
            "plugin_id": provider_id,
            "version": "1.0.0",
            "config": {},
        },
        "capability_bundle": {
            "contract_id": "fixture_capabilities",
            "version": "1.0",
            "path": "capabilities.json",
            "sha256": contract_sha256 or sha256_bytes(contract),
        },
        "run_config": {
            "run_mode": "framework_self_test",
            "allow_non_frozen_dataset": True,
        },
    }
    if reverse_keys:
        payload = dict(reversed(list(payload.items())))
    path = root / "suite.json"
    path.write_text(json.dumps(payload, indent=4), encoding="utf-8")
    return path


def _catalog(loader=None, provider=None) -> tuple[PluginCatalog, object, object]:
    loader = loader or CountingLoader()
    provider = provider or CountingProviderFactory()
    catalog = PluginCatalog()
    catalog.register(
        _descriptor("fixture_json_document_v1", "dataset_loader"), loader
    )
    catalog.register(_descriptor("fixture_provider_v1", "provider"), provider)
    return catalog, loader, provider


def test_compile_suite_resolves_loader_provider_contracts_and_sources(
    tmp_path: Path,
) -> None:
    suite_path = _write_suite(tmp_path)
    catalog, loader, provider = _catalog()
    loaded = load_suite_definition(suite_path)

    compiled = compile_suite(loaded, catalog, ContractStore(tmp_path))

    assert [case.case_id for case in compiled.dataset.cases] == ["MODULE-1"]
    assert loader.calls == 1
    assert provider.create_calls == 0
    assert {item.plugin_id for item in compiled.plugins} == {
        "fixture_json_document_v1",
        "fixture_provider_v1",
    }
    assert compiled.contracts[0].content["provider_id"] == "fixture_provider"
    assert compiled.sources[0].logical_path == "cases.json"
    assert str(tmp_path) not in json.dumps(compiled.compiled_suite_snapshot)


def test_compiled_suite_hash_is_deterministic_across_json_key_order(
    tmp_path: Path,
) -> None:
    first_path = _write_suite(tmp_path / "first")
    second_path = _write_suite(tmp_path / "second", reverse_keys=True)
    catalog, _, _ = _catalog()

    first = compile_suite(
        load_suite_definition(first_path),
        catalog,
        ContractStore(first_path.parent),
    )
    second = compile_suite(
        load_suite_definition(second_path),
        catalog,
        ContractStore(second_path.parent),
    )

    assert first.compiled_suite_snapshot == second.compiled_suite_snapshot
    assert first.compiled_suite_sha256 == second.compiled_suite_sha256


def test_compile_aggregates_preflight_issues_before_loader_or_provider(
    tmp_path: Path,
) -> None:
    suite_path = _write_suite(
        tmp_path,
        source_sha256="0" * 64,
        contract_sha256="1" * 64,
        provider_id="missing_provider",
        loader_config={"unexpected": True},
    )
    catalog, loader, provider = _catalog()

    with pytest.raises(SuiteCompilationError) as captured:
        compile_suite(
            load_suite_definition(suite_path),
            catalog,
            ContractStore(tmp_path),
        )

    assert captured.value.code == "SUITE_COMPILATION_FAILED"
    assert {issue.code for issue in captured.value.issues} == {
        "PLUGIN_CONFIG_INVALID",
        "PLUGIN_NOT_FOUND",
        "SOURCE_FINGERPRINT_MISMATCH",
    }
    assert len(captured.value.issues) == 4
    assert list(captured.value.issues) == sorted(
        captured.value.issues,
        key=lambda issue: (issue.field_path, issue.code, issue.message),
    )
    assert loader.calls == 0
    assert provider.create_calls == 0
    assert provider.model_client_calls == 0


def test_compile_rejects_noncanonical_loader_output(tmp_path: Path) -> None:
    suite_path = _write_suite(tmp_path)
    catalog, loader, provider = _catalog(loader=CountingLoader(output={"cases": []}))

    with pytest.raises(SuiteCompilationError) as captured:
        compile_suite(
            load_suite_definition(suite_path),
            catalog,
            ContractStore(tmp_path),
        )

    assert [issue.code for issue in captured.value.issues] == [
        "LOADER_OUTPUT_INVALID"
    ]
    assert loader.calls == 1
    assert provider.create_calls == 0


def test_load_suite_definition_records_source_identity(tmp_path: Path) -> None:
    path = _write_suite(tmp_path)

    loaded = load_suite_definition(path)

    assert loaded.root == tmp_path.resolve()
    assert loaded.source_path == path.resolve()
    assert loaded.source_sha256 == sha256_bytes(path.read_bytes())
    assert loaded.origin == "file"
