from __future__ import annotations

import json
from pathlib import Path

from test_compiled_execution import (
    FixtureProviderFactory,
    _descriptor,
)

from eval_framework.cli import main
from eval_framework.compatibility.suite_builder import build_legacy_suite
from eval_framework.compiled_execution import execute_compiled_suite
from eval_framework.contracts.compiler import compile_suite, load_suite_definition
from eval_framework.contracts.store import ContractStore, sha256_bytes
from eval_framework.plugins.builtin.dataset_loaders import (
    JsonDocumentDatasetLoader,
    LegacyJsonlDatasetLoader,
)
from eval_framework.plugins.catalog import PluginCatalog
from eval_framework.schemas import DatasetFilters, RunConfig


def _suite_file(
    root: Path,
    *,
    dataset_name: str,
    dataset_hash: str,
    loader_id: str,
    provider_id: str = "fixture_provider_v1",
) -> Path:
    payload = {
        "schema_version": "1.0",
        "suite_id": "cli-fixture",
        "suite_version": "1.0.0",
        "lifecycle_state": "FROZEN",
        "dataset_loader": {
            "plugin_id": loader_id,
            "version": "1.0.0",
            "config": {},
        },
        "dataset_sources": [{"path": dataset_name, "sha256": dataset_hash}],
        "provider": {
            "plugin_id": provider_id,
            "version": "1.0.0",
            "config": {},
        },
        "run_config": {
            "run_mode": "framework_self_test",
            "filters": {"case_ids": ["MODULE-1"]},
        },
    }
    manifest = root / Path(dataset_name).with_suffix(".manifest.json")
    if loader_id == "legacy_jsonl_eval_case_v1" and manifest.is_file():
        payload["dataset_sources"].append(
            {"path": manifest.name, "sha256": sha256_bytes(manifest.read_bytes())}
        )
        manifest_value = json.loads(manifest.read_text())
        binding = manifest_value.get("capability_bundle")
        if isinstance(binding, dict):
            bundle_manifest = root / binding["path"] / "bundle_manifest.json"
            payload["capability_bundle"] = {
                "contract_id": "fixture_capability_bundle",
                "version": "2.0",
                "path": str(bundle_manifest.relative_to(root)),
                "sha256": sha256_bytes(bundle_manifest.read_bytes()),
            }
    path = root / "suite.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _catalog(factory=None) -> tuple[PluginCatalog, FixtureProviderFactory]:
    factory = factory or FixtureProviderFactory()
    catalog = PluginCatalog()
    catalog.register(
        _descriptor("legacy_jsonl_eval_case_v1", "dataset_loader"),
        LegacyJsonlDatasetLoader(),
    )
    catalog.register(
        _descriptor("fixture_json_document_v1", "dataset_loader"),
        JsonDocumentDatasetLoader(),
    )
    catalog.register(
        _descriptor("fixture_provider_v1", "provider"),
        factory,
    )
    return catalog, factory


def _normalized_result(result) -> dict:
    payload = result.model_dump(mode="json")
    for field in (
        "run_directory",
        "evaluator_run_id",
        "started_at",
        "finished_at",
        "total_duration_ms",
        "compiled_suite_sha256",
        "compiled_suite_snapshot",
        "plugin_fingerprints",
        "contract_fingerprints",
        "native_artifacts",  # Inspect gives each run its own log UUID.
    ):
        payload.pop(field)
    for case in payload["cases"]:
        for field in (
            "evaluator_run_id",
            "session_id",
            "latency_ms",
            "execution_started_at",
            "execution_finished_at",
        ):
            case.pop(field)
    for field in ("average_latency_ms", "median_latency_ms", "max_latency_ms"):
        payload["summary"].pop(field)
    if payload["summary"]["performance"] is not None:
        for field in ("latency_p50_ms", "latency_p95_ms"):
            payload["summary"]["performance"].pop(field)
    if payload["stability"] is not None:
        payload["stability"].pop("latency_p50_ms")
        payload["stability"].pop("latency_p95_ms")
        for case in payload["stability"]["cases"]:
            case.pop("latency_p50_ms")
            case.pop("latency_p95_ms")
    return payload


def test_validate_accepts_suite_without_creating_provider(
    dataset_path: Path,
    monkeypatch,
    capsys,
) -> None:
    suite_path = _suite_file(
        dataset_path.parent,
        dataset_name=dataset_path.name,
        dataset_hash=sha256_bytes(dataset_path.read_bytes()),
        loader_id="legacy_jsonl_eval_case_v1",
    )
    catalog, factory = _catalog()
    monkeypatch.setattr("eval_framework.cli.default_plugin_catalog", lambda: catalog)

    assert main(["validate", "--suite", str(suite_path)]) == 0

    assert factory.calls == []
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_suite_rejects_legacy_source_flags(capsys) -> None:
    code = main(
        [
            "validate",
            "--suite",
            "suite.json",
            "--dataset",
            "cases.jsonl",
        ]
    )

    assert code == 2
    assert "cannot be combined" in json.loads(capsys.readouterr().out)["message"]


def test_validate_reports_structured_compilation_issues_before_provider(
    dataset_path: Path,
    monkeypatch,
    capsys,
) -> None:
    suite_path = _suite_file(
        dataset_path.parent,
        dataset_name=dataset_path.name,
        dataset_hash="0" * 64,
        loader_id="legacy_jsonl_eval_case_v1",
        provider_id="missing_provider",
    )
    catalog, factory = _catalog()
    monkeypatch.setattr("eval_framework.cli.default_plugin_catalog", lambda: catalog)

    assert main(["validate", "--suite", str(suite_path)]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["error_code"] == "SUITE_COMPILATION_FAILED"
    assert {item["code"] for item in payload["issues"]} == {
        "PLUGIN_NOT_FOUND",
        "SOURCE_FINGERPRINT_MISMATCH",
    }
    assert factory.calls == []


def test_authored_suite_rejects_judge_until_backend_plugin_migration(
    dataset_path: Path,
    monkeypatch,
    capsys,
) -> None:
    suite_path = _suite_file(
        dataset_path.parent,
        dataset_name=dataset_path.name,
        dataset_hash=sha256_bytes(dataset_path.read_bytes()),
        loader_id="legacy_jsonl_eval_case_v1",
    )
    payload = json.loads(suite_path.read_text())
    payload["run_config"]["judge"] = {
        "rubric_path": "rubric.json",
        "enabled": True,
        "timeout_seconds": 30,
        "max_retries": 1,
    }
    suite_path.write_text(json.dumps(payload), encoding="utf-8")
    catalog, factory = _catalog()
    monkeypatch.setattr("eval_framework.cli.default_plugin_catalog", lambda: catalog)

    assert main(["validate", "--suite", str(suite_path)]) == 2

    result = json.loads(capsys.readouterr().out)
    assert result["issues"][0]["code"] == "PROFILE_STAGE_NOT_MIGRATED"
    assert factory.calls == []


def test_legacy_builder_and_explicit_suite_produce_equivalent_results(
    dataset_path: Path,
) -> None:
    config = RunConfig(
        run_mode="framework_self_test",
        filters=DatasetFilters(case_ids=["MODULE-1"]),
    )
    explicit_path = _suite_file(
        dataset_path.parent,
        dataset_name=dataset_path.name,
        dataset_hash=sha256_bytes(dataset_path.read_bytes()),
        loader_id="legacy_jsonl_eval_case_v1",
    )
    legacy = build_legacy_suite(
        dataset=dataset_path,
        provider="fixture_provider_v1",
        capability_bundle=None,
        filters=config.filters,
        run_config=config,
    )
    catalog, _ = _catalog()

    explicit_result = execute_compiled_suite(
        compile_suite(
            load_suite_definition(explicit_path),
            catalog,
            ContractStore(dataset_path.parent),
        ),
        catalog,
    )
    legacy_result = execute_compiled_suite(
        compile_suite(legacy, catalog, ContractStore(legacy.root)),
        catalog,
    )

    # Make the elapsed-time difference deterministic even when both fast fixture
    # invocations happen to round to the same millisecond on this machine.
    assert explicit_result.summary.performance is not None
    assert legacy_result.summary.performance is not None
    explicit_result.summary.performance.latency_p50_ms = 10
    explicit_result.summary.performance.latency_p95_ms = 20
    legacy_result.summary.performance.latency_p50_ms = 30
    legacy_result.summary.performance.latency_p95_ms = 40
    assert _normalized_result(explicit_result) == _normalized_result(legacy_result)

    # Normalization must preserve the performance population and Judge usage;
    # dropping the entire performance summary would hide real semantic changes.
    for field, value in (
        ("latency_sample_count", 2),
        ("judge_token_totals", {"MODULE-1/trial_001": 10}),
        ("judge_token_total", 10),
        ("judge_token_max", 10),
    ):
        changed = explicit_result.model_copy(deep=True)
        setattr(changed.summary.performance, field, value)
        assert _normalized_result(changed) != _normalized_result(legacy_result)


def test_legacy_builder_keeps_explicit_capability_override_out_of_suite_document(
    dataset_path: Path,
) -> None:
    override = dataset_path.parent / "capability_bundles" / "fixture"

    loaded = build_legacy_suite(
        dataset=dataset_path,
        provider="mini_agent",
        capability_bundle=override,
        filters=None,
        run_config=RunConfig(run_mode="framework_self_test"),
    )

    assert loaded.definition.provider.plugin_id == "mini_agent_provider_v1"
    assert loaded.definition.provider.config == {}
    assert loaded.runtime_provider_config == {
        "bundle_override": str(override.resolve()),
        "verify_current": True,
    }


def test_run_suite_uses_second_dataset_format_without_runner_changes(
    dataset_path: Path,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    document = json.loads(
        (Path(__file__).parent / "fixtures/json_document_dataset.json").read_text()
    )
    document["metadata"]["provider_id"] = "mini_agent"
    document_path = tmp_path / "cases.json"
    document_path.write_text(json.dumps(document), encoding="utf-8")
    suite_path = _suite_file(
        tmp_path,
        dataset_name=document_path.name,
        dataset_hash=sha256_bytes(document_path.read_bytes()),
        loader_id="fixture_json_document_v1",
    )
    frozen = __import__("eval_framework").load_dataset(dataset_path)

    class DocumentProviderFactory(FixtureProviderFactory):
        def create(self, dataset, model_client_factory=None, **kwargs):
            patched = dataset.model_copy(
                update={
                    "capability_bundle_path": frozen.capability_bundle_path,
                    "capability_bundle_sha256": frozen.capability_bundle_sha256,
                }
            )
            return super().create(patched, model_client_factory, **kwargs)

    catalog, factory = _catalog(DocumentProviderFactory())
    monkeypatch.setattr("eval_framework.cli.default_plugin_catalog", lambda: catalog)

    assert (
        main(["run", "--suite", str(suite_path), "--output-dir", str(tmp_path / "out")])
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert Path(output["results"]).is_file()
    assert len(factory.calls) == 1
