from __future__ import annotations

from pathlib import Path

import pytest

from capability_snapshot_kit import CapabilityClaimV3
from capability_snapshot_kit.compiler import (
    CapabilityCompilationErrorV3,
    compile_capability_bundle_v3,
    compile_capability_snapshot_v3,
)
from capability_snapshot_kit.spec_loader import load_capability_spec_pack_v3
from tests.support.capability_adapter import FakeCapabilityAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPECS = load_capability_spec_pack_v3(PROJECT_ROOT / "capability_specs")


class AdapterWithModules(FakeCapabilityAdapter):
    def __init__(self, modules):
        self._modules = tuple(modules)

    def module_facts(self):
        return self._modules


def test_fake_adapter_compiles_a_valid_non_minimal_agent_bundle() -> None:
    bundle = compile_capability_bundle_v3(SPECS, FakeCapabilityAdapter())
    snapshots = {
        bundle.agent.snapshot_id: bundle.agent,
        **{snapshot.snapshot_id: snapshot for snapshot in bundle.child_snapshots},
    }

    assert bundle.agent.snapshot_id == "agent.example_agent"
    assert len(bundle.scopes) == 5
    assert len(bundle.chains) == 3
    assert len(bundle.evidence) == 5
    assert len(bundle.boundaries) == 7
    assert all(
        reference.snapshot_id in snapshots
        for reference in bundle.agent.module_refs
        + bundle.agent.intent_refs
        + bundle.agent.tool_refs
        + bundle.agent.scope_refs
        + bundle.agent.chain_refs
        + bundle.agent.evidence_refs
        + bundle.agent.boundary_refs
    )
    serialized = "\n".join(
        snapshot.model_dump_json()
        for snapshot in [bundle.agent, *bundle.child_snapshots]
    )
    assert "mini_agent" not in serialized
    assert compile_capability_snapshot_v3(
        "scope.understanding", SPECS, FakeCapabilityAdapter()
    ) == bundle.scopes["scope.understanding"]


def test_compilation_is_deterministic() -> None:
    first = compile_capability_bundle_v3(SPECS, FakeCapabilityAdapter())
    second = compile_capability_bundle_v3(SPECS, FakeCapabilityAdapter())

    assert first == second
    assert first.agent.capability_bundle_sha256 == (
        second.agent.capability_bundle_sha256
    )


@pytest.mark.parametrize("mode", ["missing", "ambiguous"])
def test_missing_or_ambiguous_module_role_fails_with_role_name(mode: str) -> None:
    original = FakeCapabilityAdapter().module_facts()[0]
    if mode == "missing":
        modules = [
            original.model_copy(
                update={
                    "roles": tuple(
                        role for role in original.roles if role != "observability"
                    )
                }
            )
        ]
    else:
        modules = [
            original,
            original.model_copy(
                update={
                    "module_id": "second_observer",
                    "component_versions": {"second_observer": "v1"},
                    "roles": ("observability",),
                    "intent_ids": (),
                }
            ),
        ]

    with pytest.raises(CapabilityCompilationErrorV3, match="observability"):
        compile_capability_bundle_v3(SPECS, AdapterWithModules(modules))


def test_supported_claim_with_missing_evidence_is_rejected() -> None:
    original = FakeCapabilityAdapter().module_facts()[0]
    invalid = original.model_copy(
        update={
            "capabilities": (
                CapabilityClaimV3(
                    capability_key="module.unobservable_support",
                    support_status="supported",
                    evidence_ids=["evidence.missing"],
                    reason=None,
                ),
            )
        }
    )

    with pytest.raises(CapabilityCompilationErrorV3, match="evidence.missing"):
        compile_capability_bundle_v3(SPECS, AdapterWithModules([invalid]))


def test_missing_fact_is_not_synthesized_as_supported() -> None:
    bundle = compile_capability_bundle_v3(SPECS, FakeCapabilityAdapter())

    assert bundle.evidence["evidence.context_state"].availability.support_status == (
        "unknown"
    )
    context_claim = next(
        claim
        for claim in bundle.agent.capabilities
        if claim.capability_key == "agent.context"
    )
    assert context_claim.support_status == "unknown"
