from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from conftest import module_case

from eval_framework.capabilities import (
    CapabilityBundle,
    CapabilityBundleError,
    CapabilityRegistry,
    canonical_json_bytes,
)
from eval_framework.dataset_loader import load_dataset


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_document(root: Path, name: str, payload: dict) -> dict[str, str]:
    value = dict(payload)
    value["snapshot_sha256"] = _sha256_bytes(canonical_json_bytes(value))
    path = root / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return {"path": name, "sha256": _sha256_bytes(path.read_bytes())}


def _write_bundle(root: Path, *, duplicate: bool = False) -> dict:
    root.mkdir(parents=True)
    files = [
        _write_document(
            root,
            "intent_router.json",
            {
                "snapshot_format_version": "1.0",
                "snapshot_id": "intent_router",
                "snapshot_type": "module",
                "module_id": "intent_router",
                "module_contract_version": "intent-router-contract-v2",
                "output_schema": {"type": "object"},
            },
        ),
        _write_document(
            root,
            "query_user.json",
            {
                "snapshot_format_version": "2.0",
                "snapshot_id": "query_user",
                "snapshot_type": "intent_capability",
                "capability_id": "query_user",
                "module_id": "intent_router",
                "contract_version": "query-user-intent-contract-v3",
                "parameters_schema": {"type": "object"},
            },
        ),
    ]
    if duplicate:
        files.append(
            _write_document(
                root,
                "query_user_duplicate.json",
                {
                    "snapshot_format_version": "2.0",
                    "snapshot_id": "query_user_duplicate",
                    "snapshot_type": "intent_capability",
                    "capability_id": "query_user",
                    "module_id": "intent_router",
                    "contract_version": "query-user-intent-contract-v3",
                    "parameters_schema": {"type": "object"},
                },
            )
        )
    identity = {
        "provider_id": "mini_agent",
        "bundle_format_version": "1.0",
        "files": files,
    }
    manifest = {
        **identity,
        "capability_bundle_sha256": _sha256_bytes(canonical_json_bytes(identity)),
    }
    (root / "bundle_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    return manifest


def test_load_capability_bundle_verifies_every_hash(tmp_path):
    root = tmp_path / "bundle"
    _write_bundle(root)
    document = root / "query_user.json"
    document.write_text(document.read_text() + " ")

    with pytest.raises(CapabilityBundleError) as error:
        CapabilityBundle.load(root)

    assert error.value.code == "CAPABILITY_BUNDLE_INVALID"
    assert "query_user.json" in str(error.value)


def test_bundle_rejects_parent_path_escape(tmp_path):
    root = tmp_path / "bundle"
    manifest = _write_bundle(root)
    manifest["files"][0]["path"] = "../escape.json"
    identity = {
        "provider_id": manifest["provider_id"],
        "bundle_format_version": manifest["bundle_format_version"],
        "files": manifest["files"],
    }
    manifest["capability_bundle_sha256"] = _sha256_bytes(
        canonical_json_bytes(identity)
    )
    (root / "bundle_manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(CapabilityBundleError) as error:
        CapabilityBundle.load(root)

    assert error.value.code == "CAPABILITY_BUNDLE_INVALID"
    assert "outside bundle" in str(error.value)


def test_duplicate_capability_id_is_rejected(tmp_path):
    root = tmp_path / "bundle"
    _write_bundle(root, duplicate=True)

    with pytest.raises(CapabilityBundleError) as error:
        CapabilityBundle.load(root)

    assert error.value.code == "CAPABILITY_BUNDLE_INVALID"
    assert "duplicate capability_id" in str(error.value)


def test_dataset_loader_exposes_relative_bundle_binding(tmp_path):
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(json.dumps(module_case()) + "\n")
    dataset_sha = _sha256_bytes(dataset.read_bytes())
    bundle_root = tmp_path / "capability_bundles" / "bundle-id"
    bundle_manifest = _write_bundle(bundle_root)
    manifest = {
        "suite_id": "fixture-suite",
        "dataset_version": "1.4",
        "state": "FROZEN",
        "dataset_sha256": dataset_sha,
        "capability_bundle": {
            "provider_id": "mini_agent",
            "sha256": bundle_manifest["capability_bundle_sha256"],
            "path": "capability_bundles/bundle-id",
        },
    }
    dataset.with_suffix(".manifest.json").write_text(json.dumps(manifest))

    loaded = load_dataset(dataset)

    assert loaded.provider_id == "mini_agent"
    assert loaded.capability_bundle_sha256 == bundle_manifest[
        "capability_bundle_sha256"
    ]
    assert loaded.capability_bundle_path == str(bundle_root.resolve())


def test_load_v2_bundle_uses_source_capability_identity():
    root = Path(__file__).resolve().parents[1]
    dataset = load_dataset(
        root / "datasets/mini_agent/module_query_user_intent_v1_5.jsonl"
    )

    bundle = CapabilityBundle.load(Path(dataset.capability_bundle_path))

    assert bundle.bundle_format_version == "2.0"
    assert bundle.capability_bundle_sha256 == dataset.capability_bundle_sha256
    assert bundle.get_document("agent.mini_agent").snapshot_type == "agent"


def test_v2_registry_indexes_typed_module_intent_and_tool_snapshots():
    root = Path(__file__).resolve().parents[1]
    dataset = load_dataset(
        root / "datasets/mini_agent/module_query_user_intent_v1_5.jsonl"
    )
    registry = CapabilityRegistry(
        CapabilityBundle.load(Path(dataset.capability_bundle_path))
    )

    assert registry.get_module("intent_router").snapshot_id == (
        "module.intent_router"
    )
    assert registry.get_capability("query_user").snapshot_id == (
        "intent.query_user"
    )
    assert registry.get_tool("query_user_info").snapshot_id == (
        "tool.query_user_info"
    )


def test_load_live_v2_directory_uses_agent_declared_bundle_identity():
    root = Path("/Users/yuanyu/Documents/ChatGPT/mini_agent/capabilities")

    bundle = CapabilityBundle.load_v2_directory(root)

    assert bundle.bundle_format_version == "2.0"
    assert bundle.capability_bundle_sha256 == bundle.get_document(
        "agent.mini_agent"
    ).payload["capability_bundle_sha256"]


def test_live_v2_loader_follows_root_references_and_ignores_stale_files(tmp_path):
    root = tmp_path / "capabilities"
    (root / "modules").mkdir(parents=True)
    (root / "intents").mkdir()
    module = {
        "snapshot_id": "module.intent_router",
        "snapshot_type": "module",
        "snapshot_format_version": "2.0",
        "contract_version": "intent-router-v2.0",
        "module_id": "intent_router",
    }
    module["snapshot_sha256"] = _sha256_bytes(canonical_json_bytes(module))
    (root / "modules/intent_router.json").write_text(json.dumps(module))
    reference = {
        "snapshot_id": module["snapshot_id"],
        "snapshot_type": module["snapshot_type"],
        "snapshot_format_version": module["snapshot_format_version"],
        "contract_version": module["contract_version"],
        "snapshot_sha256": module["snapshot_sha256"],
        "path": "modules/intent_router.json",
    }
    bundle_hash = _sha256_bytes(canonical_json_bytes([reference]))
    agent = {
        "snapshot_id": "agent.mini_agent",
        "snapshot_type": "agent",
        "snapshot_format_version": "2.0",
        "contract_version": "agent-v2.0",
        "module_refs": [reference],
        "capability_bundle_sha256": bundle_hash,
    }
    agent["snapshot_sha256"] = _sha256_bytes(canonical_json_bytes(agent))
    (root / "agent.json").write_text(json.dumps(agent))
    stale = {
        "snapshot_id": "intent.stale",
        "snapshot_type": "intent",
        "snapshot_format_version": "2.0",
        "contract_version": "stale-v2.0",
        "capability_id": "stale",
    }
    stale["snapshot_sha256"] = _sha256_bytes(canonical_json_bytes(stale))
    (root / "intents/stale.json").write_text(json.dumps(stale))

    bundle = CapabilityBundle.load_v2_directory(root)

    assert {item.snapshot_id for item in bundle.documents} == {
        "agent.mini_agent",
        "module.intent_router",
    }
