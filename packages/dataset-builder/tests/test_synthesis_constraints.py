from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from dataset_builder.coverage import coverage_gate
from dataset_builder.scenario_requirements import candidate_issues, load_requirements
from dataset_builder.source_pack import build_source_pack
from dataset_builder.suite_definition import load_suite


@pytest.fixture
def repaired_suite():
    return load_suite("mini_agent_query_user_intent_v3")


@pytest.fixture
def reference_candidates():
    return json.loads(
        Path("suites/mini_agent_query_user_intent_v2/seed_catalog.json").read_text()
    )["candidates"]


@pytest.fixture
def failed_candidates():
    return json.loads(
        Path("tests/fixtures/deepeval_first_run_candidates.json").read_text()
    )["candidates"]


def test_all_reference_inputs_satisfy_new_requirements(
    repaired_suite, reference_candidates
):
    for candidate, slot in zip(
        reference_candidates, repaired_suite.coverage_plan["slots"], strict=True
    ):
        assert candidate_issues(candidate, repaired_suite, slot) == [], candidate[
            "slot_id"
        ]


@pytest.mark.parametrize(
    "number", [7, 17, 18, 20, 21, 22, 26, 36, 39, 42, 11, 12, 28, 31, 37, 38]
)
def test_first_live_failures_are_now_blocked(repaired_suite, failed_candidates, number):
    candidate = failed_candidates[number - 1]
    slot = repaired_suite.coverage_plan["slots"][number - 1]
    assert candidate_issues(candidate, repaired_suite, slot)


def test_coverage_gate_rejects_correct_labels_with_wrong_scenario(
    repaired_suite, reference_candidates, failed_candidates
):
    candidates = deepcopy(reference_candidates)
    candidates[36] = failed_candidates[36]
    batch = repaired_suite.batch_type.model_validate({"candidates": candidates})
    cases = repaired_suite.compiler(batch.candidates, repaired_suite)
    result = coverage_gate(cases, repaired_suite)
    assert not result.passed
    assert any("MINI-QUSER-037" in issue for issue in result.issues)


def test_grounding_rejects_parameter_not_present_in_input(
    repaired_suite, reference_candidates
):
    candidate = deepcopy(reference_candidates[0])
    candidate["expected_parameters_json"] = '{"user_id":907533}'
    issues = candidate_issues(
        candidate, repaired_suite, repaired_suite.coverage_plan["slots"][0]
    )
    assert any("ground" in issue for issue in issues)


def test_correction_must_use_final_value(repaired_suite, reference_candidates):
    candidate = deepcopy(reference_candidates[34])
    candidate["expected_parameters_json"] = '{"user_id":9075333}'
    issues = candidate_issues(
        candidate, repaired_suite, repaired_suite.coverage_plan["slots"][34]
    )
    assert any("final" in issue for issue in issues)


@pytest.mark.parametrize(
    "change",
    [
        {"unknown_predicate": True},
        {"input_must_match": ["["]},
        {"evidence_refs": ["/semantic_rules/nonexistent"]},
    ],
)
def test_unknown_or_unbound_requirement_fails_closed(repaired_suite, change, tmp_path):
    plan = deepcopy(repaired_suite.coverage_plan)
    plan["slots"][0]["acceptance"].update(change)
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError):
        load_requirements(replace(repaired_suite, coverage_plan_path=path))


def test_validation_policy_is_model_visible_and_hash_bound(repaired_suite):
    text, manifest = build_source_pack(repaired_suite)
    assert '"omit_null_parameters": true' in text
    assert '"missing_parameters": "non_empty"' in text
    assert any(item["path"].endswith("policies/validation.json") for item in manifest)


def test_legacy_plan_does_not_gain_new_predicates():
    assert load_requirements(load_suite("mini_agent_query_user_intent_v2")) == {}


@pytest.mark.parametrize(
    "number,text",
    [
        (1, "查询用户ID -9075333 的信息"),
        (28, "查询 15000000200 的用户信息"),
        (38, "查询15000000200，再说一遍15000000200"),
        (39, "查询用户ID9075340和9075340的信息"),
    ],
)
def test_scalar_and_scenario_near_misses_are_rejected(
    repaired_suite, reference_candidates, number, text
):
    candidate = deepcopy(reference_candidates[number - 1])
    candidate["user_input"] = text
    assert candidate_issues(
        candidate, repaired_suite, repaired_suite.coverage_plan["slots"][number - 1]
    )


def test_contract_gap_blocks_release_even_when_all_slot_checks_pass(
    repaired_suite, reference_candidates
):
    batch = repaired_suite.batch_type.model_validate(
        {"candidates": reference_candidates}
    )
    cases = repaired_suite.compiler(batch.candidates, repaired_suite)
    gate = coverage_gate(cases, repaired_suite)
    blockers = [issue for issue in gate.issues if "unresolved oracle contract" in issue]
    assert not gate.passed
    assert len(blockers) == 17
    assert all("missing_parameters" in issue for issue in blockers)


@pytest.mark.parametrize(
    "number,text,parameters",
    [
        (12, "查询用户ID 13800138000 的信息", {"phone": "13800138000"}),
        (28, "查询 12345，这个数字是用户ID", {}),
        (38, "查询12345，再说一次12345，这个数字是用户ID", {}),
        (39, "查用户ID12345，不对，改成用户ID67890", {}),
        (40, "查直播间ID12345，不对，改成直播间ID67890", {}),
        (41, "查手机号13800138000，不对，改成13900139000", {}),
    ],
)
def test_explicit_binding_and_correction_cannot_hide_in_ambiguous_slots(
    repaired_suite, reference_candidates, number, text, parameters
):
    candidate = deepcopy(reference_candidates[number - 1])
    candidate.update(user_input=text, expected_parameters_json=json.dumps(parameters))
    assert candidate_issues(
        candidate, repaired_suite, repaired_suite.coverage_plan["slots"][number - 1]
    )
