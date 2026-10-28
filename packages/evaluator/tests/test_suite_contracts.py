from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from eval_framework.contracts.models import (
    CompiledSuite,
    DatasetSource,
    SuiteDefinition,
)
from eval_framework.plugins.models import PluginDescriptor, PluginReference
from eval_framework.schemas import DatasetBundle, RunConfig

SHA256 = "a" * 64


def _plugin_ref(plugin_id: str) -> dict[str, object]:
    return {"plugin_id": plugin_id, "version": "1.0.0", "config": {}}


def _suite_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "suite_id": "fixture_suite",
        "suite_version": "1.0.0",
        "lifecycle_state": "FROZEN",
        "dataset_loader": _plugin_ref("fixture_loader_v1"),
        "dataset_sources": [
            {"path": "datasets/cases.jsonl", "sha256": SHA256}
        ],
        "provider": _plugin_ref("fixture_provider_v1"),
        "run_config": {"run_mode": "framework_self_test"},
    }


@pytest.mark.parametrize("field", ["module", "command", "entry_point"])
def test_suite_definition_is_strict_and_rejects_executable_fields(
    field: str,
) -> None:
    payload = _suite_payload()
    payload[field] = "malicious"

    with pytest.raises(ValidationError):
        SuiteDefinition.model_validate(payload)


@pytest.mark.parametrize("path", ["/tmp/cases.jsonl", "../cases.jsonl", "a/../../b"])
def test_dataset_source_rejects_paths_outside_suite_root(path: str) -> None:
    with pytest.raises(ValidationError):
        DatasetSource(path=path, sha256=SHA256)


def test_plugin_descriptor_requires_exact_identity_fields() -> None:
    descriptor = PluginDescriptor(
        plugin_id="fixture_loader_v1",
        kind="dataset_loader",
        version="1.0.0",
        config_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        supported_contract_versions=["1.0"],
        implementation_fingerprint=SHA256,
    )

    assert descriptor.plugin_id == "fixture_loader_v1"
    assert descriptor.kind == "dataset_loader"
    with pytest.raises(ValidationError):
        PluginDescriptor.model_validate(
            {
                **descriptor.model_dump(),
                "config_schema": {"type": "object"},
            }
        )
    with pytest.raises(ValidationError):
        PluginDescriptor.model_validate(
            {**descriptor.model_dump(), "implementation_fingerprint": "short"}
        )


def test_compiled_suite_is_frozen() -> None:
    suite = SuiteDefinition.model_validate(_suite_payload())
    compiled = CompiledSuite(
        schema_version="1.0",
        suite_id=suite.suite_id,
        suite_version=suite.suite_version,
        lifecycle_state=suite.lifecycle_state,
        definition=suite.model_dump(mode="json"),
        dataset=DatasetBundle(
            path="datasets/cases.jsonl",
            sha256=SHA256,
            schema_versions=[],
            dataset_version="1.0",
            total_count=0,
            cases=[],
        ),
        run_config=RunConfig(run_mode="framework_self_test"),
        plugins=[],
        contracts=[],
        sources=[],
        compiled_suite_snapshot={},
        compiled_suite_sha256=SHA256,
    )

    with pytest.raises(ValidationError):
        compiled.suite_id = "changed"


def test_suite_schema_snapshot_matches_runtime_schema() -> None:
    schema_path = Path(__file__).parents[1] / "schemas" / "suite_definition.schema.json"
    assert json.loads(schema_path.read_text(encoding="utf-8")) == (
        SuiteDefinition.model_json_schema()
    )


def test_plugin_reference_config_has_independent_default() -> None:
    first = PluginReference(plugin_id="a", version="1")
    second = PluginReference(plugin_id="b", version="1")

    first.config["x"] = 1

    assert second.config == {}
