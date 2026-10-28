from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from dataset_builder.full_comparison.plan import load_plan
from dataset_builder.full_comparison.validation import validate_candidate

BASE = (
    Path(__file__).resolve().parents[1]
    / "workspaces/full_tools_fixture_v1_full_eval_20261020"
)


@pytest.fixture(scope="module")
def plan():
    return load_plan(BASE)


def choose(plan, **fields):
    return next(s for s in plan.specs if all(s[k] == v for k, v in fields.items()))


def candidate(spec, stimulus, oracle=None):
    return {
        "input": stimulus,
        "oracle": oracle,
        "preconditions": [],
        "evidence_refs": spec["evidence_refs"],
        "rationale": "根据绑定契约设计。",
        "gap": spec["gap_reason"] if spec["input_only"] else None,
    }


def parameter_case(plan, dimension):
    spec = choose(
        plan,
        target_id="tool.query_user_info",
        case_kind="parameter",
        dimension=dimension,
        parameter="user_id",
    )
    args = {"user_id": 1, "room_id": None, "phone": None, "email": None}
    return spec, candidate(
        spec,
        {
            "operation": "validate_arguments",
            "arguments": args,
            "parameter": "user_id",
            "dimension": dimension,
        },
        {
            "arguments_schema_valid": True,
            "checks": [
                {"op": "schema_valid", "actual": "input.arguments", "expected": True}
            ],
        },
    )


def test_all_targets_accounted_without_old_oracles(plan):
    assert len(plan.specs) == 847
    assert len({s["target_id"] for s in plan.specs}) == 23
    assert sum(s["definition_kind"] == "behavior_case" for s in plan.specs) == 365
    assert sum(s["definition_kind"] == "contract_check" for s in plan.specs) == 202
    assert sum(s["definition_kind"] == "blocked_obligation" for s in plan.specs) == 280
    missing = choose(
        plan,
        target_id="intent.query_user",
        case_kind="intent_case",
        dimension="missing",
    )
    assert missing["input_only"] and "missing_parameters" in missing["gap_reason"]
    assert "seed_catalog" not in plan.context(missing)
    assert "case_id" not in plan.context(missing)
    assert "EXAMPLES" not in plan.context(missing)


def test_source_tamper_fails_before_generation(tmp_path):
    # Loading must check historical source hashes, not just trust inventory JSON.
    import shutil

    shutil.copytree(BASE, tmp_path / "copy")
    path = tmp_path / "copy/capability_bundle/tools/query_user_info.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="hash|source"):
        load_plan(tmp_path / "copy")


def test_blocked_oracle_and_hidden_answer_rejected(plan):
    s = next(s for s in plan.specs if s["definition_kind"] == "blocked_obligation")
    c = candidate(
        s,
        {
            "operation": "contract_gap",
            "requirement": "契约缺少绑定",
            "needed_contract": "补充刺激和观测接口",
        },
    )
    assert validate_candidate(c, s, plan) == []
    c["oracle"] = {
        "checks": [{"op": "equals", "actual": "status", "expected": "SUCCESS"}]
    }
    assert validate_candidate(c, s, plan)
    c["oracle"] = None
    c["input"]["expected_output"] = "SUCCESS"
    assert validate_candidate(c, s, plan)


def test_static_assertion_must_equal_exact_source_value(plan):
    s = next(s for s in plan.specs if s["case_kind"] == "schema_constraint")
    c = candidate(
        s,
        {"operation": "inspect_declared_constraint", "pointer": s["pointer"]},
        {
            "checks": [
                {
                    "op": "equals",
                    "actual": "contract" + s["pointer"],
                    "expected": plan.declared(s),
                }
            ]
        },
    )
    assert validate_candidate(c, s, plan) == []
    c["oracle"]["checks"][0]["expected"] = "invented"
    assert validate_candidate(c, s, plan)


def test_parameter_dimension_checked_not_only_whole_schema(plan):
    s, c = parameter_case(plan, "wrong_type")
    assert validate_candidate(c, s, plan)
    c["input"]["arguments"]["user_id"] = {"wrong": "type"}
    c["oracle"]["arguments_schema_valid"] = False
    c["oracle"]["checks"][0]["expected"] = False
    assert validate_candidate(c, s, plan) == []
    c["input"]["arguments"]["phone"] = "bad"
    assert validate_candidate(c, s, plan)


def test_parameter_boundary_and_invented_oracle_rejected(plan):
    s, c = parameter_case(plan, "boundary")
    assert validate_candidate(c, s, plan) == []
    c["input"]["arguments"]["user_id"] = 50
    assert validate_candidate(c, s, plan)
    c["input"]["arguments"]["user_id"] = 1
    c["oracle"]["checks"].append(
        {"op": "equals", "actual": "tool_result.code", "expected": "OK"}
    )
    assert validate_candidate(c, s, plan)


def test_optional_omission_may_be_schema_valid(plan):
    s = choose(
        plan,
        target_id="intent.query_user",
        case_kind="parameter",
        dimension="omitted",
        parameter="user_id",
    )
    c = candidate(
        s,
        {
            "operation": "validate_arguments",
            "arguments": {},
            "parameter": "user_id",
            "dimension": "omitted",
        },
        {
            "arguments_schema_valid": True,
            "checks": [
                {"op": "schema_valid", "actual": "input.arguments", "expected": True}
            ],
        },
    )
    assert validate_candidate(c, s, plan) == []


def test_complete_intent_values_must_be_grounded(plan):
    s = choose(
        plan,
        target_id="intent.query_user",
        case_kind="intent_case",
        dimension="complete",
    )
    c = candidate(
        s,
        {"user_input": "查询用户 ID 127 的信息。"},
        {
            "expected_module_output": {
                "intent": "query_user",
                "status": "READY",
                "next_action": "CALL_TOOL",
                "parameters": {"user_id": 127},
                "missing_parameters": [],
            }
        },
    )
    assert validate_candidate(c, s, plan) == []
    c["oracle"]["expected_module_output"]["parameters"]["user_id"] = 999
    assert validate_candidate(c, s, plan)


def test_declared_tool_code_and_event_are_enforced(plan):
    s = choose(
        plan, target_id="tool.query_user_info", case_kind="tool_result", dimension="OK"
    )
    c = candidate(
        s,
        {
            "operation": "invoke_tool",
            "tool_name": "query_user_info",
            "arguments": {"user_id": 1, "room_id": None, "email": None, "phone": None},
        },
        {
            "checks": [
                {"op": "equals", "actual": "tool_result.code", "expected": "MADE_UP"}
            ]
        },
    )
    assert validate_candidate(c, s, plan)
    s = choose(
        plan,
        target_id="module.tool_loop",
        case_kind="module_event",
        dimension="tool_failed",
    )
    c = candidate(
        s,
        {
            "operation": "observe_module_event",
            "stimulus": {
                "action": "invoke_registered_tool",
                "handler": "returns_declared_OK",
            },
        },
        {
            "checks": [
                {
                    "op": "subset",
                    "actual": "trace.event_types",
                    "expected": ["tool_succeeded"],
                }
            ]
        },
    )
    assert validate_candidate(c, s, plan)


def test_duplicate_fingerprint_preserves_semantic_symbols():
    from dataset_builder.full_comparison.validation import fingerprint

    assert fingerprint({"user_input": "邮箱 a@b"}) != fingerprint(
        {"user_input": "邮箱 ab"}
    )
    assert fingerprint({"arguments": {"user_id": -1}}) != fingerprint(
        {"arguments": {"user_id": 1}}
    )


def test_oracle_cannot_hide_unvalidated_extra_claims(plan):
    s, c = parameter_case(plan, "valid")
    c["oracle"]["invented_business_success"] = True
    assert validate_candidate(c, s, plan)


def test_backend_direct_uses_one_call_and_does_not_copy_seed(plan):
    from dataset_builder.full_comparison.backend import DirectBackend

    s, c = parameter_case(plan, "valid")
    calls = []

    class Provider:
        def complete(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            return json.dumps(c), 0

    got = DirectBackend(Provider()).generate(plan.context(s), s, plan)
    assert got["candidate"] == c and len(calls) == 1
    assert calls[0][1] == {"json_mode": True}


def test_native_sdk_forbids_nested_extra_fields():
    from deepeval.synthesizer.schema import SyntheticDataList

    from dataset_builder.full_comparison.backend import strict_sdk_value

    with pytest.raises(ValueError, match="Additional properties"):
        strict_sdk_value(
            '{"data":[{"input":"x","expected_output":"fake"}]}', SyntheticDataList
        )


def test_runner_keeps_failures_and_resumes_without_rebilling(tmp_path, plan):
    from dataset_builder.full_comparison.runner import run_slot

    s, c = parameter_case(plan, "valid")
    called = []

    class Backend:
        def generate(self, *args):
            called.append(1)
            if len(called) == 1:
                raise ValueError("invalid model JSON")
            return {"candidate": deepcopy(c), "raw": "original"}

    result = run_slot(plan, s, "direct", tmp_path, Backend(), max_attempts=3)
    assert result["accepted"] and result["accepted_attempt"] == 2
    assert result["attempt_count"] == 2 and result["first_pass"] is False
    assert len(called) == 2
    repeat = run_slot(plan, s, "direct", tmp_path, Backend(), max_attempts=3)
    assert repeat == result and len(called) == 2
    assert json.loads((tmp_path / "attempt_1.json").read_text())["issues"]


def test_runner_exhausts_slot_without_claiming_acceptance(tmp_path, plan):
    from dataset_builder.full_comparison.runner import run_slot

    s, c = parameter_case(plan, "valid")

    class Backend:
        def generate(self, *args):
            return {"candidate": {}, "raw": "{}"}

    r = run_slot(plan, s, "deepeval", tmp_path, Backend(), max_attempts=2)
    assert not r["accepted"] and r["attempt_count"] == 2 and r["candidate"] is None


def test_runner_interrupted_attempt_consumes_budget(tmp_path, plan):
    from dataset_builder.full_comparison.runner import run_slot

    s, c = parameter_case(plan, "valid")
    (tmp_path / "attempt_1.started.json").write_text("{}")

    class Backend:
        def generate(self, *args):
            return {"candidate": deepcopy(c), "raw": "fresh"}

    r = run_slot(plan, s, "direct", tmp_path, Backend(), max_attempts=2)
    assert r["accepted_attempt"] == 2 and not r["first_pass"]
    assert (
        "interrupted"
        in json.loads((tmp_path / "attempt_1.json").read_text())["issues"][0]
    )


def test_compiler_never_promotes_input_only_to_executable(plan):
    from dataset_builder.full_comparison.runner import compile_candidate

    s = choose(
        plan,
        target_id="intent.query_user",
        case_kind="intent_case",
        dimension="missing",
    )
    c = candidate(s, {"user_input": "查一下用户信息"})
    output = compile_candidate(c, s, plan, "direct")
    assert output["execution_readiness"] == "blocked"
    assert output["payload"]["oracle"]["checks"] == []


def test_user_tool_success_requires_matching_fixture_not_only_code(plan):
    s = choose(
        plan, target_id="tool.query_user_info", case_kind="tool_result", dimension="OK"
    )
    c = candidate(
        s,
        {
            "operation": "invoke_tool",
            "tool_name": "query_user_info",
            "arguments": {"user_id": 3, "room_id": None, "email": None, "phone": None},
        },
        {
            "checks": [
                {"op": "equals", "actual": "tool_result.code", "expected": "OK"},
                {
                    "op": "schema_valid",
                    "actual": "tool_result.data",
                    "expected": plan.declared(s)["data_schema"],
                },
            ],
            "declared_terminal_status": plan.declared(s)["terminal_status"],
        },
    )
    c["preconditions"] = [
        {
            "kind": "fixture_setup",
            "fresh_instance": True,
            "records": {
                "users": [
                    {"user_id": 9, "room_id": 1, "email": "a@b", "phone": "12345678901"}
                ]
            },
        }
    ]
    assert validate_candidate(c, s, plan)
    c["preconditions"][0]["records"]["users"][0]["user_id"] = 3
    assert validate_candidate(c, s, plan) == []


def test_module_validation_failure_requires_invalid_candidate(plan):
    s = choose(
        plan,
        target_id="module.intent_router",
        case_kind="module_event",
        dimension="intent_parameter_validation_failed",
    )
    c = candidate(
        s,
        {
            "operation": "observe_module_event",
            "stimulus": {
                "action": "validate_candidate",
                "intent": "query_user",
                "parameters": {"user_id": 3},
            },
        },
        {
            "checks": [
                {
                    "op": "subset",
                    "actual": "trace.event_types",
                    "expected": ["intent_parameter_validation_failed"],
                }
            ]
        },
    )
    c["preconditions"] = [{"kind": "controlled_module_harness", "isolated": True}]
    assert validate_candidate(c, s, plan)
    c["input"]["stimulus"]["parameters"]["user_id"] = 0
    assert validate_candidate(c, s, plan) == []


def test_fixture_branch_and_sequence_reject_impossible_setup(plan):
    from dataset_builder.full_comparison.validation import _fixture_branch

    doc = plan.documents["tool.prepare_resource"]
    c = {
        "preconditions": [
            {"kind": "fixture_setup", "fresh_instance": True, "records": {}}
        ]
    }
    args = {
        "resource_type": "room",
        "environment": "production",
        "count": 1001,
        "request_id": "case-x",
    }
    with pytest.raises(ValueError):
        _fixture_branch(c, args, doc, "OK")
    args.update(environment="test", count=1)
    with pytest.raises(ValueError):
        _fixture_branch(c, args, doc, "CONFLICT")
    assert _fixture_branch(c, args, doc, "OK") is None
    c["preconditions"] = [{}]
    with pytest.raises(ValueError):
        _fixture_branch(c, args, doc, "OK")


def test_complete_chain_cannot_claim_clarification(plan):
    s = next(
        s
        for s in plan.specs
        if s["case_kind"] == "chain_case"
        and s["dimension"] == "intent.query_user:early_stop"
    )
    c = candidate(
        s,
        {
            "user_input": "查询用户 ID 127 的信息。",
            "intent_parameters": {"user_id": 127},
        },
        {"terminal_status": "NEED_CLARIFICATION"},
    )
    assert validate_candidate(c, s, plan)


def test_nested_parameters_resolve_defs_and_grounding(plan):
    from dataset_builder.full_comparison.validation import _grounded

    assert _grounded("礼物 5 数量 3", {"gift_id": 5, "num": 3})
    s = choose(
        plan,
        target_id="intent.add_backpack_gift",
        case_kind="parameter",
        parameter="gift_nums",
        dimension="valid",
    )
    c = candidate(
        s,
        {
            "operation": "validate_arguments",
            "parameter": "gift_nums",
            "dimension": "valid",
            "arguments": {"gift_nums": [{"gift_id": 5, "num": 3}]},
        },
        {
            "arguments_schema_valid": True,
            "checks": [
                {"op": "schema_valid", "actual": "input.arguments", "expected": True}
            ],
        },
    )
    assert validate_candidate(c, s, plan) == []


def test_cardinality_accepts_either_declared_group(plan):
    s = choose(
        plan,
        target_id="tool.add_gift_to_backpack",
        case_kind="tool_rule",
        dimension="selection_cardinality",
    )
    args = {
        "gift_id": 10,
        "gift_ids": [11],
        "gift_nums": None,
        "user_id": 20,
        "user_ids": None,
        "num": None,
        "duration_days": None,
    }
    c = candidate(
        s,
        {
            "operation": "validate_selection_modes",
            "modes": ["gift_id", "gift_ids", "gift_nums"],
            "arguments": args,
        },
        {
            "business_arguments_valid": False,
            "checks": [
                {
                    "op": "equals",
                    "actual": "argument_validator.accepted",
                    "expected": False,
                }
            ],
        },
    )
    assert validate_candidate(c, s, plan) == []


def test_gift_single_absent_is_empty_batch_absent_is_not_found(plan):
    from dataset_builder.full_comparison.validation import _fixture_branch

    doc = plan.documents["tool.query_gift_info"]
    c = {
        "preconditions": [
            {"kind": "fixture_setup", "fresh_instance": True, "records": {"gifts": []}}
        ]
    }
    args = {"gift_id": 5, "gift_ids": None, "gift_name": None, "limit": None}
    assert _fixture_branch(c, args, doc, "EMPTY") is None
    with pytest.raises(ValueError):
        _fixture_branch(c, args, doc, "NOT_FOUND")
    args.update(gift_id=None, gift_ids=[5])
    assert _fixture_branch(c, args, doc, "NOT_FOUND") is None


def test_default_num_cannot_be_overridden_by_gift_quantities(plan):
    s = choose(
        plan,
        target_id="tool.add_gift_to_backpack",
        case_kind="tool_rule",
        dimension="default_num",
    )
    c = candidate(
        s,
        {
            "operation": "invoke_tool",
            "tool_name": "add_gift_to_backpack",
            "arguments": {
                "user_id": 1,
                "user_ids": None,
                "gift_id": None,
                "gift_ids": None,
                "gift_nums": [{"gift_id": 2, "num": 5}],
                "num": None,
                "duration_days": None,
            },
        },
        {
            "checks": [
                {
                    "op": "equals",
                    "actual": "tool_result.data.grants[0].num",
                    "expected": 1,
                }
            ]
        },
    )
    c["preconditions"] = [
        {
            "kind": "fixture_setup",
            "fresh_instance": True,
            "records": {"users": [{"user_id": 1}], "gifts": [{"gift_id": 2}]},
            "owner_authorized_attempts": 1,
        }
    ]
    assert validate_candidate(c, s, plan)
