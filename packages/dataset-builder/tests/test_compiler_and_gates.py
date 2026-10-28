from __future__ import annotations

import json
import shutil
from collections import Counter
from dataclasses import replace
from pathlib import Path

from dataset_builder.coverage import coverage_gate, duplicate_gate
from dataset_builder.leakage import leakage_gate
from dataset_builder.pipeline import validate_draft
from dataset_builder.suite_config import CoverageConfig, DistributionField
from dataset_builder.validation import evaluator_gate, write_jsonl


def test_compiler_is_stable_and_injects_fixed_fields(authored):
    _, _, _, cases = authored
    assert [case.case_id for case in cases] == [
        f"MINI-INTENT-{index:03d}" for index in range(1, 16)
    ]
    assert cases[0].task_id == "intent-query-user"
    assert all(case.execution.tool_profile == "shadow_full" for case in cases)
    write_cases = [
        case
        for case in cases
        if case.oracle.expected_module_output["intent"]
        in {"add_backpack_gift", "update_pool_weight"}
    ]
    assert all(case.execution.user_responses == ["确认"] for case in write_cases)
    assert all(case.cleanup is not None for case in write_cases)


def test_reason_assertions_labels_are_fixed(authored):
    _, _, _, cases = authored
    for case in cases:
        expected = case.oracle.expected_module_output
        assert expected["reason"] == (
            "Expected decision defined by the benchmark contract."
        )
        checks = case.oracle.evaluation.checks
        assert sum(check.weight for check in checks) == 100
        assert all(check.critical and check.config == {} for check in checks)
        assert {"mini_agent", "module", "shadow"} <= set(case.labels)


def test_status_distribution_and_coverage(authored, suite):
    workspace, _, _, cases = authored
    counts = Counter(case.oracle.expected_module_output["status"] for case in cases)
    assert counts == {
        "READY": 6,
        "NEED_CLARIFICATION": 6,
        "NEED_CONFIRMATION": 2,
        "REJECTED": 1,
    }
    report = validate_draft(suite, workspace / "draft.jsonl", workspace)
    coverage = next(gate for gate in report.gates if gate.name == "coverage")
    assert coverage.passed


def test_generic_suite_evaluator_accepts_schema_valid_cases(
    authored, suite
):
    workspace, _, _, _ = authored
    report = validate_draft(suite, workspace / "draft.jsonl")
    evaluator = next(gate for gate in report.gates if gate.name == "evaluator")
    assert evaluator.passed
    assert not evaluator.issues


def test_evaluator_gate_uses_suite_case_count(tmp_path, authored, suite):
    _, _, _, cases = authored
    draft = tmp_path / "one-case.jsonl"
    write_jsonl(cases[:1], draft)
    (tmp_path / "coverage_plan.json").write_text(
        json.dumps({"case_count": 1, "slots": []})
    )
    one_case_suite = replace(suite, coverage_plan_path=tmp_path / "coverage_plan.json")

    gate, loaded_cases = evaluator_gate(draft, one_case_suite)

    assert not gate.passed
    assert loaded_cases == []
    assert gate.issues == ["generation_capability_bundle_missing"]


def test_duplicate_and_leakage_are_detected(authored):
    _, _, _, cases = authored
    duplicate = [case.model_copy(deep=True) for case in cases]
    duplicate[1].execution.user_input = duplicate[0].execution.user_input
    assert not duplicate_gate(duplicate).passed
    leaked = [case.model_copy(deep=True) for case in cases]
    leaked[0].execution.user_input = "expected_intent 是 query_user"
    assert not leakage_gate(leaked).passed


def test_missing_case_cannot_validate(tmp_path, authored, suite):
    workspace, _, _, cases = authored
    path = tmp_path / "missing.jsonl"
    write_jsonl(cases[:-1], path)
    shutil.copytree(
        workspace / "capability_bundle",
        tmp_path / "capability_bundle",
    )
    shutil.copyfile(
        workspace / "generation_manifest.json",
        tmp_path / "generation_manifest.json",
    )
    shutil.copyfile(
        workspace / "generation_request.json",
        tmp_path / "generation_request.json",
    )
    report = validate_draft(suite, path)
    assert not report.valid
    assert next(g for g in report.gates if g.name == "coverage").passed is False


def test_draft_execution_contains_no_oracle_leakage(authored):
    _, _, _, cases = authored
    assert leakage_gate(cases).passed
    for case in cases:
        execution = json.dumps(case.execution.model_dump())
        assert "expected" not in execution
        assert "case_id" not in execution


def test_coverage_gate_uses_declared_distribution_fields(tmp_path, authored, suite):
    _, _, _, cases = authored
    plan = {
        "case_count": len(cases),
        "slots": [{"task_id": case.task_id} for case in cases],
    }
    plan_path = tmp_path / "coverage_plan.json"
    plan_path.write_text(json.dumps(plan))
    coverage_config = CoverageConfig(
        distribution_fields=[
            DistributionField(
                report_name="task_distribution",
                case_pointers=["/task_id"],
                plan_field=None,
                slot_fields=["task_id"],
            )
        ]
    )
    coverage_policy = suite.policy_set.coverage.model_copy(
        update={"config": coverage_config}
    )
    policy_set = suite.policy_set.model_copy(
        update={"coverage": coverage_policy}
    )
    configured_suite = replace(
        suite,
        policy_set=policy_set,
        coverage_plan_path=plan_path,
    )

    gate = coverage_gate(cases, configured_suite)

    assert gate.passed
    assert gate.details["task_distribution"]["intent-query-user"] == 3


def test_coverage_gate_rejects_missing_or_duplicate_case(authored, suite):
    _, _, _, cases = authored

    missing = coverage_gate(cases[:-1], suite)
    duplicate = coverage_gate([*cases[:-1], cases[0]], suite)

    assert not missing.passed
    assert not duplicate.passed


def test_forbidden_intents_come_from_suite_config(authored, suite):
    _, _, _, cases = authored
    changed = [case.model_copy(deep=True) for case in cases]
    changed[0].oracle.expected_module_output["intent"] = "prepare_resource"

    gate = coverage_gate(changed, suite)

    assert not gate.passed
    assert any("prepare_resource" in issue for issue in gate.issues)


def test_regeneration_script_imports_no_query_user_specific_module():
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "regenerate_query_user_offline.py").read_text()

    assert "query_user_intent_suite" not in source
