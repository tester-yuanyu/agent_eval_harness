import json
from dataclasses import replace
from pathlib import Path

import pytest

from capability_snapshot_kit import calculate_snapshot_sha256
from minimal_agent.capabilities.v3.bundle import export_capability_bundle_v3
from minimal_agent.capabilities.v3.validation import (
    CapabilityBundleValidationErrorV3,
    load_capability_bundle_v3,
    validate_capability_bundle_v3,
)
from minimal_agent.contracts.intents import build_default_intent_registry
from minimal_agent.runtime.tool_registry import ToolDefinition, ToolRegistry
from tests.support.tools import ECHO_CONTRACT, echo


def _registry(name: str = "query_information") -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(contract=replace(ECHO_CONTRACT, name=name), handler=echo)
    )
    return registry


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _rehash(payload: dict) -> None:
    payload["snapshot_sha256"] = calculate_snapshot_sha256(payload)


def _export(root: Path, registry: ToolRegistry | None = None) -> None:
    export_capability_bundle_v3(
        root,
        build_default_intent_registry(),
        registry or ToolRegistry(),
    )


def _files(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_valid_default_and_configured_bundles_load_as_typed_graphs(
    tmp_path: Path,
) -> None:
    default_root = tmp_path / "default"
    configured_root = tmp_path / "configured"
    _export(default_root)
    _export(configured_root, _registry())

    default_result = validate_capability_bundle_v3(default_root)
    configured = load_capability_bundle_v3(configured_root)

    assert default_result.snapshot_counts == {
        "agent": 1,
        "module": 7,
        "intent": 7,
        "tool": 0,
        "scope": 5,
        "chain": 3,
        "evidence": 5,
        "boundary": 7,
    }
    assert set(configured.tools) == {"tool.query_information"}


def test_validation_rejects_unknown_fields_and_schema_drift(tmp_path: Path) -> None:
    unknown_root = tmp_path / "unknown"
    _export(unknown_root)
    module_path = unknown_root / "modules" / "intent_router.json"
    module = _read(module_path)
    module["invented"] = True
    _write(module_path, module)

    with pytest.raises(CapabilityBundleValidationErrorV3, match="extra_forbidden"):
        validate_capability_bundle_v3(unknown_root)

    schema_root = tmp_path / "schema"
    _export(schema_root)
    schema_path = schema_root / "schemas" / "scope.schema.json"
    schema = _read(schema_path)
    schema["title"] = "Drifted"
    _write(schema_path, schema)
    with pytest.raises(CapabilityBundleValidationErrorV3, match="Schema artifact"):
        validate_capability_bundle_v3(schema_root)


def test_validation_rejects_snapshot_and_bundle_hash_mismatch(tmp_path: Path) -> None:
    snapshot_root = tmp_path / "snapshot"
    _export(snapshot_root)
    path = snapshot_root / "scopes" / "context.json"
    payload = _read(path)
    payload["description"] = "tampered"
    _write(path, payload)
    with pytest.raises(CapabilityBundleValidationErrorV3, match="snapshot_sha256"):
        validate_capability_bundle_v3(snapshot_root)

    bundle_root = tmp_path / "bundle"
    _export(bundle_root)
    agent_path = bundle_root / "agent.json"
    agent = _read(agent_path)
    agent["capability_bundle_sha256"] = "f" * 64
    _rehash(agent)
    _write(agent_path, agent)
    with pytest.raises(CapabilityBundleValidationErrorV3, match="Bundle hash"):
        validate_capability_bundle_v3(bundle_root)


def test_validation_rejects_dangling_and_out_of_scope_artifacts(
    tmp_path: Path,
) -> None:
    dangling = tmp_path / "dangling"
    _export(dangling)
    (dangling / "evidence" / "tool_trace.json").unlink()
    with pytest.raises(CapabilityBundleValidationErrorV3, match="missing referenced"):
        validate_capability_bundle_v3(dangling)

    outside = tmp_path / "outside"
    _export(outside)
    source = _read(outside / "modules" / "model_gateway.json")
    source["snapshot_id"] = "module.unscoped"
    source["module_id"] = "unscoped"
    _rehash(source)
    _write(outside / "modules" / "unscoped.json", source)
    with pytest.raises(CapabilityBundleValidationErrorV3, match="outside Agent scope"):
        validate_capability_bundle_v3(outside)


def test_validation_reports_the_complete_module_cycle_path(tmp_path: Path) -> None:
    root = tmp_path / "cycle"
    _export(root)
    agent = _read(root / "agent.json")
    refs = {ref["snapshot_id"]: ref for ref in agent["module_refs"]}
    first_path = root / "modules" / "agent_orchestrator.json"
    second_path = root / "modules" / "model_gateway.json"
    first = _read(first_path)
    second = _read(second_path)
    first["module_refs"] = [refs["module.model_gateway"]]
    second["module_refs"] = [refs["module.agent_orchestrator"]]
    _rehash(first)
    _rehash(second)
    _write(first_path, first)
    _write(second_path, second)

    with pytest.raises(
        CapabilityBundleValidationErrorV3,
        match=(
            "module.agent_orchestrator -> module.model_gateway -> "
            "module.agent_orchestrator"
        ),
    ):
        validate_capability_bundle_v3(root)


def test_validation_rejects_wrong_protocol_version_and_tool_reverse_references(
    tmp_path: Path,
) -> None:
    mixed = tmp_path / "mixed"
    _export(mixed)
    intent_path = mixed / "intents" / "query_user.json"
    intent = _read(intent_path)
    intent["tool_refs"] = [
        {
            "snapshot_id": "tool.query_user_info",
            "snapshot_type": "tool",
            "snapshot_format_version": "0.0",
            "contract_version": "wrong-tool-version",
            "snapshot_sha256": "0" * 64,
            "path": "tools/query_user_info.json",
        }
    ]
    _rehash(intent)
    _write(intent_path, intent)
    with pytest.raises(CapabilityBundleValidationErrorV3, match="3.0"):
        validate_capability_bundle_v3(mixed)

    reverse = tmp_path / "reverse"
    _export(reverse, _registry())
    tool_path = reverse / "tools" / "query_information.json"
    tool = _read(tool_path)
    tool["intent_refs"] = []
    _rehash(tool)
    _write(tool_path, tool)
    with pytest.raises(CapabilityBundleValidationErrorV3, match="extra_forbidden"):
        validate_capability_bundle_v3(reverse)


def test_validation_rejects_false_agent_aggregation_and_unknown_evidence(
    tmp_path: Path,
) -> None:
    summary_root = tmp_path / "summary"
    _export(summary_root)
    agent_path = summary_root / "agent.json"
    agent = _read(agent_path)
    agent["capabilities"][0] = {
        "capability_key": "agent.understanding",
        "support_status": "unknown",
        "evidence_ids": [],
        "reason": "tampered",
    }
    _rehash(agent)
    _write(agent_path, agent)
    with pytest.raises(CapabilityBundleValidationErrorV3, match="summary mismatch"):
        validate_capability_bundle_v3(summary_root)

    evidence_root = tmp_path / "evidence"
    _export(evidence_root)
    module_path = evidence_root / "modules" / "intent_router.json"
    module = _read(module_path)
    module["capabilities"][0]["evidence_ids"] = ["evidence.missing"]
    _rehash(module)
    _write(module_path, module)
    with pytest.raises(CapabilityBundleValidationErrorV3, match="unknown Evidence"):
        validate_capability_bundle_v3(evidence_root)


def test_atomic_export_removes_all_stale_artifacts_and_is_repeatable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "capabilities"
    _export(root, _registry())
    assert (root / "tools" / "query_information.json").is_file()
    (root / "scopes" / "stale.json").write_text("{}", encoding="utf-8")
    (root / "unrelated.json").write_text("{}", encoding="utf-8")

    _export(root)
    first = _files(root)
    assert list((root / "tools").iterdir()) == [root / "tools" / ".gitkeep"]
    assert not (root / "scopes" / "stale.json").exists()
    assert not (root / "unrelated.json").exists()

    _export(root)
    assert _files(root) == first
