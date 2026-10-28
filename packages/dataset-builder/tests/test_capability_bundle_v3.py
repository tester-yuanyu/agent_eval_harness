from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dataset_builder.capability_bundle import (
    CapabilityBundleError,
    calculate_artifact_sha256,
    load_validated_bundle,
)
from dataset_builder.capability_profiles import load_trusted_profile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_BUNDLE = ROOT.parent / "mini_agent" / "capabilities"
TRUST_STORE = ROOT / "protocol_profiles" / "trust_store.json"


def _copy_bundle(tmp_path: Path) -> Path:
    destination = tmp_path / "capabilities"
    shutil.copytree(SOURCE_BUNDLE, destination)
    return destination


def _profile():
    return load_trusted_profile(
        "capability-snapshot",
        "3.0",
        TRUST_STORE,
    )


def _rewrite(path: Path, payload: dict) -> None:
    payload["snapshot_sha256"] = calculate_artifact_sha256(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def test_validates_standalone_v3_bundle_and_indexes_complete_graph():
    bundle = load_validated_bundle(SOURCE_BUNDLE, _profile())

    assert bundle.root.snapshot_id == "agent.mini_agent"
    assert bundle.capability_bundle_sha256 == (
        "99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8"
    )
    assert bundle.snapshot_counts == {
        "agent": 1,
        "boundary": 7,
        "chain": 3,
        "evidence": 5,
        "intent": 7,
        "module": 7,
        "scope": 5,
        "tool": 0,
    }
    closure = bundle.reference_closure(
        ("scope.understanding", "intent.query_user")
    )
    assert {
        "scope.understanding",
        "intent.query_user",
        "module.intent_router",
        "evidence.intent_result",
        "boundary.understanding",
    } <= {item.snapshot_id for item in closure}


def test_bundle_manifest_is_not_read(tmp_path):
    root = _copy_bundle(tmp_path)
    (root / "bundle_manifest.json").write_text("not json")

    bundle = load_validated_bundle(root, _profile())

    assert bundle.root.relative_path == "agent.json"
    assert "bundle_manifest.json" not in bundle.artifacts_by_path


def test_rejects_artifact_hash_mismatch(tmp_path):
    root = _copy_bundle(tmp_path)
    path = root / "intents" / "query_user.json"
    payload = json.loads(path.read_text())
    payload["semantic_rules"]["bare_integer"] = "GUESS"
    path.write_text(json.dumps(payload))

    with pytest.raises(CapabilityBundleError, match="artifact_hash_mismatch"):
        load_validated_bundle(root, _profile())


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("snapshot_sha256", "0" * 64, "reference_hash_mismatch"),
        ("snapshot_format_version", "9.9", "reference_version_mismatch"),
        ("snapshot_type", "module", "reference_type_mismatch"),
        ("path", "../outside.json", "unsafe_reference_path"),
    ],
)
def test_rejects_invalid_reference_bindings(tmp_path, field, value, code):
    root = _copy_bundle(tmp_path)
    agent_path = root / "agent.json"
    agent = json.loads(agent_path.read_text())
    reference = next(
        item
        for item in agent["intent_refs"]
        if item["snapshot_id"] == "intent.query_user"
    )
    reference[field] = value
    _rewrite(agent_path, agent)

    with pytest.raises(CapabilityBundleError, match=code):
        load_validated_bundle(root, _profile())


def test_rejects_dangling_and_unreferenced_artifacts(tmp_path):
    dangling = _copy_bundle(tmp_path / "dangling")
    agent_path = dangling / "agent.json"
    agent = json.loads(agent_path.read_text())
    agent["intent_refs"][0]["path"] = "intents/missing.json"
    _rewrite(agent_path, agent)
    with pytest.raises(CapabilityBundleError, match="dangling_reference"):
        load_validated_bundle(dangling, _profile())

    unreferenced = _copy_bundle(tmp_path / "unreferenced")
    source = unreferenced / "intents" / "query_gift.json"
    payload = json.loads(source.read_text())
    payload["snapshot_id"] = "intent.unreferenced"
    payload["capability_id"] = "unreferenced"
    _rewrite(unreferenced / "intents" / "unreferenced.json", payload)
    with pytest.raises(CapabilityBundleError, match="unreferenced_artifact"):
        load_validated_bundle(unreferenced, _profile())


def test_rejects_duplicate_id_and_reference_cycle(tmp_path):
    duplicate = _copy_bundle(tmp_path / "duplicate")
    source = duplicate / "intents" / "query_gift.json"
    payload = json.loads(source.read_text())
    payload["snapshot_id"] = "intent.query_user"
    _rewrite(source, payload)
    with pytest.raises(CapabilityBundleError, match="duplicate_snapshot_id"):
        load_validated_bundle(duplicate, _profile())

    cyclic = _copy_bundle(tmp_path / "cyclic")
    module_path = cyclic / "modules" / "intent_router.json"
    module = json.loads(module_path.read_text())
    module["module_refs"] = [
        {
            "snapshot_id": "module.intent_router",
            "snapshot_type": "module",
            "snapshot_format_version": "3.0",
            "contract_version": module["contract_version"],
            "snapshot_sha256": module["snapshot_sha256"],
            "path": "modules/intent_router.json",
        }
    ]
    _rewrite(module_path, module)
    module["module_refs"][0]["snapshot_sha256"] = module["snapshot_sha256"]
    _rewrite(module_path, module)
    agent_path = cyclic / "agent.json"
    agent = json.loads(agent_path.read_text())
    reference = next(
        item
        for item in agent["module_refs"]
        if item["snapshot_id"] == "module.intent_router"
    )
    reference["snapshot_sha256"] = module["snapshot_sha256"]
    _rewrite(agent_path, agent)
    with pytest.raises(CapabilityBundleError, match="reference_cycle"):
        load_validated_bundle(cyclic, _profile())


def test_rejects_bundle_hash_and_schema_mismatch(tmp_path):
    root = _copy_bundle(tmp_path / "bundle")
    agent_path = root / "agent.json"
    agent = json.loads(agent_path.read_text())
    agent["capability_bundle_sha256"] = "0" * 64
    _rewrite(agent_path, agent)
    with pytest.raises(CapabilityBundleError, match="bundle_hash_mismatch"):
        load_validated_bundle(root, _profile())

    schema_root = _copy_bundle(tmp_path / "schema")
    (schema_root / "schemas" / "intent.schema.json").write_text(
        '{"type":"object"}\n'
    )
    with pytest.raises(ValueError, match="trusted schema hash mismatch"):
        load_validated_bundle(schema_root, _profile())
