from __future__ import annotations

import json

from dataset_builder.pipeline import validate_draft


def test_generation_request_binds_complete_v3_provenance(authored, suite):
    workspace, request, _, _ = authored

    assert request.profile_binding["sha256"] == suite.capability_profile.sha256
    assert request.adapter_binding["implementation_sha256"] == (
        suite.capability_adapter_registration.implementation_sha256
    )
    assert request.capability_ir_binding == {
        "schema_version": "1.0",
        "sha256": suite.capability_ir.canonical_sha256,
    }
    assert request.capability_bundle_sha256 == (
        suite.validated_capability_bundle.capability_bundle_sha256
    )
    assert request.trusted_schema_bindings
    assert request.capability_source_artifacts
    assert (workspace / "capability_ir.json").is_file()


def test_ir_binding_drift_marks_dataset_stale(authored, suite):
    workspace, _, _, _ = authored
    request_path = workspace / "generation_request.json"
    request = json.loads(request_path.read_text())
    request["capability_ir_binding"]["sha256"] = "0" * 64
    request_path.write_text(json.dumps(request))

    report = validate_draft(suite, workspace / "draft.jsonl")
    gate = next(
        item for item in report.gates if item.name == "capability_snapshot"
    )
    assert report.state == "STALE"
    assert not gate.passed
    assert any("Capability IR" in issue for issue in gate.issues)
    assert gate.details["impacted_slots"]


def test_generation_manifest_contains_same_v3_bindings(authored):
    workspace, request, _, _ = authored
    manifest = json.loads((workspace / "generation_manifest.json").read_text())
    for field in (
        "profile_binding",
        "trusted_schema_bindings",
        "adapter_binding",
        "capability_ir_binding",
        "capability_selection",
        "capability_source_artifacts",
        "agent_snapshot_sha256",
        "capability_bundle_sha256",
    ):
        assert manifest[field] == request.model_dump(mode="json")[field]
