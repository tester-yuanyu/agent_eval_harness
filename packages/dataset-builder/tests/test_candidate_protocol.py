from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from dataset_builder.candidate_protocol import build_candidate_protocol
from dataset_builder.suite_definition import load_suite

ROOT = Path(__file__).resolve().parents[1]


def _protocol(suite_id: str):
    suite = load_suite(suite_id)
    return build_candidate_protocol(
        suite.config,
        suite.candidate_protocol_config,
    )


def _candidate(**changes):
    value = {
        "slot_id": "slot-1",
        "user_input": "查询 UserID 为 9075333 的用户信息。",
        "expected_intent": "query_user",
        "expected_status": "READY",
        "expected_next_action": "CALL_TOOL",
        "expected_parameters_json": '{"user_id":9075333}',
        "missing_parameters": [],
        "scenario_type": "normal",
        "difficulty": "easy",
        "coverage_tags": ["explicit_field"],
        "rule_refs": ["query_user.field_rules.user_id"],
    }
    value.update(changes)
    return value


def _schema_values(value: dict) -> list[str]:
    return value["enum"] if "enum" in value else [value["const"]]


def test_query_user_candidate_protocol_uses_suite_enums():
    suite = load_suite("mini_agent_query_user_intent_v1")
    protocol = build_candidate_protocol(
        suite.config,
        suite.candidate_protocol_config,
    )
    schema = protocol.candidate_type.model_json_schema()["properties"]

    assert _schema_values(schema["expected_intent"]) == ["query_user"]
    assert _schema_values(schema["expected_status"]) == [
        "READY",
        "NEED_CLARIFICATION",
    ]
    assert _schema_values(schema["expected_next_action"]) == [
        "CALL_TOOL",
        "ASK_USER",
    ]
    assert _schema_values(schema["scenario_type"]) == (
        suite.candidate_protocol_config.allowed_scenario_types
    )


def test_generic_intent_candidate_protocol_uses_different_suite_enums():
    protocol = _protocol("mini_agent_intent_v1")
    value = _candidate(
        expected_intent="query_gift",
        scenario_type="complete_query",
        expected_parameters_json='{"gift_id":7302}',
    )
    del value["rule_refs"]
    candidate = protocol.candidate_type.model_validate(value)

    assert candidate.expected_intent == "query_gift"
    assert candidate.scenario_type == "complete_query"


def test_dynamic_candidate_rejects_extra_fields_and_invalid_enum_values():
    protocol = _protocol("mini_agent_query_user_intent_v1")

    with pytest.raises(ValidationError):
        protocol.candidate_type.model_validate(_candidate(extra="forbidden"))
    with pytest.raises(ValidationError):
        protocol.candidate_type.model_validate(
            _candidate(expected_intent="query_gift")
        )
    with pytest.raises(ValidationError):
        protocol.candidate_type.model_validate(
            _candidate(expected_status="NEED_CONFIRMATION")
        )
    with pytest.raises(ValidationError):
        protocol.candidate_type.model_validate(
            _candidate(scenario_type="complete_query")
        )


def test_rule_refs_requirement_is_controlled_by_suite_config():
    query_protocol = _protocol("mini_agent_query_user_intent_v1")
    generic_protocol = _protocol("mini_agent_intent_v1")
    query_value = _candidate()
    del query_value["rule_refs"]
    generic_value = _candidate(scenario_type="complete_query")
    del generic_value["rule_refs"]

    with pytest.raises(ValidationError):
        query_protocol.candidate_type.model_validate(query_value)
    candidate = generic_protocol.candidate_type.model_validate(generic_value)
    assert not hasattr(candidate, "rule_refs")
