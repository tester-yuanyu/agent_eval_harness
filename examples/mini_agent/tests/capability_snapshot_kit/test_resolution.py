from __future__ import annotations

from pathlib import Path

from capability_snapshot_kit import CapabilityClaimV3, CapabilityRequirementV3
from capability_snapshot_kit.compiler import compile_capability_bundle_v3
from capability_snapshot_kit.facts import EvidenceFactV3, ToolFactV3
from capability_snapshot_kit.resolution import (
    CapabilitySelectionV3,
    resolve_capability_graph_v3,
)
from capability_snapshot_kit.spec_loader import load_capability_spec_pack_v3
from tests.support.capability_adapter import FakeCapabilityAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPECS = load_capability_spec_pack_v3(PROJECT_ROOT / "capability_specs")


class ToolCapabilityAdapter(FakeCapabilityAdapter):
    def module_facts(self):
        module = super().module_facts()[0]
        return (
            module.model_copy(
                update={
                    "capabilities": (
                        *module.capabilities,
                        CapabilityClaimV3(
                            capability_key="execution.bounded_tool_loop",
                            support_status="supported",
                            evidence_ids=["evidence.tool_trace"],
                            reason=None,
                        ),
                    ),
                    "tool_ids": ("tool.query_user_info",),
                }
            ),
        )

    def intent_facts(self):
        intent = super().intent_facts()[0]
        return (intent.model_copy(update={"required_tool_name": "query_user_info"}),)

    def tool_facts(self):
        return (
            ToolFactV3(
                tool_name="query_user_info",
                contract_version="query-user-tool-v1",
                tool_version="query-user-tool-v1",
                description="Query user information.",
                implementation_profile="evaluation_adapter",
                registered=True,
                function_schema={"type": "object"},
                parameter_semantics={},
                combination_rules={},
                batch_behavior={},
                preconditions=[],
                result_protocols={},
                permission_requirements=[],
                requires_confirmation=False,
                risk_level="low",
                idempotency_rules={},
                side_effects=[],
                retry_policy={},
                simulation_protocol={"name": "deterministic", "version": "v1"},
                simulation_capabilities=[],
                observation_interfaces=["evidence.tool_trace"],
                capabilities=(
                    CapabilityClaimV3(
                        capability_key="tool.registered_execution",
                        support_status="supported",
                        evidence_ids=["evidence.tool_trace"],
                        reason=None,
                    ),
                ),
            ),
        )

    def evidence_facts(self):
        return (
            *super().evidence_facts(),
            EvidenceFactV3(
                evidence_id="tool_trace",
                producer_module_roles=("tool_loop", "tool_registry"),
                production_timing="during tool invocation",
                payload_schema={"type": "object"},
                observation_interface="agent_result.tool_calls",
                event_types=("tool_started", "tool_succeeded"),
                applicable_result_paths=("success", "failure", "timeout"),
                availability=CapabilityClaimV3(
                    capability_key="evidence.tool_trace_available",
                    support_status="supported",
                    evidence_ids=["evidence.tool_trace"],
                    reason=None,
                ),
            ),
        )


def _selection(
    scope_or_chain_id: str,
    tool_id: str | None = None,
) -> CapabilitySelectionV3:
    return CapabilitySelectionV3(
        scope_or_chain_id=scope_or_chain_id,
        intent_id="intent.query_user",
        tool_id=tool_id,
    )


def test_explicit_unsupported_mandatory_claim_wins() -> None:
    adapter = FakeCapabilityAdapter()
    module = adapter.module_facts()[0]
    unsupported = module.model_copy(
        update={
            "capabilities": (
                *module.capabilities,
                CapabilityClaimV3(
                    capability_key="context.inheritance",
                    support_status="unsupported",
                    evidence_ids=[],
                    reason="No conversation state.",
                ),
            )
        }
    )

    class UnsupportedAdapter(FakeCapabilityAdapter):
        def module_facts(self):
            return (unsupported,)

    result = resolve_capability_graph_v3(
        compile_capability_bundle_v3(SPECS, UnsupportedAdapter()),
        _selection("scope.context"),
    )

    assert result.support_status == "unsupported"


def test_missing_claim_is_unknown_and_optional_failure_does_not_lower_status() -> None:
    bundle = compile_capability_bundle_v3(SPECS, FakeCapabilityAdapter())
    scope = bundle.scopes["scope.understanding"]
    optional = CapabilityRequirementV3(
        requirement_id="missing_optional_claim",
        capability_key="intent.undeclared_behavior",
        provider={"role": "selected_intent", "snapshot_id": None},
        mandatory=False,
        evidence_ids=[],
    )
    bundle.scopes[scope.snapshot_id] = scope.model_copy(
        update={"requirements": [*scope.requirements, optional]}
    )

    result = resolve_capability_graph_v3(
        bundle,
        _selection("scope.understanding"),
    )

    assert result.support_status == "supported"
    assert result.requirements[-1].support_status == "unknown"


def test_missing_and_mismatched_selected_tool_are_unsupported() -> None:
    no_tool = resolve_capability_graph_v3(
        compile_capability_bundle_v3(SPECS, ToolCapabilityAdapter()),
        _selection("scope.planning_execution"),
    )
    mismatch = resolve_capability_graph_v3(
        compile_capability_bundle_v3(SPECS, ToolCapabilityAdapter()),
        _selection("scope.planning_execution", "tool.unrelated"),
    )

    assert no_tool.support_status == "unknown"
    assert any("no Tool was selected" in item for item in no_tool.diagnostics)
    assert mismatch.support_status == "unsupported"
    assert any("required-tool mismatch" in item for item in mismatch.diagnostics)


def test_supported_requires_claims_and_available_evidence() -> None:
    bundle = compile_capability_bundle_v3(SPECS, ToolCapabilityAdapter())
    selection = _selection("scope.planning_execution", "tool.query_user_info")

    supported = resolve_capability_graph_v3(bundle, selection)
    assert supported.support_status == "supported"

    scope = bundle.scopes[selection.scope_or_chain_id]
    first = scope.requirements[0].model_copy(
        update={"evidence_ids": ["evidence.context_state"]}
    )
    bundle.scopes[scope.snapshot_id] = scope.model_copy(
        update={"requirements": [first, *scope.requirements[1:]]}
    )
    unavailable = resolve_capability_graph_v3(bundle, selection)

    assert unavailable.support_status == "unknown"
    assert any("unavailable Evidence" in item for item in unavailable.diagnostics)


def test_resolution_is_deterministic_and_does_not_mutate_sources() -> None:
    bundle = compile_capability_bundle_v3(SPECS, ToolCapabilityAdapter())
    selection = _selection("chain.end_to_end", "tool.query_user_info")
    before = bundle.chains[selection.scope_or_chain_id].model_dump(mode="json")

    first = resolve_capability_graph_v3(bundle, selection)
    second = resolve_capability_graph_v3(bundle, selection)

    assert first == second
    assert bundle.chains[selection.scope_or_chain_id].model_dump(mode="json") == before
