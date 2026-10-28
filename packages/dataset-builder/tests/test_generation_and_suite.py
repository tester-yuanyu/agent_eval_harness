from __future__ import annotations

import json
import shutil
from dataclasses import replace

import pytest

from dataset_builder.generation_client import ScriptedGenerationClient
from dataset_builder.orchestration import StageExecutionError, StageLedger
from dataset_builder.pipeline import (
    generate_candidates,
    ingest_response,
    prepare_generation,
    validate_draft,
)
from dataset_builder.source_pack import build_source_pack
from dataset_builder.suite_definition import load_suite


def test_suite_registry_and_unknown_suite(suite):
    assert suite.suite_id == "mini_agent_intent_v1"
    with pytest.raises(ValueError, match="unknown suite"):
        load_suite("missing")


def test_source_pack_files_and_hashes(suite):
    text, manifest = build_source_pack(suite)
    assert "生成规则 v1" in text
    assert "# 来源文件：coverage_plan.json" in text
    assert "capability_contract.md" not in text
    assert len(manifest) == 3
    assert manifest[0]["path"].startswith("capability-ir://")
    assert all(len(item["sha256"]) == 64 for item in manifest)


def test_source_pack_missing_file_fails(suite, tmp_path):
    missing_suite = replace(suite, source_files_resolved=(tmp_path / "missing.md",))
    with pytest.raises(FileNotFoundError):
        build_source_pack(missing_suite)


def test_suite_declares_source_pack_files(suite):
    custom_names = ("query_user_info_intent_dataset_constraints.md",)
    custom_suite = replace(
        suite,
        source_files_resolved=tuple(suite.suite_dir / name for name in custom_names),
    )

    assert custom_suite.source_files == tuple(
        custom_suite.suite_dir / name for name in custom_names
    )


def test_coverage_plan_has_exactly_fifteen_unique_slots(suite):
    slots = suite.coverage_plan["slots"]
    assert len(slots) == 15
    assert len({slot["slot_id"] for slot in slots}) == 15


def test_scripted_client_success_timeout_error(authored, seed):
    _, request, _, _ = authored
    result = ScriptedGenerationClient(seed).generate(request)
    assert result.mode == "scripted"
    with pytest.raises(TimeoutError):
        ScriptedGenerationClient(seed, error=TimeoutError()).generate(request)
    with pytest.raises(RuntimeError):
        ScriptedGenerationClient(seed, error=RuntimeError()).generate(request)


def test_generation_rejects_tampered_bundle_before_calling_client(
    tmp_path, suite, seed
):
    workspace = tmp_path / "run"
    request = prepare_generation(suite, workspace)
    source = workspace / "capability_bundle" / "agent.json"
    source.write_text(source.read_text() + "\n")

    class FailIfCalled:
        called = False

        def generate(self, request):
            self.called = True
            raise AssertionError("generation client must not be called")

    client = FailIfCalled()
    with pytest.raises(
        StageExecutionError,
        match="prepared capability bundle file hash mismatch",
    ):
        generate_candidates(request, client, workspace)
    assert not client.called


def test_generation_without_workspace_validates_bundle_before_client(
    tmp_path, suite
):
    prepared_workspace = tmp_path / "prepared"
    request = prepare_generation(suite, prepared_workspace)
    source = prepared_workspace / "capability_bundle" / "agent.json"
    source.write_text(source.read_text() + "\n")

    class FailIfCalled:
        called = False

        def generate(self, request):
            self.called = True
            raise AssertionError("generation client must not be called")

    client = FailIfCalled()
    with pytest.raises(
        ValueError,
        match="prepared capability bundle file hash mismatch",
    ):
        generate_candidates(request, client)
    assert not client.called


def test_prepare_does_not_copy_or_bind_bundle_manifest(tmp_path, suite):
    source_bundle = tmp_path / "capabilities"
    shutil.copytree(suite.capability_bundle_path, source_bundle)
    (source_bundle / "bundle_manifest.json").write_text("not json")
    isolated_suite = replace(suite, capability_bundle_path=source_bundle)
    workspace = tmp_path / "run"

    request = prepare_generation(isolated_suite, workspace)

    assert not (workspace / "capability_bundle" / "bundle_manifest.json").exists()
    assert "bundle_manifest.json" not in {
        item["relative_path"] for item in request.capability_bundle_files
    }


def test_external_ingest_preserves_response_and_same_protocol(
    tmp_path, authored, suite, seed
):
    _, request, _, _ = authored
    source = tmp_path / "external.json"
    source.write_text(json.dumps(seed))
    workspace = tmp_path / "external-run"
    raw = ingest_response(request, source, workspace)
    assert raw.mode == "external"
    assert raw.response == seed
    assert (workspace / "raw_response.json").exists()
    assert (workspace / "generation_request.json").exists()


def test_prepare_artifacts_do_not_contain_environment_secret(authored, monkeypatch):
    workspace, _, _, _ = authored
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret")
    all_text = "".join(
        path.read_text() for path in workspace.rglob("*") if path.is_file()
    )
    assert "sk-super-secret" not in all_text


def test_generation_manifest_binds_plugins_and_policies(authored):
    workspace, request, _, _ = authored
    manifest = json.loads((workspace / "generation_manifest.json").read_text())

    assert manifest["plugin_bindings"] == request.plugin_bindings
    assert manifest["policy_bindings"] == request.policy_bindings


def test_public_authoring_pipeline_records_ordered_stages(authored):
    workspace, _, _, _ = authored
    ledger = StageLedger(workspace / "stage_ledger.jsonl")

    assert [record.stage_id for record in ledger.records] == [
        "prepare",
        "generate",
        "compile",
    ]
    assert all(record.status == "succeeded" for record in ledger.records)


def test_validation_appends_a_bound_stage_record(authored):
    workspace, _, _, _ = authored
    suite = load_suite("mini_agent_intent_v1")

    report = validate_draft(suite, workspace / "draft.jsonl", workspace)
    ledger = StageLedger(workspace / "stage_ledger.jsonl")

    assert report.valid
    assert [record.stage_id for record in ledger.records] == [
        "prepare",
        "generate",
        "compile",
        "validate",
    ]
    assert ledger.records[-1].plugin.role == "validation_gate"
