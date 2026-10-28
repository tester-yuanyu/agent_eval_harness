from __future__ import annotations

import json
from collections import Counter

from dataset_builder.generation_client import ScriptedGenerationClient
from dataset_builder.pipeline import (
    compile_candidates,
    generate_candidates,
    prepare_generation,
    validate_draft,
)
from dataset_builder.suite_definition import load_suite


def test_add_backpack_gift_suite_generates_confirmation_bound_intent_cases(
    tmp_path,
):
    suite = load_suite("mini_agent_add_backpack_gift_intent_v1")
    seed = json.loads(suite.seed_catalog_path.read_text())
    workspace = tmp_path / "add-backpack-gift"

    assert suite.dataset_version == "2.0"
    assert suite.test_scope == "module"
    assert suite.target == "intent_router"
    assert suite.prompt_version == "add-backpack-gift-intent-v2"
    assert suite.capability_ir.intent.snapshot_id == "intent.add_backpack_gift"
    assert suite.capability_ir.intent.required_tool_name == "add_gift_to_backpack"
    assert suite.capability_ir.selected_node.snapshot_id == "scope.understanding"
    assert suite.capability_ir.decision_rules["complete"] == {
        "status": "NEED_CONFIRMATION",
        "next_action": "ASK_CONFIRMATION",
    }
    assert suite.coverage_plan["case_count"] == 28
    assert suite.coverage_plan["status_distribution"] == {
        "NEED_CONFIRMATION": 12,
        "NEED_CLARIFICATION": 16,
    }

    request = prepare_generation(suite, workspace)
    raw = generate_candidates(request, ScriptedGenerationClient(seed), workspace)
    cases = compile_candidates(suite, raw, workspace)
    report = validate_draft(suite, workspace / "draft.jsonl", workspace)

    assert len(cases) == 28
    assert report.valid
    assert report.state == "VALIDATED"
    assert all(gate.passed for gate in report.gates)
    assert Counter(case.scenario_type for case in cases) == {
        "normal": 6,
        "expression_variant": 2,
        "valid_boundary": 4,
        "missing_parameter": 4,
        "multi_condition": 4,
        "invalid_parameter": 8,
    }
    assert [case.case_id for case in cases] == [
        f"MINI-ABGIFT-{index:03d}" for index in range(1, 29)
    ]
    assert all(case.task_id == "intent-add-backpack-gift" for case in cases)
    assert all(case.oracle.expected_tool_calls == [] for case in cases)
    assert all(case.execution.allowed_tools == [] for case in cases)

    confirmation_cases = [
        case
        for case in cases
        if case.oracle.expected_module_output["status"] == "NEED_CONFIRMATION"
    ]
    assert len(confirmation_cases) == 12
    assert all(
        case.oracle.expected_module_output["next_action"] == "ASK_CONFIRMATION"
        for case in confirmation_cases
    )
    assert all(case.execution.user_responses == [] for case in cases)
    assert all(case.cleanup is None for case in cases)

    by_slot = {
        next(
            label.removeprefix("slot:")
            for label in case.labels
            if label.startswith("slot:")
        ): case
        for case in cases
    }
    assert by_slot["default_num_and_duration"].oracle.expected_module_output[
        "parameters"
    ] == {"user_id": 3102, "gift_id": 7206, "environment": "test"}
    assert by_slot["permanent_duration"].oracle.expected_module_output[
        "parameters"
    ]["duration_days"] == 1000
    assert by_slot["missing_environment"].oracle.expected_module_output[
        "missing_parameters"
    ] == ["environment"]
    assert by_slot["conflict_user_modes"].oracle.expected_module_output[
        "missing_parameters"
    ] == ["single_user_selection_mode"]

    exact_clarification_oracles = {
        "conflict_user_modes": (
            {
                "user_id": 3116,
                "user_ids": [3117, 3118],
                "gift_id": 7221,
                "environment": "test",
            },
            ["single_user_selection_mode"],
        ),
        "conflict_gift_id_and_ids": (
            {
                "user_id": 3119,
                "gift_id": 7222,
                "gift_ids": [7223, 7224],
                "environment": "test",
            },
            ["single_gift_selection_mode"],
        ),
        "conflict_gift_id_and_nums": (
            {
                "user_id": 3120,
                "gift_id": 7225,
                "gift_nums": [{"gift_id": 7226, "num": 2}],
                "environment": "staging",
            },
            ["single_gift_selection_mode"],
        ),
        "conflict_gift_ids_and_nums": (
            {
                "user_id": 3121,
                "gift_ids": [7227, 7228],
                "gift_nums": [{"gift_id": 7229, "num": 3}],
                "environment": "prod",
            },
            ["single_gift_selection_mode"],
        ),
        "invalid_user_id_zero": (
            {"gift_id": 7230, "environment": "test"},
            ["user_id"],
        ),
        "invalid_user_ids_empty": (
            {"gift_id": 7231, "environment": "test"},
            ["user_ids"],
        ),
        "invalid_gift_id_zero": (
            {"user_id": 3122, "environment": "staging"},
            ["gift_id"],
        ),
        "invalid_gift_ids_member": (
            {"user_id": 3123, "environment": "test"},
            ["gift_ids"],
        ),
        "invalid_environment_empty": (
            {"user_id": 3124, "gift_id": 7233},
            ["environment"],
        ),
        "invalid_gift_nums_num": (
            {"user_id": 3125, "environment": "staging"},
            ["gift_nums"],
        ),
        "invalid_num_zero": (
            {"user_id": 3126, "gift_id": 7234, "environment": "test"},
            ["num"],
        ),
        "invalid_duration_above_maximum": (
            {"user_id": 3127, "gift_id": 7235, "environment": "prod"},
            ["duration_days"],
        ),
    }
    for slot_id, (parameters, missing_parameters) in (
        exact_clarification_oracles.items()
    ):
        expected = by_slot[slot_id].oracle.expected_module_output
        assert expected["status"] == "NEED_CLARIFICATION"
        assert expected["next_action"] == "ASK_USER"
        assert expected["parameters"] == parameters
        assert expected["missing_parameters"] == missing_parameters
