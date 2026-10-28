from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from dataclasses import replace

import pytest
from pydantic import ValidationError

from dataset_builder.candidate_parser import parse_candidates
from dataset_builder.coverage import coverage_gate
from dataset_builder.generation_client import ScriptedGenerationClient
from dataset_builder.intent_compiler import compile_intent_candidates
from dataset_builder.intent_validation import (
    validate_module_intent_contract,
    validate_parameters,
)
from dataset_builder.pipeline import (
    compile_candidates,
    generate_candidates,
    prepare_generation,
    validate_draft,
)
from dataset_builder.source_pack import sha256_file
from dataset_builder.suite_definition import ROOT, load_suite

SCENARIO_DISTRIBUTION = {
    "normal": 4,
    "valid_boundary": 4,
    "invalid_parameter": 6,
    "missing_parameter": 2,
    "ambiguous_expression": 3,
    "multi_condition": 3,
    "expression_variant": 12,
    "correction_conflict": 3,
    "unsupported_batch": 5,
}


def _assert_strict_objects(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            assert schema.get("additionalProperties") is False
            assert set(schema.get("required", [])) == set(schema.get("properties", {}))
        for value in schema.values():
            _assert_strict_objects(value)
    elif isinstance(schema, list):
        for value in schema:
            _assert_strict_objects(value)


def _candidate(**changes):
    value = {
        "slot_id": "explicit_user_id",
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


def _candidates_for_suite(suite):
    candidates = []
    for slot in suite.coverage_plan["slots"]:
        ready = slot["status"] == "READY"
        candidates.append(
            suite.candidate_type.model_validate(
                _candidate(
                    slot_id=slot["slot_id"],
                    user_input=f"查询测试用户 {slot['slot_id']}",
                    expected_status=slot["status"],
                    expected_next_action="CALL_TOOL" if ready else "ASK_USER",
                    expected_parameters_json=('{"user_id":1}' if ready else "{}"),
                    missing_parameters=[] if ready else ["user_id"],
                    scenario_type=slot["scenario_type"],
                    coverage_tags=[slot["category"]],
                    rule_refs=slot["rule_refs"],
                )
            )
        )
    return candidates


def test_query_user_suite_registration_and_coverage():
    suite = load_suite("mini_agent_query_user_intent_v1")

    assert suite.suite_id == "mini_agent_query_user_intent_v1"
    assert suite.dataset_version == "2.0"
    assert suite.test_scope == "module"
    assert suite.target == "intent_router"
    assert suite.prompt_version == "query-user-intent-v7"
    assert suite.source_file_names == (
        "generation.json",
        "coverage_plan.json",
    )
    assert suite.capability_bundle_path.name == "capabilities"
    assert suite.capability_ir.intent.snapshot_id == "intent.query_user"
    assert suite.capability_ir.selected_node.snapshot_id == "scope.understanding"
    assert suite.authoritative_source_files == ()
    assert suite.coverage_plan["capability_contract_version"] == (
        "query-user-intent-contract-v3"
    )
    assert suite.coverage_plan["module_contract_version"] == (
        "intent-router-module-v3"
    )
    assert all(
        slot["category"] in suite.coverage_plan["rule_catalog"]
        for slot in suite.coverage_plan["slots"]
    )
    assert all(slot["rule_refs"] for slot in suite.coverage_plan["slots"])
    slots = suite.coverage_plan["slots"]
    assert suite.coverage_plan["case_count"] == 42
    assert len(slots) == 42
    assert len({slot["slot_id"] for slot in slots}) == 42
    assert Counter(slot["status"] for slot in slots) == {
        "READY": 25,
        "NEED_CLARIFICATION": 17,
    }
    assert Counter(slot["scenario_type"] for slot in slots) == (SCENARIO_DISTRIBUTION)
    assert suite.coverage_plan["scenario_type_distribution"] == (SCENARIO_DISTRIBUTION)


def test_query_user_candidate_schema_is_strict_and_narrow():
    suite = load_suite("mini_agent_query_user_intent_v1")
    schema = suite.batch_type.model_json_schema()
    _assert_strict_objects(schema)

    with pytest.raises(ValidationError):
        suite.candidate_type.model_validate(_candidate(expected_intent="query_gift"))
    with pytest.raises(ValidationError):
        suite.candidate_type.model_validate(
            _candidate(expected_status="NEED_CONFIRMATION")
        )
    with pytest.raises(ValidationError):
        suite.candidate_type.model_validate(_candidate(extra="forbidden"))
    for scenario_type in SCENARIO_DISTRIBUTION:
        assert (
            suite.candidate_type.model_validate(
                _candidate(scenario_type=scenario_type)
            ).scenario_type
            == scenario_type
        )
    for scenario_type in ("", "explicit_field", "other"):
        with pytest.raises(ValidationError):
            suite.candidate_type.model_validate(_candidate(scenario_type=scenario_type))


def test_query_user_candidate_schema_snapshot_matches_model():
    suite = load_suite("mini_agent_query_user_intent_v1")
    snapshot = ROOT / "schemas" / "query_user_intent_candidate.schema.json"
    assert json.loads(snapshot.read_text()) == suite.batch_type.model_json_schema()


def test_query_user_compiler_injects_fixed_evaluator_fields():
    suite = load_suite("mini_agent_query_user_intent_v1")
    cases = compile_intent_candidates(_candidates_for_suite(suite), suite)

    assert [case.case_id for case in cases] == [
        f"MINI-QUSER-{index:03d}" for index in range(1, 43)
    ]
    assert all(case.task_id == "intent-query-user" for case in cases)
    assert all(case.test_scope == "module" for case in cases)
    assert all(case.target == "intent_router" for case in cases)
    assert all(case.execution.tool_profile == "shadow_read" for case in cases)
    assert all(case.execution.user_responses == [] for case in cases)
    assert all(case.cleanup is None for case in cases)
    for index, case in enumerate(cases):
        slot = suite.coverage_plan["slots"][index]
        assert case.scenario_type == slot["scenario_type"]
        assert slot["category"] in case.labels
        checks = case.oracle.evaluation.checks
        assert [check.weight for check in checks] == [10, 30, 20, 10, 20, 10]
        assert all(check.critical and check.config == {} for check in checks)
        expected = case.oracle.expected_module_output
        assert {
            "mini_agent",
            "module",
            "intent_understanding",
            "shadow",
            "query_user",
            "query_user_info",
            "bootstrap_generated",
            expected["status"],
        } <= set(case.labels)
        assert [label for label in case.labels if label.startswith("slot:")] == [
            f"slot:{suite.coverage_plan['slots'][index]['slot_id']}"
        ]
        assert {f"rule:{rule}" for rule in slot["rule_refs"]} <= set(case.labels)


def test_query_user_coverage_reports_and_enforces_scenario_distribution():
    suite = load_suite("mini_agent_query_user_intent_v1")
    cases = compile_intent_candidates(_candidates_for_suite(suite), suite)

    gate = coverage_gate(cases, suite)

    assert gate.passed
    assert gate.details["scenario_type_distribution"] == SCENARIO_DISTRIBUTION
    changed = [case.model_copy(deep=True) for case in cases]
    changed[0].scenario_type = "valid_boundary"
    failed = coverage_gate(changed, suite)
    assert not failed.passed
    assert any(
        "scenario type distribution mismatch" in issue for issue in failed.issues
    )


@pytest.mark.parametrize("distribution", [None, {}])
def test_query_user_coverage_requires_complete_scenario_distribution(
    tmp_path, distribution
):
    suite = load_suite("mini_agent_query_user_intent_v1")
    cases = compile_intent_candidates(_candidates_for_suite(suite), suite)
    plan = deepcopy(suite.coverage_plan)
    if distribution is None:
        plan.pop("scenario_type_distribution")
    else:
        plan["scenario_type_distribution"] = distribution
    (tmp_path / "coverage_plan.json").write_text(json.dumps(plan))
    broken_suite = replace(suite, coverage_plan_path=tmp_path / "coverage_plan.json")

    gate = coverage_gate(cases, broken_suite)

    assert not gate.passed
    assert any(
        "scenario type distribution is required" in issue for issue in gate.issues
    )


@pytest.mark.parametrize(
    ("parameters", "expected_issue"),
    [
        ({"user_id": True}, "user_id"),
        ({"user_id": 0}, "user_id"),
        ({"room_id": -1}, "room_id"),
        ({"email": "example.com"}, "email"),
        ({"email": "a@@b"}, "email"),
        ({"phone": 15000000200}, "phone"),
        ({"phone": "1500000020"}, "phone"),
        ({"phone": "15000A00200"}, "phone"),
        ({"user_id": None}, "omitted instead of null"),
        ({"user_ids": [1, 2]}, "Additional properties"),
        ({"user_id": [1, 2]}, "user_id"),
    ],
)
def test_query_user_parameter_contract_rejects_invalid_values(
    parameters, expected_issue
):
    query_user = load_suite("mini_agent_query_user_intent_v1").capability_ir
    issues = validate_parameters(
        parameters, query_user.parameters_schema, omit_null=True
    )
    assert any(expected_issue in issue for issue in issues)


def test_query_user_contract_rejects_broken_ready_and_clarification():
    suite = load_suite("mini_agent_query_user_intent_v1")
    base_cases = compile_intent_candidates(_candidates_for_suite(suite), suite)
    assert validate_module_intent_contract(base_cases, suite) == []

    broken = [deepcopy(base_cases[0]), deepcopy(base_cases[16])]
    ready = broken[0].oracle.expected_module_output
    ready["parameters"] = {}
    clarification = broken[1].oracle.expected_module_output
    clarification["next_action"] = "CALL_TOOL"
    clarification["missing_parameters"] = []

    issues = validate_module_intent_contract(broken, suite)

    assert any("requires at least 1 parameters" in issue for issue in issues)
    assert any("status/next_action mismatch" in issue for issue in issues)
    assert any("clarification needs missing_parameters" in issue for issue in issues)


@pytest.mark.parametrize(
    ("mode", "expected_issues"),
    [
        ("missing", ("exactly one slot label", "missing slot labels")),
        ("multiple", ("exactly one slot label", "duplicate slot labels")),
        ("unknown", ("unknown slot label", "missing slot labels")),
        ("duplicate", ("duplicate slot labels", "missing slot labels")),
    ],
)
def test_query_user_contract_rejects_invalid_slot_traceability(mode, expected_issues):
    suite = load_suite("mini_agent_query_user_intent_v1")
    cases = compile_intent_candidates(_candidates_for_suite(suite), suite)
    first_slot = next(label for label in cases[0].labels if label.startswith("slot:"))
    second_slot = next(label for label in cases[1].labels if label.startswith("slot:"))

    if mode == "missing":
        cases[0].labels.remove(first_slot)
    elif mode == "multiple":
        cases[1].labels.append(first_slot)
    elif mode == "unknown":
        cases[0].labels[cases[0].labels.index(first_slot)] = "slot:not_in_plan"
    else:
        cases[1].labels[cases[1].labels.index(second_slot)] = first_slot

    issues = validate_module_intent_contract(cases, suite)

    for expected_issue in expected_issues:
        assert any(expected_issue in issue for issue in issues)


def test_query_user_contract_rejects_scenario_type_different_from_slot():
    suite = load_suite("mini_agent_query_user_intent_v1")
    cases = compile_intent_candidates(_candidates_for_suite(suite), suite)
    cases[0].scenario_type = "valid_boundary"

    issues = validate_module_intent_contract(cases, suite)

    assert any(
        "scenario_type does not match coverage slot" in issue for issue in issues
    )


def test_query_user_seed_catalog_key_semantics_and_distribution():
    suite = load_suite("mini_agent_query_user_intent_v1")
    seed_path = suite.suite_dir / "seed_catalog.json"
    batch = suite.batch_type.model_validate_json(seed_path.read_text())
    by_slot = {candidate.slot_id: candidate for candidate in batch.candidates}

    assert len(batch.candidates) == 42
    assert all(candidate.rule_refs for candidate in batch.candidates)
    planned_rule_refs = {
        slot["slot_id"]: slot["rule_refs"] for slot in suite.coverage_plan["slots"]
    }
    assert all(
        candidate.rule_refs == planned_rule_refs[candidate.slot_id]
        for candidate in batch.candidates
    )
    assert Counter(candidate.expected_status for candidate in batch.candidates) == {
        "READY": 25,
        "NEED_CLARIFICATION": 17,
    }
    assert Counter(candidate.scenario_type for candidate in batch.candidates) == (
        SCENARIO_DISTRIBUTION
    )
    assert all(
        candidate.scenario_type
        == next(
            slot["scenario_type"]
            for slot in suite.coverage_plan["slots"]
            if slot["slot_id"] == candidate.slot_id
        )
        for candidate in batch.candidates
    )
    assert by_slot["explicit_user_id"].user_input == (
        "查询 UserID 为 9075333 的用户信息。"
    )
    assert json.loads(by_slot["explicit_user_id"].expected_parameters_json) == {
        "user_id": 9075333
    }
    assert (
        json.loads(by_slot["translated_user_id"].expected_parameters_json)["user_id"]
        == 9075334
    )
    assert json.loads(
        by_slot["inferred_phone_from_format"].expected_parameters_json
    ) == {"phone": "15000000200"}
    assert (
        json.loads(by_slot["variant_value_before_field"].expected_parameters_json)[
            "user_id"
        ]
        == 15000000200
    )
    assert by_slot["ambiguous_bare_positive_integer"].expected_status == (
        "NEED_CLARIFICATION"
    )
    assert by_slot["invalid_phone_length"].missing_parameters == ["phone"]
    assert by_slot["and_user_id_phone"].expected_status == "READY"
    assert json.loads(by_slot["and_user_id_phone"].expected_parameters_json) == {
        "user_id": 9075333,
        "phone": "15000000200",
    }
    assert by_slot["explicit_two_users_not_and"].missing_parameters == [
        "single_user_query_condition"
    ]
    assert (
        json.loads(by_slot["correction_latest_value"].expected_parameters_json)[
            "user_id"
        ]
        == 9075334
    )
    assert by_slot["conflicting_same_field_values"].missing_parameters == [
        "single_user_id"
    ]
    assert by_slot["repeated_bare_positive_integer_ambiguous"].scenario_type == (
        "ambiguous_expression"
    )
    assert by_slot["missing_all_conditions"].scenario_type == "missing_parameter"
    assert by_slot["explicit_two_users_not_and"].scenario_type == ("unsupported_batch")
    assert by_slot["batch_user_ids"].missing_parameters == ["single_user_id"]


def test_query_user_seed_runs_through_public_pipeline(tmp_path):
    suite = load_suite("mini_agent_query_user_intent_v1")
    seed = json.loads((suite.suite_dir / "seed_catalog.json").read_text())
    workspace = tmp_path / "query-user-run"

    request = prepare_generation(suite, workspace)

    assert (workspace / "capability_bundle" / "agent.json").is_file()
    assert (
        workspace / "capability_bundle" / "modules" / "intent_router.json"
    ).is_file()
    assert (workspace / "capability_bundle" / "intents" / "query_user.json").is_file()
    assert request.capability_bundle_sha256 == (
        suite.validated_capability_bundle.capability_bundle_sha256
    )
    assert {
        "boundary.understanding",
        "evidence.intent_result",
        "intent.query_user",
        "module.intent_router",
        "module.model_gateway",
        "scope.understanding",
    } <= {item["snapshot_id"] for item in request.capability_source_artifacts}
    assert (
        request.agent_snapshot_sha256
        == suite.validated_capability_bundle.root.snapshot_sha256
    )
    assert request.capability_selection["scope_or_chain_id"] == (
        "scope.understanding"
    )
    assert request.capability_ir_binding["sha256"] == (
        suite.capability_ir.canonical_sha256
    )
    assert len(request.trusted_schema_bindings) == 9
    assert len(request.capability_bundle_files) == 44
    assert "intent_contracts.py" not in request.prompt
    assert "seed_catalog.json" not in request.prompt
    raw = generate_candidates(request, ScriptedGenerationClient(seed), workspace)
    cases = compile_candidates(suite, raw, workspace)
    report = validate_draft(suite, workspace / "draft.jsonl", workspace)

    assert len(cases) == 42
    assert report.valid
    assert report.state == "VALIDATED"
    assert all(gate.passed for gate in report.gates)
    assert request.suite_config_sha256 == sha256_file(suite.suite_dir / "suite.json")
    generation_manifest = json.loads(
        (workspace / "generation_manifest.json").read_text()
    )
    assert generation_manifest["suite_config_sha256"] == (request.suite_config_sha256)


def test_query_user_parser_rejects_status_swapped_between_slots(tmp_path):
    suite = load_suite("mini_agent_query_user_intent_v1")
    seed = json.loads((suite.suite_dir / "seed_catalog.json").read_text())
    request = prepare_generation(suite, tmp_path)
    raw = ScriptedGenerationClient(seed).generate(request)
    ready = raw.response["candidates"][0]
    clarification = raw.response["candidates"][16]
    fields = (
        "expected_status",
        "expected_next_action",
        "expected_parameters_json",
        "missing_parameters",
    )
    for field in fields:
        ready[field], clarification[field] = clarification[field], ready[field]

    with pytest.raises(ValueError, match="slot explicit_user_id status"):
        parse_candidates(suite, raw)
