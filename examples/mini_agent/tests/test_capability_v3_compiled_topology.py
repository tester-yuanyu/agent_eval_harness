from minimal_agent.capabilities.v3.bundle import build_capability_bundle_v3
from minimal_agent.contracts.intents import build_default_intent_registry
from minimal_agent.runtime.tool_registry import ToolRegistry

EVIDENCE_IDS = {
    "evidence.intent_result",
    "evidence.context_state",
    "evidence.tool_trace",
    "evidence.safety_recovery_event",
    "evidence.final_response",
}
BOUNDARY_IDS = {
    "boundary.understanding",
    "boundary.context",
    "boundary.planning_execution",
    "boundary.safety_recovery",
    "boundary.result",
    "boundary.critical_chain",
    "boundary.end_to_end",
}
SCOPE_IDS = {
    "scope.understanding",
    "scope.context",
    "scope.planning_execution",
    "scope.safety_recovery",
    "scope.result",
}
CHAIN_IDS = {
    "chain.understanding_to_planning",
    "chain.planning_to_result",
    "chain.end_to_end",
}
EMITTED_EVENTS = {
    "run_started",
    "intent_requested",
    "intent_candidate_received",
    "intent_definition_resolved",
    "intent_parameter_normalized",
    "intent_parameter_validation_failed",
    "intent_semantic_constraint_failed",
    "intent_contract_validated",
    "intent_decided",
    "clarification_returned",
    "confirmation_required",
    "request_rejected",
    "model_failed",
    "final_response_generated",
    "max_steps_exceeded",
    "tool_requested",
    "tool_started",
    "tool_succeeded",
    "tool_failed",
    "tool_timeout",
    "run_finished",
}


def _catalogs():
    bundle = build_capability_bundle_v3(
        build_default_intent_registry(),
        ToolRegistry(),
    )
    return (
        bundle.modules,
        bundle.evidence,
        bundle.boundaries,
        bundle.scopes,
        bundle.chains,
    )


def test_compiled_topology_has_exact_reusable_artifact_ids() -> None:
    _, evidence, boundaries, scopes, chains = _catalogs()

    assert set(evidence) == EVIDENCE_IDS
    assert set(boundaries) == BOUNDARY_IDS
    assert set(scopes) == SCOPE_IDS
    assert set(chains) == CHAIN_IDS
    assert all(
        "support_status" not in type(scope).model_fields for scope in scopes.values()
    )
    assert all(
        "support_status" not in type(chain).model_fields for chain in chains.values()
    )


def test_scopes_declare_structural_range_without_scoring_rules() -> None:
    _, _, _, scopes, _ = _catalogs()

    for scope in scopes.values():
        assert scope.entrypoint
        assert scope.stop_boundary
        assert scope.allowed_module_ids
        assert scope.prohibited_module_ids
        assert scope.requirements
        assert scope.evidence_refs
        assert scope.boundary_refs
        assert scope.completion_condition
        serialized = scope.model_dump_json().lower()
        assert "coverage_count" not in serialized
        assert "expected_answer" not in serialized
        assert "judge" not in serialized


def test_context_scope_requires_all_state_behaviors_without_resolving_them() -> None:
    _, _, _, scopes, _ = _catalogs()
    context = scopes["scope.context"]

    assert {requirement.capability_key for requirement in context.requirements} == {
        "context.inheritance",
        "context.override",
        "context.cancellation",
        "context.session_isolation",
        "context.residual_state_handling",
        "context.cleanup",
    }
    assert "support_status" not in context.model_dump()


def test_chains_are_ordered_role_based_and_include_terminal_branches() -> None:
    _, _, _, _, chains = _catalogs()

    for chain in chains.values():
        positions = {node.node_id: index for index, node in enumerate(chain.nodes)}
        assert all(
            positions[dependency] < positions[node.node_id]
            for node in chain.nodes
            for dependency in node.depends_on
        )
        assert {branch["branch_type"] for branch in chain.branches} == {
            "normal",
            "error",
            "early_stop",
        }
        assert chain.completion_condition

    end_to_end = chains["chain.end_to_end"]
    roles = {node.provider.role for node in end_to_end.nodes}
    roles.update(requirement.provider.role for requirement in end_to_end.requirements)
    assert {"selected_intent", "selected_tool"}.issubset(roles)
    assert "tool.query_user_info" not in end_to_end.model_dump_json()


def test_all_topology_references_resolve_inside_the_catalogs() -> None:
    modules, evidence, boundaries, scopes, chains = _catalogs()

    for artifact in [*scopes.values(), *chains.values()]:
        assert {ref.snapshot_id for ref in artifact.module_refs} <= set(modules)
        assert {ref.snapshot_id for ref in artifact.evidence_refs} <= set(evidence)
        assert {ref.snapshot_id for ref in artifact.boundary_refs} <= set(boundaries)


def test_evidence_uses_only_emitted_events_and_marks_context_unavailable() -> None:
    _, evidence, _, _, _ = _catalogs()

    assert all(set(item.event_types) <= EMITTED_EVENTS for item in evidence.values())
    context = evidence["evidence.context_state"]
    assert context.event_types == []
    assert context.availability.support_status in {"unsupported", "unknown"}
    assert context.availability.reason
