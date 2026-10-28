from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from dataset_builder.capability_ir import SupportStatus
from dataset_builder.suite_config import SuiteConfig
from dataset_builder.suite_definition import load_suite

ROOT = Path(__file__).resolve().parents[1]


def test_checked_in_query_suites_bind_bundle_hash_and_load_capability_ir():
    user = load_suite("mini_agent_query_user_intent_v1")
    gift = load_suite("mini_agent_query_gift_intent_v1")

    assert user.capability_bundle_path.name == "capabilities"
    assert user.config.capability_input.bundle_hash == (
        "99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8"
    )
    assert user.capability_ir.intent.snapshot_id == "intent.query_user"
    assert gift.capability_ir.intent.snapshot_id == "intent.query_gift"
    assert user.capability_ir.support_status is SupportStatus.SUPPORTED
    assert gift.capability_ir.support_status is SupportStatus.SUPPORTED
    assert user.config.metadata.dataset_version == "2.0"
    assert gift.config.metadata.dataset_version == "2.0"


def test_legacy_capability_fields_are_rejected():
    path = ROOT / "suites" / "mini_agent_query_user_intent_v1" / "suite.json"
    payload = json.loads(path.read_text())
    payload["capability_selection"] = {
        "agent_id": "agent.mini_agent",
        "module_ids": ["module.intent_router"],
    }
    with pytest.raises(ValidationError, match="capability_selection"):
        SuiteConfig.model_validate(payload)


def test_suite_capability_input_rejects_protocol_routing_fields():
    path = ROOT / "suites" / "mini_agent_query_user_intent_v1" / "suite.json"
    payload = json.loads(path.read_text())
    payload["capability_input"]["profile_id"] = "capability-snapshot-v3"

    with pytest.raises(ValidationError, match="profile_id"):
        SuiteConfig.model_validate(payload)


def test_invalid_selection_is_rejected():
    suite = load_suite("mini_agent_query_user_intent_v1")
    changed_input = suite.config.capability_input.model_copy(
        update={"scope_or_chain_id": "scope.missing"}
    )
    changed_config = suite.config.model_copy(
        update={"capability_input": changed_input}
    )
    suite = replace(suite, config=changed_config)
    with pytest.raises(ValueError, match="selected_artifact_missing"):
        _ = suite.capability_ir


def test_suite_bundle_hash_must_match_validated_bundle():
    suite = load_suite("mini_agent_query_user_intent_v1")
    changed_input = suite.config.capability_input.model_copy(
        update={"bundle_hash": "0" * 64}
    )
    changed_config = suite.config.model_copy(
        update={"capability_input": changed_input}
    )
    suite = replace(suite, config=changed_config)

    with pytest.raises(ValueError, match="Suite capability bundle hash mismatch"):
        _ = suite.validated_capability_bundle


def test_capability_ir_uses_single_unversioned_adapter_and_includes_agent():
    suite = load_suite("mini_agent_query_user_intent_v1")

    assert suite.capability_adapter_registration.key.protocol == "capability-snapshot"
    assert suite.capability_ir.adapter_protocol == "capability-snapshot"
    assert suite.capability_ir.source_protocol_version == "3.0"
    assert "agent" in {
        artifact.snapshot_type for artifact in suite.capability_ir.source_artifacts
    }


@pytest.mark.parametrize("path", ["/absolute", "../escape", "a/../escape"])
def test_capability_bundle_path_is_safe(path):
    source = ROOT / "suites" / "mini_agent_query_user_intent_v1" / "suite.json"
    payload = json.loads(source.read_text())
    payload["capability_input"]["bundle"]["path"] = path
    with pytest.raises(ValidationError):
        SuiteConfig.model_validate(payload)
