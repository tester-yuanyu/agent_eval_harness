"""Contracts for the isolated example fixture, not production backend claims."""

from minimal_agent.contracts.intent_parameters import (
    AddGiftToBackpackArguments,
    NonEmptyString,
    PositiveInt,
    QueryGiftInfoArguments,
    QueryPoolConfigArguments,
    QueryUserInfoArguments,
    StrictToolArguments,
)
from minimal_agent.contracts.tools import ToolContract

from .results import ROW_MODELS


class QueryInformationArguments(StrictToolArguments):
    resource_type: NonEmptyString
    environment: NonEmptyString


class PrepareResourceArguments(QueryInformationArguments):
    count: PositiveInt
    request_id: NonEmptyString


def _result(field: str, kind: str = "array") -> dict:
    row_schema = ROW_MODELS[field].model_json_schema()
    shape = (
        {"type": "array", "items": row_schema, "minItems": 1}
        if kind == "array"
        else row_schema
    )
    return {
        "terminal_status": "success",
        "data_schema": {
            "type": "object",
            "properties": {field: shape},
            "required": [field],
            "additionalProperties": False,
        },
    }


def _contract(
    name,
    model,
    field,
    rules,
    *,
    write=False,
    confirmation=False,
    kind="array",
    errors=(),
    idempotency=None,
):
    results = {
        "OK": _result(field, kind),
        **{
            code: {
                "terminal_status": "business_failure",
                "data_schema": {"type": "object", "additionalProperties": False},
            }
            for code in errors
        },
    }
    if not write:
        results["EMPTY"] = {
            "terminal_status": "success",
            "data_schema": {
                "type": "object",
                "properties": {
                    field: {"type": "null"}
                    if kind == "object"
                    else {
                        "type": "array",
                        "maxItems": 0,
                    }
                },
                "required": [field],
                "additionalProperties": False,
            },
        }
    return ToolContract(
        name=name,
        version=f"{name.replace('_', '-')}-example-fixture-v1",
        description=(
            f"Execute {name} against an isolated in-memory example fixture. "
            "No production backend or real business data is connected."
        ),
        arguments_model=model,
        tool_type="write" if write else "read",
        parameter_rules=rules,
        permission_requirements=(
            "REGISTERED_TOOL_AND_RUN_ALLOW_LIST",
            *(("EXTERNAL_FIXTURE_APPROVAL",) if confirmation else ()),
        ),
        requires_confirmation=confirmation,
        risk_level="low",
        idempotency_rules=idempotency
        or {
            "mode": "READ_ONLY" if not write else "NOT_IDEMPOTENT",
        },
        side_effects=(f"isolated_fixture.{field}",) if write else (),
        result_contracts=results,
        empty_result_behavior=(
            "EMPTY_SUCCESS_WITH_NULL_USER_OR_EMPTY_LIST"
            if not write
            else "NOT_APPLICABLE"
        ),
        partial_success_behavior="UNSUPPORTED_ALL_OR_NOTHING",
        trace_event_types=(),
        implementation_profile="test_fixture",
        simulation_capabilities=(
            "success",
            *(("empty_result",) if not write else ()),
            *(("business_failure",) if errors else ()),
        ),
        observation_interfaces=("agent_result.tool_calls", "agent_result.events"),
    )


CONTRACTS = (
    _contract(
        "query_information",
        QueryInformationArguments,
        "resources",
        {
            "required_fields": ["resource_type", "environment"],
            "environment": "test only",
            "matching": "EXACT",
        },
        errors=("ENVIRONMENT_UNSUPPORTED",),
    ),
    _contract(
        "prepare_resource",
        PrepareResourceArguments,
        "resources",
        {
            "required_fields": ["resource_type", "environment", "count", "request_id"],
            "environment": "test only",
            "maximum_fixture_count": 1000,
            "request_id_conflict": "CONFLICT_WITHOUT_MUTATION",
            "intent_policy": "CURRENT_INTENT_USES_READ_POLICY",
        },
        write=True,
        errors=("ENVIRONMENT_UNSUPPORTED", "LIMIT_EXCEEDED", "CONFLICT"),
        idempotency={
            "mode": "REQUEST_ID_WITHIN_FIXTURE_INSTANCE",
            "same_arguments": "RETURN_ORIGINAL_RESOURCES",
            "different_arguments": "CONFLICT",
        },
    ),
    _contract(
        "query_user_info",
        QueryUserInfoArguments,
        "user",
        {
            "condition_cardinality": "AT_LEAST_ONE",
            "multiple_conditions": "AND",
            "batch_queries": "UNSUPPORTED",
            "matching": "EXACT",
            "accepted_fields": ["user_id", "room_id", "email", "phone"],
        },
        kind="object",
    ),
    _contract(
        "query_gift_info",
        QueryGiftInfoArguments,
        "gifts",
        {
            "query_modes": ["gift_id", "gift_ids", "gift_name"],
            "query_mode_cardinality": "EXACTLY_ONE",
            "gift_name_matching": "CASE_INSENSITIVE_SUBSTRING",
            "gift_ids": "ALL_MUST_EXIST; UNIQUE_SORTED_RESULTS",
            "limit": "APPLIED_AFTER_MATCHING",
        },
        errors=("NOT_FOUND",),
    ),
    _contract(
        "query_pool_config",
        QueryPoolConfigArguments,
        "pools",
        {
            "query_modes": ["gift_id", "pool_id"],
            "query_mode_cardinality": "EXACTLY_ONE",
            "matching": "EXACT_ID_OR_GIFT_MEMBERSHIP",
        },
    ),
    _contract(
        "add_gift_to_backpack",
        AddGiftToBackpackArguments,
        "grants",
        {
            "user_selection_modes": ["user_id", "user_ids"],
            "gift_selection_modes": ["gift_id", "gift_ids", "gift_nums"],
            "selection_cardinality": "EXACTLY_ONE_PER_GROUP",
            "default_num": 1,
            "default_duration_days": 7,
            "duplicate_users": "DEDUPLICATE",
            "duplicate_gifts": "REJECT",
            "environment_binding": "ISOLATED_FIXTURE_ONLY",
            "confirmation": "EXTERNAL_ONE_CALL_APPROVAL_CONSUMED_ON_ATTEMPT",
            "mutation": "VALIDATE_ALL_REFERENCES_BEFORE_WRITING",
        },
        write=True,
        confirmation=True,
        errors=("CONFIRMATION_REQUIRED", "NOT_FOUND", "DUPLICATE_GIFT"),
    ),
)
