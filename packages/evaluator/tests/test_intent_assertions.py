from __future__ import annotations

from conftest import assertion, module_case

from eval_framework.assertions import run_assertions
from eval_framework.capabilities import (
    CapabilityBundle,
    CapabilityDocument,
    CapabilityRegistry,
)
from eval_framework.mini_agent_adapter import AdapterOutput
from eval_framework.schemas import EvalCase


def _registry() -> CapabilityRegistry:
    envelope = {
        "type": "object",
        "additionalProperties": False,
        "required": ["intent", "status", "next_action", "reason"],
        "properties": {
            "intent": {"type": "string"},
            "status": {"type": "string"},
            "next_action": {"type": "string"},
            "parameters": {"type": "object"},
            "missing_parameters": {
                "type": "array",
                "items": {"type": "string"},
            },
            "reason": {"type": "string"},
        },
    }
    parameter_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "user_id": {"type": "integer", "exclusiveMinimum": 0},
            "note": {"type": "string"},
        },
    }
    documents = (
        CapabilityDocument(
            snapshot_id="intent_router",
            snapshot_type="module",
            snapshot_format_version="1.0",
            contract_version="router-v1",
            snapshot_sha256="a" * 64,
            module_id="intent_router",
            payload={"output_schema": envelope},
        ),
        CapabilityDocument(
            snapshot_id="query_user",
            snapshot_type="intent_capability",
            snapshot_format_version="1.0",
            contract_version="query-user-v1",
            snapshot_sha256="b" * 64,
            module_id="intent_router",
            capability_id="query_user",
            payload={"parameters_schema": parameter_schema},
        ),
        CapabilityDocument(
            snapshot_id="temporary_intent",
            snapshot_type="intent_capability",
            snapshot_format_version="1.0",
            contract_version="temporary-v1",
            snapshot_sha256="c" * 64,
            module_id="intent_router",
            capability_id="temporary_intent",
            payload={
                "parameters_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["token"],
                    "properties": {"token": {"type": "string", "minLength": 2}},
                }
            },
        ),
    )
    return CapabilityRegistry(
        CapabilityBundle(
            root="/fixture",
            provider_id="fixture",
            bundle_format_version="1.0",
            capability_bundle_sha256="d" * 64,
            documents=documents,
        )
    )


def _results(parameters, *, intent="query_user"):
    raw = module_case()
    raw["oracle"]["evaluation"]["checks"] = [
        assertion("intent_envelope_schema_valid", critical=True),
        assertion("intent_parameters_schema_valid", critical=True),
    ]
    case = EvalCase.model_validate(raw)
    output = AdapterOutput(
        module_output={
            "intent": intent,
            "status": "READY",
            "next_action": "CALL_TOOL",
            "parameters": parameters,
            "missing_parameters": [],
            "reason": "fixture",
        },
        turns=[],
        before_snapshot=None,
        turn_snapshots=[],
        snapshot=None,
    )
    return run_assertions(case, output, _registry())


def test_temporary_intent_schema_needs_no_core_registration():
    result = _results({"token": "ok"}, intent="temporary_intent")[1]

    assert result.passed is True


def test_unknown_actual_intent_is_assertion_failure():
    result = _results({}, intent="not_registered")[1]

    assert result.passed is False
    assert result.actual["errors"][0]["type"] == "UNKNOWN_CAPABILITY"


def test_omitted_optional_fields_remain_valid():
    results = _results({"user_id": 9075333})

    assert [item.passed for item in results] == [True, True]


def test_wrong_type_and_range_preserve_failure():
    wrong_type = _results({"user_id": "9075333"})[1]
    invalid_value = _results({"user_id": 0})[1]

    assert wrong_type.passed is False
    assert wrong_type.actual["errors"][0]["type"] == "JSON_SCHEMA_TYPE"
    assert invalid_value.passed is False
    assert invalid_value.actual["errors"][0]["type"] == (
        "JSON_SCHEMA_EXCLUSIVEMINIMUM"
    )


def test_extra_parameter_is_rejected():
    result = _results({"user_id": 9075333, "unexpected": True})[1]

    assert result.passed is False
    assert result.actual["errors"][0]["type"] == (
        "JSON_SCHEMA_ADDITIONALPROPERTIES"
    )


def test_legacy_output_schema_assertion_remains_registered():
    raw = module_case()

    case = EvalCase.model_validate(raw)

    assert case.oracle.evaluation.checks[0].name == "output_schema_valid"
