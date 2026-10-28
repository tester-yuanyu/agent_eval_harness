"""Deterministic single-turn intent cases grounded in the selected contracts."""

from eval_framework.schemas import EvalCase

from .models import CompiledCase

# Author-owned synthetic inputs, not observed Agent responses or production data.
EXAMPLES = {
    "query_user": (
        "查询用户 ID 10001 的信息。",
        {"user_id": 10001},
        "请查询手机号 bad-phone 对应的用户。",
        {},
        ["phone"],
        "请查询用户信息。",
        ["user_id_or_room_id_or_email_or_phone"],
    ),
    "query_gift": (
        "查询礼物 ID 20001 的信息。",
        {"gift_id": 20001},
        "查询礼物 ID 为 0 的信息。",
        {},
        ["gift_id"],
        "请查询礼物信息。",
        ["single_gift_query_mode"],
    ),
    "query_pool": (
        "查询奖池 ID 30001 的配置。",
        {"pool_id": 30001},
        "查询奖池 ID 为 0 的配置。",
        {},
        ["pool_id"],
        "请查询奖池配置。",
        ["single_pool_query_mode"],
    ),
    "query_information": (
        "查询 test 环境的账号资源。",
        {"resource_type": "账号", "environment": "test"},
        "查询账号资源，environment 是空字符串。",
        {"resource_type": "账号"},
        ["environment"],
        "请查询账号资源。",
        ["environment"],
    ),
    "prepare_resource": (
        "在 test 环境准备 2 个账号资源，request_id 为 fixture-request-001。",
        {
            "resource_type": "账号",
            "environment": "test",
            "count": 2,
            "request_id": "fixture-request-001",
        },
        "在 test 环境准备 0 个账号资源，request_id 为 fixture-request-001。",
        {
            "resource_type": "账号",
            "environment": "test",
            "request_id": "fixture-request-001",
        },
        ["count"],
        "准备 2 个账号资源，request_id 为 fixture-request-001。",
        ["environment"],
    ),
    "add_backpack_gift": (
        "在 test 环境给用户 10001 发放礼物 20001，数量 2，有效期 7 天。",
        {
            "user_id": 10001,
            "gift_id": 20001,
            "num": 2,
            "duration_days": 7,
            "environment": "test",
        },
        "在 test 环境给用户 10001 发放礼物 20001，数量 0，有效期 7 天。",
        {"user_id": 10001, "gift_id": 20001, "duration_days": 7, "environment": "test"},
        ["num"],
        "给用户 10001 发放礼物 20001，数量 2，有效期 7 天。",
        ["environment"],
    ),
    "unsupported": (
        "请预订明天从北京到上海的机票。",
        {},
        "请为我创建一幅水彩画。",
        {},
        [],
        "请播放一首古典音乐。",
        [],
    ),
}


def intent_example(inv, ident, dimension):
    name = ident.removeprefix("intent.")
    d = inv.artifacts[ident]["payload"]
    text, params, bad, partial, missing_bad, missing_text, missing_names = EXAMPLES[
        name
    ]
    params = dict(params)
    decision = d["decision_rules"]["complete"]
    missing = []
    if dimension == "invalid":
        text, params, missing = bad, dict(partial), missing_bad
        decision = d["decision_rules"]["incomplete"]
    elif dimension == "missing":
        text = missing_text
        missing = missing_names
        decision = d["decision_rules"]["incomplete"]
        if name in {"query_information", "prepare_resource", "add_backpack_gift"}:
            params.pop("environment", None)
        else:
            params = {}
    elif dimension == "expression_variant":
        text = "麻烦帮我处理一下：" + text
    return text, {
        "intent": name,
        **decision,
        "parameters": params,
        "missing_parameters": missing,
        "reason": "依据绑定能力契约生成，待人工复核。",
    }


def execution(text):
    return {
        "user_input": text,
        "user_responses": [],
        "tool_profile": "full_fixture",
        "allowed_tools": [],
        "fault_injection": {},
        "max_steps": 4,
        "timeout_seconds": 30.0,
    }


def assertions(names):
    return {
        "checks": [
            {"name": n, "weight": 1, "critical": True, "config": {}} for n in names
        ]
    }


def compile_intent_cases(inv, slots):
    cases = []
    for s in slots:
        if s.case_kind != "intent_case":
            continue
        text, expected = intent_example(inv, s.target_id, s.dimension)
        payload = EvalCase.model_validate(
            {
                "schema_version": "1.0",
                "case_id": "I-" + s.slot_id,
                "task_id": s.target_id,
                "scenario_type": {
                    "missing": "missing_parameter",
                    "invalid": "invalid_parameter",
                    "expression_variant": "expression_variant",
                }.get(s.dimension, "normal"),
                "test_scope": "module",
                "target": "intent_router",
                "execution": execution(text),
                "oracle": {
                    "expected_module_output": expected,
                    "evaluation": assertions(
                        [
                            "intent_parameters_schema_valid",
                            "intent_match",
                            "status_match",
                            "next_action_match",
                            "params_match",
                            "missing_params_match",
                        ]
                    ),
                },
                "labels": [
                    "slot:" + s.slot_id,
                    "source:" + s.target_id,
                    "test_fixture",
                    "needs_human_review",
                ],
            }
        ).model_dump(mode="json")
        cases.append(
            CompiledCase(
                slot_id=s.slot_id,
                dataset_format="eval_case",
                payload=payload,
                execution_readiness="not_run",
                coverage_mode="direct",
            )
        )
    return cases
