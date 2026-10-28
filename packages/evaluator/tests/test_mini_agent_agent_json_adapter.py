from __future__ import annotations

import hashlib
import json
import shutil
import urllib.request
from pathlib import Path

import pytest

from eval_framework.capabilities import (
    CapabilityBundleError,
    CapabilityRegistry,
    canonical_json_bytes,
)
from eval_framework.providers.mini_agent.capability_adapter import (
    load_mini_agent_capability_bundle,
)

BUNDLE_SHA256 = "99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8"


def _bundle_root() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "datasets/mini_agent/capability_bundles"
        / BUNDLE_SHA256
    )


def test_loads_frozen_agent_json_bundle_without_empty_tools_directory(tmp_path) -> None:
    root = tmp_path / "bundle"
    shutil.copytree(_bundle_root(), root)
    shutil.rmtree(root / "tools", ignore_errors=True)
    assert not (root / "tools").exists()

    bundle = load_mini_agent_capability_bundle(
        root,
        expected_sha256=BUNDLE_SHA256,
    )
    registry = CapabilityRegistry(bundle)

    assert bundle.provider_id == "mini_agent"
    assert bundle.bundle_format_version == "3.0"
    assert bundle.capability_bundle_sha256 == BUNDLE_SHA256
    assert registry.get_module("intent_router").snapshot_id == "module.intent_router"
    assert registry.parameter_schema("query_user")["additionalProperties"] is False
    assert (
        bundle.get_document("evidence.intent_result").payload["observation_interface"]
        == "agent_result.intent_result"
    )


def test_current_capabilities_do_not_require_an_agent_checkout(monkeypatch, tmp_path):
    import minimal_agent

    from eval_framework.providers.mini_agent.provider import _load_current_capabilities

    monkeypatch.setattr(
        minimal_agent, "__file__", str(tmp_path / "minimal_agent/__init__.py")
    )
    registry = _load_current_capabilities()
    assert registry.bundle.provider_id == "mini_agent"
    assert registry.bundle.bundle_format_version == "3.0"
    assert registry.get_module("intent_router").snapshot_id == "module.intent_router"


def test_rejects_expected_bundle_hash_mismatch() -> None:
    with pytest.raises(CapabilityBundleError, match="bundle hash mismatch"):
        load_mini_agent_capability_bundle(
            _bundle_root(),
            expected_sha256="0" * 64,
        )


def test_rejects_missing_referenced_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    shutil.copytree(_bundle_root(), root)
    (root / "intents/query_user.json").unlink()

    with pytest.raises(CapabilityBundleError, match="cannot read bundle file"):
        load_mini_agent_capability_bundle(root)


def test_rejects_reference_metadata_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    shutil.copytree(_bundle_root(), root)
    agent_path = root / "agent.json"
    agent = json.loads(agent_path.read_text(encoding="utf-8"))
    query_user = next(
        item
        for item in agent["intent_refs"]
        if item["snapshot_id"] == "intent.query_user"
    )
    query_user["contract_version"] = "wrong-contract-v9"
    agent_path.write_text(json.dumps(agent), encoding="utf-8")

    with pytest.raises(
        CapabilityBundleError,
        match="reference contract_version mismatch",
    ):
        load_mini_agent_capability_bundle(root)


def test_rejects_reference_path_outside_bundle(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    shutil.copytree(_bundle_root(), root)
    agent_path = root / "agent.json"
    agent = json.loads(agent_path.read_text(encoding="utf-8"))
    agent["intent_refs"][0]["path"] = "../outside.json"
    agent_path.write_text(json.dumps(agent), encoding="utf-8")

    with pytest.raises(CapabilityBundleError, match="outside bundle"):
        load_mini_agent_capability_bundle(root)


def test_rejects_agent_json_symlink_outside_bundle(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    shutil.copytree(_bundle_root(), root)
    outside = tmp_path / "outside-agent.json"
    agent_path = root / "agent.json"
    outside.write_bytes(agent_path.read_bytes())
    agent_path.unlink()
    agent_path.symlink_to(outside)

    with pytest.raises(CapabilityBundleError, match="outside bundle"):
        load_mini_agent_capability_bundle(root)


def test_rejects_external_schema_reference_without_fetching(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "bundle"
    shutil.copytree(_bundle_root(), root)
    (root / "schemas/agent.schema.json").write_text(
        json.dumps({"$ref": "https://schemas.invalid/agent.json"}),
        encoding="utf-8",
    )
    attempted: list[str] = []

    def reject_fetch(request, *args, **kwargs):
        del args, kwargs
        attempted.append(str(request))
        raise AssertionError("external schema fetch attempted")

    monkeypatch.setattr(urllib.request, "urlopen", reject_fetch)

    with pytest.raises(CapabilityBundleError, match="external schema reference"):
        load_mini_agent_capability_bundle(root)
    assert attempted == []


def test_rejects_duplicate_module_id(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    shutil.copytree(_bundle_root(), root)
    module_path = root / "modules/model_gateway.json"
    module = json.loads(module_path.read_text(encoding="utf-8"))
    module["module_id"] = "intent_router"
    module["snapshot_sha256"] = _snapshot_hash(module)
    module_path.write_text(json.dumps(module), encoding="utf-8")

    agent_path = root / "agent.json"
    agent = json.loads(agent_path.read_text(encoding="utf-8"))
    reference = next(
        item
        for item in agent["module_refs"]
        if item["snapshot_id"] == "module.model_gateway"
    )
    reference["snapshot_sha256"] = module["snapshot_sha256"]
    references = [
        item
        for field, value in agent.items()
        if field.endswith("_refs") and isinstance(value, list)
        for item in value
    ]
    agent["capability_bundle_sha256"] = hashlib.sha256(
        canonical_json_bytes(sorted(references, key=lambda item: item["snapshot_id"]))
    ).hexdigest()
    agent["snapshot_sha256"] = _snapshot_hash(agent)
    agent_path.write_text(json.dumps(agent), encoding="utf-8")

    with pytest.raises(CapabilityBundleError, match="duplicate module_id"):
        load_mini_agent_capability_bundle(root)


def _snapshot_hash(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("snapshot_sha256", None)
    return hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()
