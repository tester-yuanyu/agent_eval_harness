from __future__ import annotations

import json
from pathlib import Path

import pytest

from capability_snapshot_kit.exporting import export_capability_bundle_v3
from capability_snapshot_kit.hashing import calculate_snapshot_sha256
from capability_snapshot_kit.spec_loader import load_capability_spec_pack_v3
from capability_snapshot_kit.validation import (
    CapabilityBundleValidationErrorV3,
    load_capability_bundle_v3,
    validate_capability_bundle_v3,
)
from tests.support.capability_adapter import FakeCapabilityAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPECS = load_capability_spec_pack_v3(PROJECT_ROOT / "capability_specs")


def _export(root: Path) -> None:
    export_capability_bundle_v3(root, SPECS, FakeCapabilityAdapter())


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _rehash(payload: dict) -> None:
    payload["snapshot_sha256"] = calculate_snapshot_sha256(payload)


def test_valid_non_minimal_agent_bundle_loads_as_typed_graph(
    tmp_path: Path,
) -> None:
    root = tmp_path / "bundle"
    _export(root)

    result = validate_capability_bundle_v3(root)
    bundle = load_capability_bundle_v3(root)

    assert result.valid is True
    assert result.snapshot_counts == {
        "agent": 1,
        "module": 1,
        "intent": 1,
        "tool": 0,
        "scope": 5,
        "chain": 3,
        "evidence": 5,
        "boundary": 7,
    }
    assert bundle.agent.agent_id == "example_agent"


def test_validation_rejects_hash_schema_and_unexpected_json(
    tmp_path: Path,
) -> None:
    hash_root = tmp_path / "hash"
    _export(hash_root)
    scope_path = hash_root / "scopes" / "context.json"
    scope = _read(scope_path)
    scope["description"] = "tampered"
    _write(scope_path, scope)
    with pytest.raises(CapabilityBundleValidationErrorV3, match="snapshot_sha256"):
        validate_capability_bundle_v3(hash_root)

    schema_root = tmp_path / "schema"
    _export(schema_root)
    schema_path = schema_root / "schemas" / "scope.schema.json"
    schema = _read(schema_path)
    schema["title"] = "Drifted"
    _write(schema_path, schema)
    with pytest.raises(CapabilityBundleValidationErrorV3, match="Schema artifact"):
        validate_capability_bundle_v3(schema_root)

    unexpected_root = tmp_path / "unexpected"
    _export(unexpected_root)
    (unexpected_root / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(CapabilityBundleValidationErrorV3, match="unexpected JSON"):
        validate_capability_bundle_v3(unexpected_root)


def test_validation_rejects_dangling_escape_and_out_of_scope_artifacts(
    tmp_path: Path,
) -> None:
    dangling = tmp_path / "dangling"
    _export(dangling)
    (dangling / "evidence" / "tool_trace.json").unlink()
    with pytest.raises(CapabilityBundleValidationErrorV3, match="missing referenced"):
        validate_capability_bundle_v3(dangling)

    escaping = tmp_path / "escaping"
    _export(escaping)
    agent_path = escaping / "agent.json"
    agent = _read(agent_path)
    agent["module_refs"][0]["path"] = "../escape.json"
    _rehash(agent)
    _write(agent_path, agent)
    with pytest.raises(CapabilityBundleValidationErrorV3, match="dot segments|escapes"):
        validate_capability_bundle_v3(escaping)

    outside = tmp_path / "outside"
    _export(outside)
    source = _read(outside / "modules" / "intent_router.json")
    source["snapshot_id"] = "module.unscoped"
    source["module_id"] = "unscoped"
    _rehash(source)
    _write(outside / "modules" / "unscoped.json", source)
    with pytest.raises(CapabilityBundleValidationErrorV3, match="outside Agent scope"):
        validate_capability_bundle_v3(outside)


def test_validation_reports_cycle_and_unavailable_supported_evidence(
    tmp_path: Path,
) -> None:
    cycle_root = tmp_path / "cycle"
    _export(cycle_root)
    module_path = cycle_root / "modules" / "intent_router.json"
    module = _read(module_path)
    module["module_refs"] = [
        next(
            ref
            for ref in _read(cycle_root / "agent.json")["module_refs"]
            if ref["snapshot_id"] == "module.intent_router"
        )
    ]
    _rehash(module)
    _write(module_path, module)
    with pytest.raises(
        CapabilityBundleValidationErrorV3,
        match="module.intent_router -> module.intent_router",
    ):
        validate_capability_bundle_v3(cycle_root)

    evidence_root = tmp_path / "evidence"
    _export(evidence_root)
    module_path = evidence_root / "modules" / "intent_router.json"
    module = _read(module_path)
    module["capabilities"][0]["evidence_ids"] = ["evidence.context_state"]
    _rehash(module)
    _write(module_path, module)
    with pytest.raises(
        CapabilityBundleValidationErrorV3,
        match="unavailable Evidence.*context_state",
    ):
        validate_capability_bundle_v3(evidence_root)
