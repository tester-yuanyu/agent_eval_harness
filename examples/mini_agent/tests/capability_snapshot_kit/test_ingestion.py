from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from capability_snapshot_kit.ingestion.models import FactDocument, SourceReference
from capability_snapshot_kit.ingestion.providers import AdapterCollector, load_plugin
from capability_snapshot_kit.ingestion.sources import check_sources
from tests.support.capability_adapter import FakeCapabilityAdapter


def document(root: Path) -> FactDocument:
    path = root / "agent.py"
    path.write_text('def run(): return "hello"\n')
    result = AdapterCollector(FakeCapabilityAdapter()).collect(root)
    payload = result.model_dump(mode="json")
    payload["sources"] = {
        "implementation": {
            "path": "agent.py",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "kind": "code",
        }
    }
    payload["origins"] = {key: ["implementation"] for key in result.fact_index()}
    return FactDocument.model_validate(payload)


def test_document_roundtrip_and_duplicate_fact_rejected(tmp_path):
    facts = document(tmp_path)
    assert facts == FactDocument.model_validate_json(facts.model_dump_json())
    assert facts.tool_facts() == ()
    payload = facts.model_dump(mode="json")
    payload["modules"] *= 2
    with pytest.raises(ValidationError, match="duplicate"):
        FactDocument.model_validate(payload)


def test_unknown_provenance_and_extra_fields_rejected(tmp_path):
    payload = document(tmp_path).model_dump(mode="json")
    payload["origins"]["module.missing"] = ["implementation"]
    with pytest.raises(ValidationError, match="unknown fact"):
        FactDocument.model_validate(payload)
    payload["origins"].pop("module.missing")
    payload["origins"]["agent.example_agent"] = ["missing"]
    with pytest.raises(ValidationError, match="unknown source"):
        FactDocument.model_validate(payload)
    payload = document(tmp_path).model_dump(mode="json")
    payload["plugin"] = "malicious:factory"
    with pytest.raises(ValidationError):
        FactDocument.model_validate(payload)


def test_source_hash_and_symlink_escape(tmp_path):
    facts = document(tmp_path)
    check_sources(facts, tmp_path)
    (tmp_path / "agent.py").write_text("changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        check_sources(facts, tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.write_text("secret")
    (tmp_path / "agent.py").unlink()
    (tmp_path / "agent.py").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        check_sources(facts, tmp_path)


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "a/../b", "a\\b"])
def test_source_paths_must_be_relative(path):
    with pytest.raises(ValidationError):
        SourceReference(path=path, sha256="a" * 64, kind="code")


def test_explicit_factory_validation():
    with pytest.raises(ValueError, match="module:factory"):
        load_plugin("not-a-factory", "collect")
    with pytest.raises(ValueError, match="collect"):
        load_plugin("builtins:dict", "collect")


def test_model_document_cannot_claim_observed(tmp_path):
    payload = json.loads(document(tmp_path).model_dump_json())
    payload["observed"] = True
    with pytest.raises(ValidationError):
        FactDocument.model_validate(payload)


def test_candidate_support_is_unknown_and_original_claim_is_reported(tmp_path):
    from capability_snapshot_kit.ingestion.reconcile import reconcile

    candidate = document(tmp_path)
    effective, provenance, gaps = reconcile(None, candidate)
    claim = effective.modules[0].capabilities[0]
    assert claim.support_status == "unknown"
    assert effective.evidence[0].availability.support_status == "unknown"
    entry = provenance["facts"]["module.intent_router"]
    assert entry["basis"] == "declared"
    assert entry["claims"][0]["declared_status"] == "supported"
    assert entry["claims"][0]["effective_status"] == "unknown"
    assert any(gap["code"] == "UNVERIFIED_DECLARATION" for gap in gaps)
    assert candidate.modules[0].capabilities[0].support_status == "supported"


def test_candidate_cannot_override_runtime_or_add_registered_tool(tmp_path):
    from capability_snapshot_kit.ingestion.reconcile import reconcile
    from examples.full_tool_fixture import create_registry
    from minimal_agent.capability_adapter import MiniAgentCapabilityAdapter
    from minimal_agent.contracts import build_default_intent_registry

    runtime = document(tmp_path)
    conflicting = runtime.model_dump(mode="json")
    conflicting["modules"][0]["output_schema"] = {"type": "string"}
    with pytest.raises(ValueError, match="conflicting fact: module.intent_router"):
        reconcile(runtime, FactDocument.model_validate(conflicting))
    tool_document = AdapterCollector(
        MiniAgentCapabilityAdapter(
            build_default_intent_registry(),
            create_registry(),
        )
    ).collect(tmp_path)
    with pytest.raises(ValueError, match="registered tool"):
        reconcile(None, tool_document)


def test_runtime_source_and_candidate_source_remain_distinct(tmp_path):
    from capability_snapshot_kit.ingestion.reconcile import reconcile

    runtime = document(tmp_path)
    effective, provenance, _ = reconcile(runtime, runtime)
    assert effective.modules == runtime.modules
    assert provenance["facts"]["module.intent_router"]["basis"] == "configured"
    assert set(effective.sources) == {
        "collector/implementation",
        "candidate/implementation",
    }
    assert provenance["execution_verified"] is False


def test_delivery_is_immutable_valid_and_deterministic(tmp_path):
    from capability_snapshot_kit import validate_capability_bundle
    from capability_snapshot_kit.ingestion.service import export_delivery

    facts = document(tmp_path)
    specs = Path(__file__).resolve().parents[2] / "capability_specs"
    a, b = tmp_path / "a", tmp_path / "b"
    export_delivery(a, source_root=tmp_path, spec_root=specs, runtime=facts)
    export_delivery(b, source_root=tmp_path, spec_root=specs, runtime=facts)
    assert validate_capability_bundle(a / "bundle").valid
    for path in a.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (b / path.relative_to(a)).read_bytes()
    manifest = json.loads((a / "manifest.json").read_text())
    for name, digest in manifest["files_sha256"].items():
        assert hashlib.sha256((a / name).read_bytes()).hexdigest() == digest
    with pytest.raises(FileExistsError):
        export_delivery(a, source_root=tmp_path, spec_root=specs, runtime=facts)
    assert (a / "manifest.json").exists()


def test_invalid_sources_and_conflicts_write_no_delivery(tmp_path):
    from capability_snapshot_kit.ingestion.service import export_delivery

    facts = document(tmp_path)
    (tmp_path / "agent.py").write_text("modified")
    target = tmp_path / "output"
    with pytest.raises(ValueError, match="hash mismatch"):
        export_delivery(
            target,
            source_root=tmp_path,
            spec_root=Path("capability_specs"),
            runtime=facts,
        )
    assert not target.exists()
