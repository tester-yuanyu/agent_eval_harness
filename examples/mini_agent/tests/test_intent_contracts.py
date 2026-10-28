from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from minimal_agent.contracts.agent import IntentResult
from minimal_agent.contracts.intent_parameters import QueryUserInfoArguments
from minimal_agent.contracts.intents import (
    AtLeastOneFieldGroup,
    ExactlyOneFieldGroup,
    IntegerStringNormalizer,
    IntentContractError,
    IntentDefinition,
    IntentRegistry,
    MutuallyExclusiveFields,
    ReadIntentPolicy,
    RequiredFields,
    TrimStringNormalizer,
    UnsupportedIntentPolicy,
    WriteIntentPolicy,
    build_default_intent_registry,
)


class ExampleParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    resource_type: str | None = None
    environment: str | None = None
    user_id: int | None = None
    room_id: int | None = None


def test_default_registry_contains_exactly_the_formal_intents() -> None:
    assert build_default_intent_registry().intents == {
        "query_information",
        "prepare_resource",
        "query_user",
        "query_gift",
        "query_pool",
        "add_backpack_gift",
        "unsupported",
    }


def candidate(
    intent: str,
    parameters: dict[str, Any],
    *,
    status: str = "READY",
) -> IntentResult:
    action = {
        "READY": "CALL_TOOL",
        "NEED_CLARIFICATION": "ASK_USER",
        "NEED_CONFIRMATION": "ASK_CONFIRMATION",
        "REJECTED": "REJECT",
    }[status]
    return IntentResult.model_validate(
        {
            "intent": intent,
            "status": status,
            "next_action": action,
            "parameters": parameters,
            "missing_parameters": (
                ["candidate_missing"] if status == "NEED_CLARIFICATION" else []
            ),
            "reason": "candidate reason",
        }
    )


def definition(
    *,
    intent: str = "query_information",
    constraints: tuple[object, ...] = (),
    normalizers: tuple[object, ...] = (),
    policy: object | None = None,
    execution_mode: str = "read",
) -> IntentDefinition:
    return IntentDefinition(
        intent=intent,
        contract_version="intent-contract-v1",
        parameters_model=ExampleParameters,
        normalizers=normalizers,
        semantic_constraints=constraints,
        completion_policy=policy or ReadIntentPolicy(),
        execution_mode=execution_mode,
    )


def test_registry_rejects_duplicate_intent_definition() -> None:
    registry = IntentRegistry()
    registry.register(definition())

    with pytest.raises(
        IntentContractError,
        match="already registered.*query_information",
    ):
        registry.register(definition())


def test_registry_rejects_unknown_intent() -> None:
    registry = IntentRegistry()

    with pytest.raises(IntentContractError, match="not registered.*query_user"):
        registry.validate("query user", candidate("query_user", {"user_id": 1}))


def test_registry_rejects_definition_with_contradictory_configuration() -> None:
    registry = IntentRegistry()
    contradictory = definition(
        policy=WriteIntentPolicy(),
        execution_mode="read",
    )

    with pytest.raises(IntentContractError, match="completion policy.*read"):
        registry.register(contradictory)


def test_integer_string_normalizer_converts_ascii_digits_only() -> None:
    registry = IntentRegistry()
    registry.register(
        definition(
            normalizers=(
                TrimStringNormalizer(("user_id",)),
                IntegerStringNormalizer(("user_id",)),
            ),
            constraints=(RequiredFields(("user_id",)),),
        )
    )

    result = registry.validate(
        "query user",
        candidate("query_information", {"user_id": " 9075333 "}),
    )

    assert result.parameters == {"user_id": 9075333}
    assert result.status == "READY"


@pytest.mark.parametrize("value", ["-7", "9.5", True, "９０７５３３３"])
def test_integer_string_normalizer_rejects_signed_decimal_boolean_and_unicode_digits(
    value: object,
) -> None:
    registry = IntentRegistry()
    registry.register(
        definition(
            normalizers=(IntegerStringNormalizer(("user_id",)),),
            constraints=(RequiredFields(("user_id",)),),
        )
    )

    result = registry.validate(
        "query user",
        candidate("query_information", {"user_id": value}),
    )

    assert result.status == "NEED_CLARIFICATION"
    assert result.parameters == {}
    assert result.missing_parameters == ["user_id"]


def test_trim_string_normalizer_trims_declared_fields_only() -> None:
    registry = IntentRegistry()
    registry.register(
        definition(
            normalizers=(TrimStringNormalizer(("resource_type",)),),
            constraints=(RequiredFields(("resource_type", "environment")),),
        )
    )

    result = registry.validate(
        "query",
        candidate(
            "query_information",
            {"resource_type": " fixture ", "environment": " test "},
        ),
    )

    assert result.parameters == {
        "resource_type": "fixture",
        "environment": " test ",
    }


def test_required_fields_reports_canonical_missing_names() -> None:
    registry = IntentRegistry()
    registry.register(
        definition(
            constraints=(RequiredFields(("resource_type", "environment")),),
        )
    )

    result = registry.validate(
        "query",
        candidate("query_information", {"resource_type": "fixture"}),
    )

    assert result.status == "NEED_CLARIFICATION"
    assert result.next_action == "ASK_USER"
    assert result.missing_parameters == ["environment"]


def test_at_least_one_and_exactly_one_groups_are_reusable() -> None:
    at_least_registry = IntentRegistry()
    at_least_registry.register(
        definition(
            constraints=(
                AtLeastOneFieldGroup(
                    ("user_id", "room_id"),
                    missing_name="user_id_or_room_id",
                ),
            ),
        )
    )
    exactly_registry = IntentRegistry()
    exactly_registry.register(
        definition(
            constraints=(
                ExactlyOneFieldGroup(
                    ("user_id", "room_id"),
                    missing_name="single_user_query_condition",
                ),
            ),
        )
    )

    missing = at_least_registry.validate(
        "query",
        candidate("query_information", {}),
    )
    conflict = exactly_registry.validate(
        "query",
        candidate("query_information", {"user_id": 1, "room_id": 2}),
    )

    assert missing.missing_parameters == ["user_id_or_room_id"]
    assert conflict.missing_parameters == ["single_user_query_condition"]


def test_mutually_exclusive_fields_reports_conflicting_fields() -> None:
    registry = IntentRegistry()
    registry.register(
        definition(
            constraints=(
                MutuallyExclusiveFields(
                    ("user_id", "room_id"),
                    missing_name="single_lookup_mode",
                ),
            ),
        )
    )

    result = registry.validate(
        "query",
        candidate("query_information", {"user_id": 1, "room_id": 2}),
    )

    assert result.status == "NEED_CLARIFICATION"
    assert result.missing_parameters == ["single_lookup_mode"]


def test_read_write_and_unsupported_policies_choose_canonical_state() -> None:
    read_registry = IntentRegistry()
    read_registry.register(definition())
    write_registry = IntentRegistry()
    write_registry.register(
        definition(
            intent="prepare_resource",
            policy=WriteIntentPolicy(),
            execution_mode="write",
        )
    )
    unsupported_registry = IntentRegistry()
    unsupported_registry.register(
        definition(
            intent="unsupported",
            policy=UnsupportedIntentPolicy(),
            execution_mode="unsupported",
        )
    )

    read_result = read_registry.validate(
        "query",
        candidate("query_information", {}),
    )
    write_result = write_registry.validate(
        "prepare",
        candidate("prepare_resource", {}),
    )
    unsupported_result = unsupported_registry.validate(
        "unsupported",
        candidate("unsupported", {}, status="REJECTED"),
    )

    assert (read_result.status, read_result.next_action) == ("READY", "CALL_TOOL")
    assert (write_result.status, write_result.next_action) == (
        "NEED_CONFIRMATION",
        "ASK_CONFIRMATION",
    )
    assert (unsupported_result.status, unsupported_result.next_action) == (
        "REJECTED",
        "REJECT",
    )


PUBLIC_INTENTS = {
    "query_information",
    "prepare_resource",
    "query_user",
    "query_gift",
    "add_backpack_gift",
    "query_pool",
    "unsupported",
}


def test_default_registry_contains_every_public_intent_literal() -> None:
    assert build_default_intent_registry().intents == PUBLIC_INTENTS


def test_each_default_definition_has_a_nonempty_contract_version() -> None:
    registry = build_default_intent_registry()

    assert all(registry.get(name).contract_version for name in registry.intents)


def test_default_intents_use_expected_execution_modes_and_policies() -> None:
    registry = build_default_intent_registry()

    for intent in {
        "query_information",
        "prepare_resource",
        "query_user",
        "query_gift",
        "query_pool",
    }:
        definition = registry.get(intent)
        assert definition.execution_mode == "read"
        assert isinstance(definition.completion_policy, ReadIntentPolicy)
    for intent in {"add_backpack_gift"}:
        definition = registry.get(intent)
        assert definition.execution_mode == "write"
        assert isinstance(definition.completion_policy, WriteIntentPolicy)
    assert isinstance(
        registry.get("unsupported").completion_policy,
        UnsupportedIntentPolicy,
    )


def test_query_user_accepts_positive_ids_valid_email_and_phone() -> None:
    result = build_default_intent_registry().validate(
        "query user",
        candidate(
            "query_user",
            {
                "user_id": "10001",
                "room_id": 20001,
                "email": "person@example.com",
                "phone": "13800000001",
            },
        ),
    )

    assert result.status == "READY"
    assert result.parameters["user_id"] == 10001


@pytest.mark.parametrize(
    "email",
    ["example.com", "@example.com", "a@", "a@@example.com"],
)
def test_query_user_rejects_invalid_email_shapes(email: str) -> None:
    result = build_default_intent_registry().validate(
        "query user",
        candidate("query_user", {"email": email}),
    )

    assert result.status == "NEED_CLARIFICATION"
    assert result.parameters == {}
    assert "email" in result.missing_parameters


@pytest.mark.parametrize(
    "phone",
    ["1380000000", "138000000001", "1380000000a", "138-0000-001", 13800000001],
)
def test_query_user_rejects_invalid_phone_values(phone: object) -> None:
    result = build_default_intent_registry().validate(
        "query user",
        candidate("query_user", {"phone": phone}),
    )

    assert result.status == "NEED_CLARIFICATION"
    assert result.parameters == {}
    assert "phone" in result.missing_parameters


def test_query_user_preserves_valid_phone_when_user_id_is_invalid() -> None:
    result = build_default_intent_registry().validate(
        "query user",
        candidate("query_user", {"user_id": "-1", "phone": "13800000001"}),
    )

    assert result.status == "NEED_CLARIFICATION"
    assert result.parameters == {"phone": "13800000001"}
    assert result.missing_parameters == ["user_id"]


def test_query_user_requires_at_least_one_condition_in_intent_contract() -> None:
    result = build_default_intent_registry().validate(
        "query user",
        candidate("query_user", {}),
    )

    assert result.status == "NEED_CLARIFICATION"
    assert result.missing_parameters == [
        "user_id_or_room_id_or_email_or_phone"
    ]


@pytest.mark.parametrize(
    ("intent", "parameters", "missing_name"),
    [
        (
            "query_gift",
            {"gift_id": 1, "gift_name": "rose"},
            "single_gift_query_mode",
        ),
        ("query_pool", {"gift_id": 1, "pool_id": 2}, "single_pool_query_mode"),
    ],
)
def test_query_gift_and_pool_enforce_exactly_one_lookup_mode(
    intent: str,
    parameters: dict[str, object],
    missing_name: str,
) -> None:
    result = build_default_intent_registry().validate(
        "query",
        candidate(intent, parameters),
    )

    assert result.status == "NEED_CLARIFICATION"
    assert result.missing_parameters == [missing_name]


def test_write_intents_require_environment() -> None:
    result = build_default_intent_registry().validate(
        "write",
        candidate(
            "add_backpack_gift",
            {"gift_id": 300101, "user_id": 10001, "num": 1},
        ),
    )

    assert result.status == "NEED_CLARIFICATION"
    assert "environment" in result.missing_parameters


def test_intent_and_tool_models_share_query_user_field_constraints() -> None:
    intent_model = build_default_intent_registry().get("query_user").parameters_model
    valid = {
        "user_id": 10001,
        "room_id": None,
        "email": "person@example.com",
        "phone": "13800000001",
    }

    assert intent_model.model_validate(valid).phone == "13800000001"
    assert QueryUserInfoArguments.model_validate(valid).phone == "13800000001"

    for invalid in ({**valid, "email": "a@@b"}, {**valid, "phone": "123"}):
        with pytest.raises(ValidationError):
            intent_model.model_validate(invalid)
        with pytest.raises(ValidationError):
            QueryUserInfoArguments.model_validate(invalid)
