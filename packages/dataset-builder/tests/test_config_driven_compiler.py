from __future__ import annotations

import inspect

from dataset_builder.intent_compiler import compile_intent_candidates
from dataset_builder.suite_definition import load_suite


def _seed_candidates(suite_id: str):
    suite = load_suite(suite_id)
    batch = suite.batch_type.model_validate_json(
        suite.seed_catalog_path.read_text()
    )
    return suite, batch.candidates


def test_query_user_compilation_is_entirely_config_driven():
    suite, candidates = _seed_candidates("mini_agent_query_user_intent_v1")
    cases = compile_intent_candidates(candidates, suite)

    assert [case.case_id for case in cases] == [
        f"MINI-QUSER-{index:03d}" for index in range(1, 43)
    ]
    assert all(case.task_id == "intent-query-user" for case in cases)
    assert all(case.test_scope == "module" for case in cases)
    assert all(case.target == "intent_router" for case in cases)
    assert all(case.execution.tool_profile == "shadow_read" for case in cases)
    assert all(case.execution.user_responses == [] for case in cases)
    assert all(case.execution.fault_injection == {} for case in cases)
    assert all(case.execution.max_steps == 4 for case in cases)
    assert all(case.execution.timeout_seconds == 30.0 for case in cases)
    assert all(case.cleanup is None for case in cases)

    first = cases[0]
    assert "contract:query-user-intent-contract-v3" in first.labels
    assert "slot:explicit_user_id" in first.labels
    assert "rule:query_user.field_rules.user_id.aliases" in first.labels
    assert "READY" in first.labels
    assert first.oracle.expected_module_output["reason"] == (
        "预期决策由评测集约束定义。"
    )
    assert [check.weight for check in first.oracle.evaluation.checks] == [
        10,
        30,
        20,
        10,
        20,
        10,
    ]
    assert all(check.critical for check in first.oracle.evaluation.checks)


def test_generic_intent_compilation_uses_configured_conditionals():
    suite, candidates = _seed_candidates("mini_agent_intent_v1")
    cases = compile_intent_candidates(candidates, suite)
    by_id = {case.case_id: case for case in cases}

    assert len(cases) == 15
    assert by_id["MINI-INTENT-001"].task_id == "intent-query-user"
    assert by_id["MINI-INTENT-001"].scenario_type == "normal"
    assert by_id["MINI-INTENT-011"].execution.user_responses == ["确认"]
    assert by_id["MINI-INTENT-011"].cleanup.model_dump(mode="json") == {
        "required": True,
        "strategy": "temporary_directory",
    }
    assert by_id["MINI-INTENT-001"].cleanup is None
    assert by_id["MINI-INTENT-001"].oracle.expected_module_output["reason"] == (
        "Expected decision defined by the benchmark contract."
    )


def test_compiler_source_has_no_suite_or_tool_dispatch():
    source = inspect.getsource(compile_intent_candidates)

    assert "mini_agent_query_user_intent_v1" not in source
    assert "mini_agent_intent_v1" not in source
    assert "query_user_info" not in source
    assert "if suite.suite_id" not in source
