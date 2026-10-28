from __future__ import annotations

import inspect
from dataclasses import replace

from dataset_builder.intent_compiler import compile_intent_candidates
from dataset_builder.intent_validation import (
    validate_module_intent_contract,
    validate_parameters,
)
from dataset_builder.suite_definition import load_suite
from dataset_builder.validation import validate_draft_file, write_jsonl


def _query_suite_and_cases():
    suite = load_suite("mini_agent_query_user_intent_v1")
    batch = suite.batch_type.model_validate_json(
        suite.seed_catalog_path.read_text()
    )
    return suite, compile_intent_candidates(batch.candidates, suite)


def _parameter_schema():
    suite = load_suite("mini_agent_query_user_intent_v1")
    return suite.capability_ir.parameters_schema


def test_parameter_validation_comes_from_capability_json_schema():
    schema = _parameter_schema()

    assert validate_parameters({"user_id": 1}, schema, omit_null=True) == []
    assert validate_parameters(
        {"email": "a@b"}, schema, omit_null=True
    ) == []
    assert validate_parameters(
        {"phone": "15000000200"}, schema, omit_null=True
    ) == []
    assert validate_parameters(
        {"phone": "1500000020"}, schema, omit_null=True
    )


def test_integer_schema_rejects_boolean_and_non_positive_values():
    schema = _parameter_schema()

    assert validate_parameters({"user_id": True}, schema, omit_null=True)
    assert validate_parameters({"user_id": 0}, schema, omit_null=True)
    assert validate_parameters({"room_id": -1}, schema, omit_null=True)


def test_unknown_and_explicit_null_parameters_are_rejected():
    schema = _parameter_schema()

    unknown = validate_parameters({"unknown": 1}, schema, omit_null=True)
    explicit_null = validate_parameters(
        {"user_id": None}, schema, omit_null=True
    )

    assert any("unknown" in issue for issue in unknown)
    assert any("omitted instead of null" in issue for issue in explicit_null)


def test_valid_boundary_values_are_accepted():
    schema = _parameter_schema()

    assert validate_parameters({"user_id": 1}, schema, omit_null=True) == []
    assert validate_parameters({"room_id": 1}, schema, omit_null=True) == []
    assert validate_parameters({"email": "a@b"}, schema, omit_null=True) == []
    assert validate_parameters(
        {"phone": "00000000000"}, schema, omit_null=True
    ) == []


def test_status_action_mapping_comes_from_module_snapshot():
    suite, cases = _query_suite_and_cases()
    changed = [case.model_copy(deep=True) for case in cases]
    changed[0].oracle.expected_module_output["next_action"] = "ASK_USER"

    issues = validate_module_intent_contract(changed, suite)

    assert any("status/next_action mismatch" in issue for issue in issues)


def test_missing_parameter_vocabulary_comes_from_capability_snapshot():
    suite, cases = _query_suite_and_cases()
    changed = [case.model_copy(deep=True) for case in cases]
    clarification = next(
        case
        for case in changed
        if case.oracle.expected_module_output["status"]
        == "NEED_CLARIFICATION"
    )
    clarification.oracle.expected_module_output["missing_parameters"] = [
        "unknown_missing_name"
    ]

    issues = validate_module_intent_contract(changed, suite)

    assert any("unknown missing parameters" in issue for issue in issues)


def test_slot_scenario_and_rule_refs_are_checked_without_tool_specific_code():
    suite, cases = _query_suite_and_cases()
    changed = [case.model_copy(deep=True) for case in cases]
    changed[0].scenario_type = "valid_boundary"
    changed[1].labels = [
        label
        for label in changed[1].labels
        if not label.startswith("rule:")
    ]

    issues = validate_module_intent_contract(changed, suite)
    source = inspect.getsource(validate_module_intent_contract)

    assert any("scenario_type does not match" in issue for issue in issues)
    assert any("rule_refs do not match" in issue for issue in issues)
    for business_term in ("query_user", "user_id", "room_id", "phone"):
        assert business_term not in source


def test_migrated_validation_policy_selects_enabled_gates(tmp_path):
    suite, cases = _query_suite_and_cases()
    policy_set = suite.policy_set
    assert policy_set is not None
    validation = policy_set.validation.model_copy(
        update={
            "config": policy_set.validation.config.model_copy(
                update={"enabled_gates": ["evaluator"]}
            )
        }
    )
    changed_suite = replace(
        suite,
        policy_set=policy_set.model_copy(update={"validation": validation}),
    )
    draft = tmp_path / "draft.jsonl"
    write_jsonl(cases, draft)

    report = validate_draft_file(changed_suite, draft)

    assert [gate.name for gate in report.gates] == ["evaluator"]
