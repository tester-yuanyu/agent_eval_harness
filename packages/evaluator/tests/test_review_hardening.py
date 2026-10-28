from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from test_compiled_execution import FixtureProviderFactory, _compiled, _descriptor

from eval_framework.capabilities import CapabilityBundle
from eval_framework.cli import main
from eval_framework.compatibility.suite_builder import build_legacy_suite
from eval_framework.compiled_execution import execute_compiled_suite
from eval_framework.composition import (
    _implementation_fingerprint,
    default_plugin_catalog,
)
from eval_framework.contracts.compiler import (
    SuiteCompilationError,
    compile_suite,
    load_suite_definition,
)
from eval_framework.contracts.store import ContractStore, sha256_bytes
from eval_framework.plugins.builtin.dataset_loaders import LegacyJsonlDatasetLoader
from eval_framework.plugins.catalog import PluginCatalog
from eval_framework.plugins.models import PluginDescriptor
from eval_framework.provider import EvaluationPreflightError
from eval_framework.schemas import RunConfig


def test_suite_compiles_agent_json_as_capability_contract(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    source_dir = project_root / "datasets/mini_agent"
    dataset_name = "module_query_user_intent_v2_0.jsonl"
    manifest_name = "module_query_user_intent_v2_0.manifest.json"
    bundle_hash = "99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8"
    shutil.copy2(source_dir / dataset_name, tmp_path / dataset_name)
    shutil.copy2(source_dir / manifest_name, tmp_path / manifest_name)
    bundle_relative = Path("capability_bundles") / bundle_hash
    shutil.copytree(source_dir / bundle_relative, tmp_path / bundle_relative)
    agent_relative = bundle_relative / "agent.json"
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "suite_id": "query-user-agent-json",
                "suite_version": "2.0",
                "lifecycle_state": "FROZEN",
                "dataset_loader": {
                    "plugin_id": "legacy_jsonl_eval_case_v1",
                    "version": "1.0.0",
                },
                "dataset_sources": [
                    {
                        "path": dataset_name,
                        "sha256": sha256_bytes((tmp_path / dataset_name).read_bytes()),
                    },
                    {
                        "path": manifest_name,
                        "sha256": sha256_bytes((tmp_path / manifest_name).read_bytes()),
                    },
                ],
                "provider": {
                    "plugin_id": "mini_agent_provider_v1",
                    "version": "1.0.0",
                },
                "capability_bundle": {
                    "contract_id": "mini_agent_capability_bundle",
                    "version": "3.0",
                    "path": str(agent_relative),
                    "sha256": sha256_bytes((tmp_path / agent_relative).read_bytes()),
                },
                "run_config": {"run_mode": "framework_self_test"},
            }
        ),
        encoding="utf-8",
    )

    compiled = compile_suite(
        load_suite_definition(suite_path),
        default_plugin_catalog(),
        ContractStore(tmp_path),
    )

    assert compiled.dataset.provider_id == "mini_agent"
    assert compiled.dataset.capability_bundle_sha256 == bundle_hash
    assert Path(compiled.dataset.capability_bundle_path) == tmp_path / bundle_relative


def test_undeclared_jsonl_sidecar_cannot_change_compiled_dataset(
    dataset_path: Path,
) -> None:
    suite_path = dataset_path.parent / "suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "suite_id": "no-hidden-inputs",
                "suite_version": "1",
                "dataset_loader": {
                    "plugin_id": "loader",
                    "version": "1.0.0",
                },
                "dataset_sources": [
                    {
                        "path": dataset_path.name,
                        "sha256": sha256_bytes(dataset_path.read_bytes()),
                    }
                ],
                "provider": {"plugin_id": "provider", "version": "1.0.0"},
                "run_config": {"filters": {"case_ids": ["MODULE-1"]}},
            }
        )
    )

    class Provider:
        provider_id = "unknown"

    empty = {"type": "object", "properties": {}, "additionalProperties": False}
    catalog = PluginCatalog()
    for plugin_id, kind, implementation in (
        ("loader", "dataset_loader", LegacyJsonlDatasetLoader()),
        ("provider", "provider", Provider()),
    ):
        catalog.register(
            PluginDescriptor(
                plugin_id=plugin_id,
                kind=kind,
                version="1.0.0",
                config_schema=empty,
                supported_contract_versions=["1.0"],
                implementation_fingerprint="a" * 64,
            ),
            implementation,
        )

    first = compile_suite(
        load_suite_definition(suite_path), catalog, ContractStore(dataset_path.parent)
    )
    manifest = dataset_path.with_suffix(".manifest.json")
    manifest.write_text('{"execution_profiles":{"changed":{"allowed_tools":[]}}}')
    second = compile_suite(
        load_suite_definition(suite_path), catalog, ContractStore(dataset_path.parent)
    )

    assert first.compiled_suite_sha256 == second.compiled_suite_sha256
    assert first.dataset.execution_profiles == second.dataset.execution_profiles
    assert first.dataset.manifest_path is None


def test_capability_contract_is_the_execution_binding(dataset_path: Path) -> None:
    compiled, _, _ = _compiled(dataset_path)

    assert compiled.dataset.capability_bundle_path is not None
    assert Path(compiled.dataset.capability_bundle_path) == (
        dataset_path.parent / Path(compiled.contracts[0].logical_path).parent
    )


def test_validate_runs_semantic_preflight(dataset_path: Path, capsys) -> None:
    manifest_path = dataset_path.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    profile = next(iter(manifest["execution_profiles"].values()))
    profile["allowed_tools"] = ["tool_that_does_not_exist"]
    manifest_path.write_text(json.dumps(manifest))

    assert (
        main(["validate", "--dataset", str(dataset_path), "--provider", "mini_agent"])
        == 2
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["issues"][0]["code"] == "DATASET_SEMANTIC_INVALID"


def test_nested_compiled_mutation_is_rejected_before_provider(
    dataset_path: Path,
) -> None:
    compiled, catalog, factory = _compiled(dataset_path)
    compiled.run_config.trials_per_case = 2

    with pytest.raises(EvaluationPreflightError) as captured:
        execute_compiled_suite(compiled, catalog)

    assert captured.value.code == "COMPILED_SUITE_INTEGRITY_ERROR"
    assert factory.calls == []


@pytest.mark.parametrize("unsafe", ["../outside.jsonl", "/tmp/outside.jsonl"])
def test_path_escape_has_stable_compilation_issue(tmp_path: Path, unsafe: str) -> None:
    path = tmp_path / "suite.json"
    path.write_text(
        json.dumps(
            {
                "suite_id": "escape",
                "suite_version": "1",
                "dataset_loader": {"plugin_id": "x", "version": "1"},
                "dataset_sources": [{"path": unsafe, "sha256": "0" * 64}],
                "provider": {"plugin_id": "y", "version": "1"},
            }
        )
    )

    with pytest.raises(SuiteCompilationError) as captured:
        load_suite_definition(path)

    assert [(item.code, item.field_path) for item in captured.value.issues] == [
        ("SOURCE_PATH_OUTSIDE_ROOT", "$.dataset_sources[0].path")
    ]


def test_symlink_escape_has_stable_compilation_issue(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.jsonl"
    outside.write_text("{}\n")
    (tmp_path / "linked.jsonl").symlink_to(outside)
    suite = tmp_path / "suite.json"
    suite.write_text(
        json.dumps(
            {
                "suite_id": "symlink-escape",
                "suite_version": "1",
                "dataset_loader": {"plugin_id": "missing", "version": "1"},
                "dataset_sources": [
                    {
                        "path": "linked.jsonl",
                        "sha256": sha256_bytes(outside.read_bytes()),
                    }
                ],
                "provider": {"plugin_id": "missing", "version": "1"},
            }
        )
    )

    with pytest.raises(SuiteCompilationError) as captured:
        compile_suite(
            load_suite_definition(suite), PluginCatalog(), ContractStore(tmp_path)
        )

    assert (
        "SOURCE_PATH_OUTSIDE_ROOT",
        "$.dataset_sources[0].path",
    ) in {(item.code, item.field_path) for item in captured.value.issues}


def test_builtin_fingerprint_changes_with_implementation_source(
    tmp_path: Path, monkeypatch
) -> None:
    dependency = tmp_path / "parser.py"
    dependency.write_text("first")
    implementation = LegacyJsonlDatasetLoader()
    monkeypatch.setattr(implementation, "fingerprint_sources", lambda: [dependency])
    first = _implementation_fingerprint(implementation)
    dependency.write_text("second")

    assert _implementation_fingerprint(implementation) != first


def test_bundle_dependency_mismatch_stops_before_loader(dataset_path: Path) -> None:
    compiled, _, _ = _compiled(dataset_path)
    suite_path = dataset_path.parent / "suite.json"
    bundle_root = Path(compiled.dataset.capability_bundle_path)
    manifest = json.loads((bundle_root / "bundle_manifest.json").read_text())
    child = bundle_root / manifest["files"][0]["path"]
    child.write_text("{}")

    class CountingLoader(LegacyJsonlDatasetLoader):
        calls = 0

        def load(self, *args, **kwargs):
            self.calls += 1
            return super().load(*args, **kwargs)

    loader = CountingLoader()
    catalog = PluginCatalog()
    catalog.register(_descriptor("legacy_jsonl_eval_case_v1", "dataset_loader"), loader)
    catalog.register(
        _descriptor("fixture_provider_v1", "provider"), FixtureProviderFactory()
    )

    with pytest.raises(SuiteCompilationError) as captured:
        compile_suite(
            load_suite_definition(suite_path),
            catalog,
            ContractStore(dataset_path.parent),
        )

    assert "SOURCE_FINGERPRINT_MISMATCH" in {
        item.code for item in captured.value.issues
    }
    assert loader.calls == 0


def test_capability_reference_must_be_bundle_manifest(dataset_path: Path) -> None:
    compiled, catalog, _ = _compiled(dataset_path)
    suite_path = dataset_path.parent / "suite.json"
    suite = json.loads(suite_path.read_text())
    bundle_root = Path(compiled.dataset.capability_bundle_path)
    manifest = json.loads((bundle_root / "bundle_manifest.json").read_text())
    unrelated = bundle_root / manifest["files"][0]["path"]
    suite["capability_bundle"]["path"] = str(unrelated.relative_to(dataset_path.parent))
    suite["capability_bundle"]["sha256"] = sha256_bytes(unrelated.read_bytes())
    suite_path.write_text(json.dumps(suite))

    with pytest.raises(SuiteCompilationError) as captured:
        compile_suite(
            load_suite_definition(suite_path),
            catalog,
            ContractStore(dataset_path.parent),
        )

    assert {item.code for item in captured.value.issues} == {
        "CAPABILITY_CONTRACT_INVALID"
    }


def test_explicit_capability_contract_must_match_dataset_binding(
    dataset_path: Path,
) -> None:
    _, catalog, _ = _compiled(dataset_path)
    suite_path = dataset_path.parent / "suite.json"
    manifest_path = dataset_path.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    manifest["capability_bundle"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    suite = json.loads(suite_path.read_text())
    manifest_source = next(
        item for item in suite["dataset_sources"] if item["path"] == manifest_path.name
    )
    manifest_source["sha256"] = sha256_bytes(manifest_path.read_bytes())
    suite_path.write_text(json.dumps(suite))

    with pytest.raises(SuiteCompilationError) as captured:
        compile_suite(
            load_suite_definition(suite_path),
            catalog,
            ContractStore(dataset_path.parent),
        )

    assert {item.code for item in captured.value.issues} == {
        "CAPABILITY_CONTRACT_MISMATCH"
    }


def test_legacy_override_snapshot_is_path_free(dataset_path: Path) -> None:
    override = dataset_path.parent / "capability_bundles" / "fixture"
    loaded = build_legacy_suite(
        dataset=dataset_path,
        provider="fixture_provider_v1",
        capability_bundle=override,
        filters=None,
        run_config=RunConfig(run_mode="framework_self_test"),
    )
    catalog = PluginCatalog()
    catalog.register(
        _descriptor("legacy_jsonl_eval_case_v1", "dataset_loader"),
        LegacyJsonlDatasetLoader(),
    )
    catalog.register(
        _descriptor("fixture_provider_v1", "provider"), FixtureProviderFactory()
    )

    compiled = compile_suite(loaded, catalog, ContractStore(loaded.root))

    assert str(override) not in json.dumps(compiled.compiled_suite_snapshot)
    assert (
        "bundle_override_sha256"
        in compiled.compiled_suite_snapshot["runtime_provider_config"]
    )


def test_legacy_override_is_used_by_semantic_preflight(dataset_path: Path) -> None:
    manifest_path = dataset_path.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    override = dataset_path.parent / manifest["capability_bundle"]["path"]
    bundle = CapabilityBundle.load(override)
    manifest.pop("capability_bundle")
    manifest["capability_bundle_sha256"] = "legacy-semantic-hash"
    manifest["capability_snapshots"] = [
        {
            "snapshot_id": item.snapshot_id,
            "snapshot_sha256": item.snapshot_sha256,
        }
        for item in bundle.documents
    ]
    manifest_path.write_text(json.dumps(manifest))
    loaded = build_legacy_suite(
        dataset=dataset_path,
        provider="mini_agent",
        capability_bundle=override,
        filters=None,
        run_config=RunConfig(run_mode="framework_self_test"),
    )

    compiled = compile_suite(
        loaded,
        default_plugin_catalog(),
        ContractStore(loaded.root),
    )

    assert compiled.runtime_provider_config["bundle_override"] == str(override)


def test_suite_zero_numeric_flag_is_not_silently_ignored(
    tmp_path: Path, capsys
) -> None:
    suite = tmp_path / "suite.json"
    suite.write_text("{}")

    assert (
        main(
            [
                "run",
                "--suite",
                str(suite),
                "--output-dir",
                str(tmp_path / "out"),
                "--trials",
                "0",
            ]
        )
        == 2
    )

    assert "cannot be combined" in json.loads(capsys.readouterr().out)["message"]


def test_run_persists_structured_compilation_issues(tmp_path: Path, capsys) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text("{}\n")
    suite = tmp_path / "suite.json"
    suite.write_text(
        json.dumps(
            {
                "suite_id": "invalid",
                "suite_version": "1",
                "dataset_loader": {
                    "plugin_id": "legacy_jsonl_eval_case_v1",
                    "version": "1.0.0",
                },
                "dataset_sources": [{"path": dataset.name, "sha256": "0" * 64}],
                "provider": {"plugin_id": "missing", "version": "1.0.0"},
            }
        )
    )

    assert (
        main(["run", "--suite", str(suite), "--output-dir", str(tmp_path / "out")]) == 2
    )
    paths = json.loads(capsys.readouterr().out)
    record = json.loads(Path(paths["record"]).read_text())

    assert {item["code"] for item in record["issues"]} == {
        "PLUGIN_NOT_FOUND",
        "SOURCE_FINGERPRINT_MISMATCH",
    }
