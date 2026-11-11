from dataclasses import replace

import pytest
from minimal_agent import MinimalAgent
from minimal_agent.capabilities.v3.bundle import build_capability_bundle_v3
from minimal_agent.contracts.agent import IntentResult
from minimal_agent.contracts.intents import (
    IntentRegistry,
    TrimStringNormalizer,
    UnsupportedIntentPolicy,
    build_default_intent_registry,
)
from minimal_agent.runtime.tool_registry import ToolRegistry
from tests.support.model_client import DeterministicModelClient


def changed_registry(**changes):
    registry = IntentRegistry()
    for d in build_default_intent_registry().definitions:
        registry.register(
            replace(d, **changes) if d.intent == "query_information" else d
        )
    return registry


def bundle(registry):
    return build_capability_bundle_v3(registry, ToolRegistry())


@pytest.mark.parametrize(
    "changes",
    [
        {"semantic_constraints": ()},
        {"normalizers": (TrimStringNormalizer(("resource_type",)),)},
        {
            "completion_policy": UnsupportedIntentPolicy(),
            "execution_mode": "unsupported",
        },
    ],
)
def test_semantic_configuration_changes_snapshot_identity(changes):
    original = bundle(build_default_intent_registry())
    modified = bundle(changed_registry(**changes))
    assert (
        original.agent.capability_bundle_sha256
        != modified.agent.capability_bundle_sha256
    )
    assert (
        original.intents["intent.query_information"].snapshot_sha256
        != modified.intents["intent.query_information"].snapshot_sha256
    )


def test_custom_unidentified_rule_is_rejected():
    class UnknownNormalizer:
        def normalize(self, *args):
            raise AssertionError("must not execute a normalizer during export")

    with pytest.raises(ValueError, match="snapshot_semantics"):
        bundle(changed_registry(normalizers=(UnknownNormalizer(),)))


def test_runtime_and_snapshot_share_custom_registry():
    registry = changed_registry(
        execution_mode="unsupported", completion_policy=UnsupportedIntentPolicy()
    )
    client = DeterministicModelClient(
        [
            IntentResult(
                intent="query_information",
                status="READY",
                next_action="CALL_TOOL",
                parameters={"resource_type": "fixture", "environment": "test"},
                missing_parameters=[],
                reason="offline",
            ).model_dump()
        ]
    )
    agent = MinimalAgent(client, ToolRegistry(), intent_registry=registry)
    observed = agent.run_intent_only("query")
    expected = (
        bundle(registry).intents["intent.query_information"].decision_rules["complete"]
    )
    assert observed.status == expected["status"] == "REJECTED"


def test_constraint_order_is_part_of_semantic_identity():
    from minimal_agent.contracts.intents import AtLeastOneFieldGroup, RequiredFields

    constraints = (
        RequiredFields(("environment",)),
        AtLeastOneFieldGroup(("resource_type",), "resource_type"),
    )
    first = bundle(changed_registry(semantic_constraints=constraints))
    second = bundle(changed_registry(semantic_constraints=constraints[::-1]))
    assert first.agent.capability_bundle_sha256 != second.agent.capability_bundle_sha256


def test_custom_normalizer_configuration_uses_explicit_protocol():
    class ConfiguredNormalizer:
        def __init__(self, field):
            self.field = field

        def snapshot_semantics(self):
            return {
                "component_id": "external_agent.normalizer",
                "version": "2",
                "parameters": {"field": self.field},
            }

        def normalize(self, *args):
            raise AssertionError("snapshot must not execute normalization")

    one = bundle(changed_registry(normalizers=(ConfiguredNormalizer("environment"),)))
    two = bundle(changed_registry(normalizers=(ConfiguredNormalizer("resource_type"),)))
    assert one.agent.capability_bundle_sha256 != two.agent.capability_bundle_sha256
