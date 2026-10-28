from copy import deepcopy

import pytest
from pydantic import ValidationError

from minimal_agent.capabilities.v3.models import (
    AgentSnapshotV3,
    BoundarySnapshotV3,
    CapabilityClaimV3,
    ChainSnapshotV3,
    EvidenceSnapshotV3,
    IntentSnapshotV3,
    ModuleSnapshotV3,
    ScopeSnapshotV3,
    SnapshotReferenceV3,
    SnapshotTypeV3,
    SupportStatusV3,
    ToolSnapshotV3,
    snapshot_schema_v3,
)

SHA = "0" * 64


def _base(snapshot_type: str, snapshot_id: str) -> dict[str, object]:
    return {
        "snapshot_id": snapshot_id,
        "snapshot_type": snapshot_type,
        "snapshot_format_version": "3.0",
        "contract_version": "test-v3",
        "source_hashes": {"test": SHA},
        "snapshot_sha256": SHA,
    }


def _claim() -> dict[str, object]:
    return {
        "capability_key": "intent.formal_validation",
        "support_status": "supported",
        "evidence_ids": ["evidence.intent_result"],
        "reason": None,
    }


def _artifacts() -> list[tuple[type, dict[str, object]]]:
    return [
        (
            AgentSnapshotV3,
            {
                **_base("agent", "agent.mini_agent"),
                "agent_id": "mini_agent",
                "agent_version": "test",
                "entrypoints": ["run"],
                "input_schema": {},
                "output_schema": {},
                "capabilities": [_claim()],
                "module_refs": [],
                "intent_refs": [],
                "tool_refs": [],
                "scope_refs": [],
                "chain_refs": [],
                "evidence_refs": [],
                "boundary_refs": [],
                "runtime_versions": {},
                "capability_bundle_sha256": SHA,
            },
        ),
        (
            ModuleSnapshotV3,
            {
                **_base("module", "module.intent_router"),
                "module_id": "intent_router",
                "responsibility": "Validate intent output.",
                "component_versions": {"router": "v1"},
                "input_schema": {},
                "output_schema": {},
                "capabilities": [_claim()],
                "module_refs": [],
                "intent_refs": [],
                "tool_refs": [],
                "execution_boundary_ids": ["boundary.intent_only"],
                "trace_event_types": ["intent_decided"],
            },
        ),
        (
            IntentSnapshotV3,
            {
                **_base("intent", "intent.query_user"),
                "capability_id": "query_user",
                "module_id": "module.intent_router",
                "parameters_schema": {},
                "parameter_semantics": {},
                "decision_rules": {},
                "semantic_rules": {},
                "required_tool_name": "query_user_info",
                "capabilities": [_claim()],
                "tool_refs": [],
            },
        ),
        (
            ToolSnapshotV3,
            {
                **_base("tool", "tool.query_user_info"),
                "tool_name": "query_user_info",
                "tool_version": "v1",
                "description": "Query users.",
                "implementation_profile": "evaluation_adapter",
                "registered": True,
                "function_schema": {},
                "parameter_semantics": {},
                "combination_rules": {},
                "batch_behavior": {},
                "preconditions": [],
                "result_protocols": {},
                "permission_requirements": [],
                "requires_confirmation": False,
                "risk_level": "low",
                "idempotency_rules": {},
                "side_effects": [],
                "retry_policy": {},
                "simulation_protocol": None,
                "simulation_capabilities": [],
                "observation_interfaces": [],
                "capabilities": [_claim()],
            },
        ),
        (
            ScopeSnapshotV3,
            {
                **_base("scope", "scope.understanding"),
                "scope_id": "understanding",
                "description": "Intent understanding boundary.",
                "inputs": ["user_input"],
                "outputs": ["intent_result"],
                "entrypoint": "run",
                "stop_boundary": "intent_decided",
                "allowed_module_ids": ["module.intent_router"],
                "prohibited_module_ids": [],
                "module_refs": [],
                "evidence_refs": [],
                "boundary_refs": [],
                "requirements": [],
                "completion_condition": "intent result emitted",
                "unresolved_behavior": "resolve unknown",
            },
        ),
        (
            ChainSnapshotV3,
            {
                **_base("chain", "chain.end_to_end"),
                "chain_id": "end_to_end",
                "description": "Generic full chain.",
                "nodes": [],
                "module_refs": [],
                "evidence_refs": [],
                "boundary_refs": [],
                "requirements": [],
                "branches": [],
                "completion_condition": "terminal result emitted",
            },
        ),
        (
            EvidenceSnapshotV3,
            {
                **_base("evidence", "evidence.intent_result"),
                "evidence_id": "intent_result",
                "description": "Validated intent result.",
                "producer_module_ids": ["module.intent_router"],
                "consumer_roles": ["evaluator"],
                "production_timing": "after intent validation",
                "payload_schema": {},
                "observation_interface": "agent_result.intent_result",
                "event_types": ["intent_decided"],
                "required": True,
                "applicable_result_paths": ["success"],
                "availability": _claim(),
            },
        ),
        (
            BoundarySnapshotV3,
            {
                **_base("boundary", "boundary.intent_only"),
                "boundary_id": "intent_only",
                "description": "Stop after intent decision.",
                "entry_node": "run",
                "stop_node": "intent_decided",
                "allowed_module_ids": ["module.intent_router"],
                "prohibited_module_ids": [],
                "terminal_condition": "intent result exists",
                "evidence_ids": ["evidence.intent_result"],
                "no_overrun_rule": "no tool call",
            },
        ),
    ]


@pytest.mark.parametrize(("model", "payload"), _artifacts())
def test_all_artifact_models_reject_unknown_fields(
    model: type,
    payload: dict[str, object],
) -> None:
    invalid = deepcopy(payload)
    invalid["unexpected"] = True

    with pytest.raises(ValidationError):
        model.model_validate(invalid)


@pytest.mark.parametrize(("model", "payload"), _artifacts())
def test_typed_snapshot_ids_must_match_the_artifact_type(
    model: type,
    payload: dict[str, object],
) -> None:
    invalid = deepcopy(payload)
    invalid["snapshot_id"] = "wrong.value"

    with pytest.raises(ValidationError):
        model.model_validate(invalid)


def test_reference_requires_v3_relative_posix_json_path() -> None:
    valid = {
        "snapshot_id": "scope.understanding",
        "snapshot_type": "scope",
        "snapshot_format_version": "3.0",
        "contract_version": "test-v3",
        "snapshot_sha256": SHA,
        "path": "scopes/understanding.json",
    }

    assert SnapshotReferenceV3.model_validate(valid).path == valid["path"]
    for path in ("/scopes/a.json", "scopes\\a.json", "scopes/../a.json", "a.txt"):
        with pytest.raises(ValidationError):
            SnapshotReferenceV3.model_validate({**valid, "path": path})
    with pytest.raises(ValidationError):
        SnapshotReferenceV3.model_validate({**valid, "snapshot_format_version": "0.0"})


@pytest.mark.parametrize(
    ("model", "payload"),
    [item for item in _artifacts() if item[0] in (ScopeSnapshotV3, ChainSnapshotV3)],
)
def test_scope_and_chain_do_not_declare_a_resolved_support_status(
    model: type,
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({**payload, "support_status": "supported"})


def test_capability_claim_enforces_reason_and_supported_evidence() -> None:
    with pytest.raises(ValidationError):
        CapabilityClaimV3(
            capability_key="context.inheritance",
            support_status="unknown",
            evidence_ids=[],
            reason=None,
        )
    with pytest.raises(ValidationError):
        CapabilityClaimV3(
            capability_key="intent.formal_validation",
            support_status="supported",
            evidence_ids=[],
            reason=None,
        )

    claim = CapabilityClaimV3(
        capability_key="context.inheritance",
        support_status=SupportStatusV3.UNSUPPORTED,
        evidence_ids=[],
        reason="No conversation state is accepted by the runtime.",
    )
    assert claim.reason


@pytest.mark.parametrize("snapshot_type", list(SnapshotTypeV3))
def test_every_v3_snapshot_type_emits_a_strict_json_schema(
    snapshot_type: SnapshotTypeV3,
) -> None:
    schema = snapshot_schema_v3(snapshot_type)

    assert schema["additionalProperties"] is False
