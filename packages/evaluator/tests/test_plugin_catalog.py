from __future__ import annotations

import pytest

from eval_framework.plugins.catalog import PluginCatalog, PluginCatalogError
from eval_framework.plugins.models import PluginDescriptor, PluginReference

SHA256 = "b" * 64


def _descriptor(
    *,
    plugin_id: str = "fixture_loader",
    kind: str = "dataset_loader",
    version: str = "1.0.0",
    contracts: list[str] | None = None,
) -> PluginDescriptor:
    return PluginDescriptor(
        plugin_id=plugin_id,
        kind=kind,
        version=version,
        config_schema={
            "type": "object",
            "properties": {"encoding": {"type": "string"}},
            "additionalProperties": False,
        },
        supported_contract_versions=contracts or ["1.0"],
        implementation_fingerprint=SHA256,
    )


def test_catalog_resolves_only_exact_key_and_snapshots_config() -> None:
    implementation = object()
    catalog = PluginCatalog()
    catalog.register(_descriptor(), implementation)
    reference = PluginReference(
        plugin_id="fixture_loader",
        version="1.0.0",
        config={"encoding": "utf-8"},
    )

    registration = catalog.resolve(
        reference,
        expected_kind="dataset_loader",
        contract_version="1.0",
        field_path="$.dataset_loader",
    )

    assert registration.implementation is implementation
    assert catalog.snapshot(registration).model_dump() == {
        "kind": "dataset_loader",
        "plugin_id": "fixture_loader",
        "version": "1.0.0",
        "implementation_fingerprint": SHA256,
        "config": {"encoding": "utf-8"},
    }


def test_catalog_rejects_duplicate_exact_key() -> None:
    catalog = PluginCatalog()
    descriptor = _descriptor()
    catalog.register(descriptor, object())

    with pytest.raises(PluginCatalogError) as captured:
        catalog.register(descriptor, object())

    assert captured.value.code == "DUPLICATE_PLUGIN"


def test_catalog_reports_kind_mismatch_for_known_id_and_version() -> None:
    catalog = PluginCatalog()
    catalog.register(_descriptor(kind="provider"), object())

    with pytest.raises(PluginCatalogError) as captured:
        catalog.resolve(
            PluginReference(plugin_id="fixture_loader", version="1.0.0"),
            expected_kind="dataset_loader",
            contract_version="1.0",
            field_path="$.dataset_loader",
        )

    assert captured.value.code == "PLUGIN_KIND_MISMATCH"


def test_catalog_does_not_fall_back_to_another_version() -> None:
    catalog = PluginCatalog()
    catalog.register(_descriptor(version="1.0.0"), object())

    with pytest.raises(PluginCatalogError) as captured:
        catalog.resolve(
            PluginReference(plugin_id="fixture_loader", version="2.0.0"),
            expected_kind="dataset_loader",
            contract_version="1.0",
            field_path="$.dataset_loader",
        )

    assert captured.value.code == "PLUGIN_NOT_FOUND"


def test_catalog_rejects_incompatible_contract_version() -> None:
    catalog = PluginCatalog()
    catalog.register(_descriptor(contracts=["2.0"]), object())

    with pytest.raises(PluginCatalogError) as captured:
        catalog.resolve(
            PluginReference(plugin_id="fixture_loader", version="1.0.0"),
            expected_kind="dataset_loader",
            contract_version="1.0",
            field_path="$.dataset_loader",
        )

    assert captured.value.code == "PLUGIN_CONTRACT_INCOMPATIBLE"


def test_catalog_reports_precise_path_for_unknown_config_field() -> None:
    catalog = PluginCatalog()
    catalog.register(_descriptor(), object())

    with pytest.raises(PluginCatalogError) as captured:
        catalog.resolve(
            PluginReference(
                plugin_id="fixture_loader",
                version="1.0.0",
                config={"unexpected": True},
            ),
            expected_kind="dataset_loader",
            contract_version="1.0",
            field_path="$.dataset_loader",
        )

    assert captured.value.code == "PLUGIN_CONFIG_INVALID"
    assert captured.value.field_path == "$.dataset_loader.config.unexpected"
