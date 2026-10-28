from typing import Any

import pytest

from minimal_agent.contracts.intent_parameters import QueryUserInfoArguments
from minimal_agent.contracts.intents import (
    QUERY_USER_CONTRACT_VERSION,
    QUERY_USER_MISSING_PARAMETERS,
    build_default_intent_registry,
)
from minimal_agent.runtime.intent_router import IntentRouter
from tests.support.model_client import DeterministicModelClient


def candidate(parameters: dict[str, Any]) -> dict[str, object]:
    return {
        "intent": "query_user",
        "status": "READY",
        "next_action": "CALL_TOOL",
        "parameters": parameters,
        "missing_parameters": [],
        "reason": "模型候选认为参数完整。",
    }


def test_query_user_parameter_contract_is_formal_not_shadow_owned() -> None:
    parsed = QueryUserInfoArguments(
        user_id=10001,
        room_id=None,
        email=None,
        phone=None,
    )

    assert parsed.user_id == 10001


def route(user_input: str, parameters: dict[str, Any]):
    return IntentRouter(
        DeterministicModelClient([candidate(parameters)])
    ).run_intent_only(
        user_input,
    )


def test_query_user_public_contract_freezes_missing_parameter_vocabulary() -> None:
    definition = build_default_intent_registry().get("query_user")

    assert QUERY_USER_CONTRACT_VERSION == "query-user-intent-contract-v3"
    assert definition.contract_version == QUERY_USER_CONTRACT_VERSION
    assert QUERY_USER_MISSING_PARAMETERS == frozenset(
        {
            "user_id",
            "room_id",
            "email",
            "phone",
            "user_id_or_room_id",
            "user_id_or_room_id_or_email_or_phone",
            "single_user_id",
            "single_room_id",
            "single_email",
            "single_phone",
            "single_user_query_condition",
        }
    )


def test_query_user_without_any_condition_uses_public_composite_name() -> None:
    result = route("请查询用户信息", {})

    assert result.status == "NEED_CLARIFICATION"
    assert result.missing_parameters == [
        "user_id_or_room_id_or_email_or_phone"
    ]


@pytest.mark.parametrize(
    "user_input",
    [
        "查询 9075333 的用户信息",
        "查询 9075338，我再说一遍，就是 9075338 的用户信息",
    ],
)
def test_bare_positive_integer_requires_user_or_room_clarification(
    user_input: str,
) -> None:
    result = route(user_input, {"user_id": "9075333"})

    assert result.status == "NEED_CLARIFICATION"
    assert result.next_action == "ASK_USER"
    assert result.parameters == {}
    assert result.missing_parameters == ["user_id_or_room_id"]


@pytest.mark.parametrize(
    ("user_input", "parameters", "expected"),
    [
        ("查询用户 9075335 的信息", {"user_id": "9075335"}, {"user_id": 9075335}),
        ("查询直播间 8800125 对应的用户", {"room_id": "8800125"}, {"room_id": 8800125}),
    ],
)
def test_context_can_resolve_positive_integer_query_field(
    user_input: str,
    parameters: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    result = route(user_input, parameters)

    assert result.status == "READY"
    assert result.parameters == expected


def test_explicit_user_id_string_is_normalized_to_integer() -> None:
    result = route("查询用户 ID 9075333", {"user_id": "9075333"})

    assert result.status == "READY"
    assert result.parameters == {"user_id": 9075333}


def test_bare_eleven_digit_number_remains_phone() -> None:
    result = route("查询 13800000001", {"phone": "13800000001"})

    assert result.status == "READY"
    assert result.parameters == {"phone": "13800000001"}


def test_zero_user_id_requests_clarification() -> None:
    result = route("查询用户 ID 0", {"user_id": 0})

    assert result.status == "NEED_CLARIFICATION"
    assert result.next_action == "ASK_USER"
    assert result.parameters == {}
    assert "user_id" in result.missing_parameters


def test_and_query_normalizes_id_and_preserves_phone() -> None:
    result = route(
        "查询用户 ID 9075333 且手机号为 13800000001",
        {"user_id": "9075333", "phone": "13800000001"},
    )

    assert result.status == "READY"
    assert result.parameters == {"user_id": 9075333, "phone": "13800000001"}


def test_or_query_is_not_converted_to_and() -> None:
    result = route(
        "查询用户 ID 9075333 或手机号 13800000001",
        {"user_id": "9075333", "phone": "13800000001"},
    )

    assert result.status == "NEED_CLARIFICATION"
    assert result.next_action == "ASK_USER"
    assert result.parameters == {}
    assert result.missing_parameters == ["single_user_query_condition"]
    assert "不支持" in result.reason
    assert "一次" in result.reason


def test_explicit_batch_query_requests_single_entity() -> None:
    result = route(
        "分别查询用户 ID 9075333 和房间 ID 8001 对应的用户",
        {"user_id": "9075333", "room_id": "8001"},
    )

    assert result.status == "NEED_CLARIFICATION"
    assert result.parameters == {}
    assert result.missing_parameters == ["single_user_query_condition"]


def test_two_different_fields_without_or_remain_and_query() -> None:
    result = route(
        "查询用户 ID 9075333，手机号 13800000001",
        {"user_id": "9075333", "phone": "13800000001"},
    )

    assert result.status == "READY"


def test_or_word_without_two_extracted_conditions_does_not_false_positive() -> None:
    result = route(
        "手机号或者联系方式是 13800000001",
        {"phone": "13800000001"},
    )

    assert result.status == "READY"
    assert "single_user_query_condition" not in result.missing_parameters


@pytest.mark.parametrize(
    "parameters",
    [{"email": "a@@example.com"}, {"phone": "1380000000a"}],
)
def test_invalid_email_and_phone_candidates_request_correction(
    parameters: dict[str, Any],
) -> None:
    result = route("查询用户", parameters)

    assert result.status == "NEED_CLARIFICATION"
    assert result.parameters == {}


def test_candidate_status_is_recomputed_from_contract() -> None:
    response = candidate({"user_id": 10001})
    response.update(
        status="NEED_CLARIFICATION",
        next_action="ASK_USER",
        missing_parameters=["email"],
    )

    result = IntentRouter(DeterministicModelClient([response])).run_intent_only(
        "查询用户"
    )

    assert result.status == "READY"
    assert result.next_action == "CALL_TOOL"
    assert result.missing_parameters == []


@pytest.mark.parametrize(
    ("user_input", "parameters", "expected_missing"),
    [
        ("查询用户 ID 为 0 的用户信息。", {}, ["user_id"]),
        ("用户编号是 -7，查一下他的资料。", {}, ["user_id"]),
        ("请查直播间号 0 对应的用户。", {"room_id": 0}, ["room_id"]),
        ("查询邮箱 example.com 对应的用户信息。", {}, ["email"]),
        ("查询手机号 1500000020 的用户信息。", {"phone": "1500000020"}, ["phone"]),
        ("请查手机号 15000A00200 对应的用户。", {}, ["phone"]),
        ("请按手机号查询用户，号码稍后再说。", {}, ["phone"]),
    ],
)
def test_explicit_invalid_or_missing_field_requests_that_specific_field(
    user_input: str,
    parameters: dict[str, Any],
    expected_missing: list[str],
) -> None:
    result = route(user_input, parameters)

    assert result.status == "NEED_CLARIFICATION"
    assert result.parameters == {}
    assert result.missing_parameters == expected_missing


@pytest.mark.parametrize(
    "user_input",
    [
        "麻烦查一下用户资料。",
        "帮我查一下他的用户信息。",
    ],
)
def test_missing_all_query_conditions_uses_public_composite_name(
    user_input: str,
) -> None:
    result = route(user_input, {})

    assert result.missing_parameters == [
        "user_id_or_room_id_or_email_or_phone"
    ]


@pytest.mark.parametrize(
    ("user_input", "candidate_parameters"),
    [
        ("查询 9075333 的用户信息。", {"user_id": 9075333}),
        (
            "查询 9075338，我再说一遍，就是 9075338 的用户信息。",
            {"user_id": 9075338},
        ),
    ],
)
def test_bare_positive_integer_remains_ambiguous_between_user_and_room(
    user_input: str,
    candidate_parameters: dict[str, Any],
) -> None:
    result = route(user_input, candidate_parameters)

    assert result.status == "NEED_CLARIFICATION"
    assert result.parameters == {}
    assert result.missing_parameters == ["user_id_or_room_id"]


def test_user_word_before_number_is_sufficient_user_id_context() -> None:
    result = route("查询用户 9075335 的信息。", {"user_id": 9075335})

    assert result.status == "READY"
    assert result.parameters == {"user_id": 9075335}


@pytest.mark.parametrize(
    ("user_input", "parameters", "expected_missing"),
    [
        (
            "查询用户 ID 9075333，用户 ID 9075334。",
            {},
            ["single_user_id"],
        ),
        (
            "查询用户 ID 9075340、9075341 和 9075342 的信息。",
            {},
            ["single_user_id"],
        ),
        (
            "把直播间 ID 8800130 和 8800131 对应的用户都查出来。",
            {},
            ["single_room_id"],
        ),
        (
            "批量查询手机号 15000000204、15000000205 对应的用户。",
            {"phone": "15000000204、15000000205"},
            ["single_phone"],
        ),
    ],
)
def test_multiple_values_for_one_field_request_a_single_value(
    user_input: str,
    parameters: dict[str, Any],
    expected_missing: list[str],
) -> None:
    result = route(user_input, parameters)

    assert result.status == "NEED_CLARIFICATION"
    assert result.parameters == {}
    assert result.missing_parameters == expected_missing


@pytest.mark.parametrize(
    ("user_input", "parameters", "expected"),
    [
        (
            "查询用户 ID 9075333，不对，改成 9075334。",
            {"user_id": 9075334},
            {"user_id": 9075334},
        ),
        (
            "不要查用户 ID 9075333，查 9075337。",
            {"user_id": 9075337},
            {"user_id": 9075337},
        ),
        (
            "用户 ID 9075333 错了，更正为 9075336。",
            {"user_id": 9075336},
            {"user_id": 9075336},
        ),
        (
            "不是用户 ID 9075333，而是 9075339。",
            {"user_id": 9075339},
            {"user_id": 9075339},
        ),
    ],
)
def test_explicit_same_field_replacement_uses_final_value(
    user_input: str,
    parameters: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    result = route(user_input, parameters)

    assert result.status == "READY"
    assert result.next_action == "CALL_TOOL"
    assert result.parameters == expected
    assert result.missing_parameters == []


def test_explicit_replacement_with_multiple_final_values_still_clarifies() -> None:
    result = route(
        "用户 ID 9075333 不对，改成 9075334 和 9075335。",
        {"user_id": 9075335},
    )

    assert result.status == "NEED_CLARIFICATION"
    assert result.parameters == {}
    assert result.missing_parameters == ["single_user_id"]


def test_explicit_multi_user_query_is_rejected_when_candidate_omits_fields(
) -> None:
    result = route(
        "分别查询用户 ID 9075333 和手机号 15000000200 对应的两个用户。",
        {},
    )

    assert result.status == "NEED_CLARIFICATION"
    assert result.parameters == {}
    assert result.missing_parameters == ["single_user_query_condition"]
    assert "一次" in result.reason


def test_or_query_is_rejected_even_when_candidate_omits_fields() -> None:
    result = route(
        "查询用户 ID 9075343 或者邮箱 alternate@example.test 对应的用户。",
        {},
    )

    assert result.status == "NEED_CLARIFICATION"
    assert result.parameters == {}
    assert result.missing_parameters == ["single_user_query_condition"]
    assert "OR" in result.reason
