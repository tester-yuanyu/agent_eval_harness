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


def test_query_gift_suite_generates_contract_bound_intent_cases(tmp_path):
    suite = load_suite("mini_agent_query_gift_intent_v1")
    seed = json.loads(suite.seed_catalog_path.read_text())
    workspace = tmp_path / "query-gift"

    assert suite.dataset_version == "2.0"
    assert suite.test_scope == "module"
    assert suite.target == "intent_router"
    assert suite.prompt_version == "query-gift-intent-v2"
    assert suite.capability_ir.intent.snapshot_id == "intent.query_gift"
    assert suite.capability_ir.selected_node.snapshot_id == "scope.understanding"
    assert suite.coverage_plan["case_count"] == 23
    assert suite.coverage_plan["status_distribution"] == {
        "READY": 13,
        "NEED_CLARIFICATION": 10,
    }

    request = prepare_generation(suite, workspace)
    raw = generate_candidates(request, ScriptedGenerationClient(seed), workspace)
    cases = compile_candidates(suite, raw, workspace)
    report = validate_draft(suite, workspace / "draft.jsonl", workspace)

    assert len(cases) == 23
    assert report.valid
    assert report.state == "VALIDATED"
    assert all(gate.passed for gate in report.gates)
    assert Counter(case.scenario_type for case in cases) == {
        "normal": 6,
        "expression_variant": 3,
        "valid_boundary": 4,
        "invalid_parameter": 5,
        "missing_parameter": 2,
        "multi_condition": 3,
    }
    assert [case.case_id for case in cases] == [
        f"MINI-QGIFT-{index:03d}" for index in range(1, 24)
    ]
    assert all(case.task_id == "intent-query-gift" for case in cases)
