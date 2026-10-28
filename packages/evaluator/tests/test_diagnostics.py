from conftest import module_case

from eval_framework.diagnostics import DiagnosticRegistry, build_diagnoses
from eval_framework.provider import DiagnosticOutcome
from eval_framework.providers.mini_agent.diagnostics import (
    MiniAgentQueryUserDiagnosticRule,
)
from eval_framework.schemas import AssertionResult, EvalCase


def failed(name, expected, actual, ref):
    return AssertionResult(
        name=name,
        weight=1,
        critical=True,
        passed=False,
        expected=expected,
        actual=actual,
        evidence_refs=[ref],
    )


def test_parameter_type_mismatch_is_a_specific_diagnosis(capability_registry):
    diagnoses = build_diagnoses(
        [
            failed(
                "params_match",
                {"user_id": 9075333, "phone": "15000000200"},
                {"user_id": "9075333", "phone": "15000000200"},
                "module_output:/parameters",
            )
        ],
        case=EvalCase.model_validate(module_case()),
        capabilities=capability_registry,
        rules=(MiniAgentQueryUserDiagnosticRule(),),
    )

    assert [item.code for item in diagnoses] == ["PARAM_TYPE_MISMATCH"]
    assert diagnoses[0].title == "user_id 类型错误"
    assert diagnoses[0].category == "parameters"


def test_invalid_parameter_is_not_reported_as_missing(capability_registry):
    diagnoses = build_diagnoses(
        [
            failed("status_match", "NEED_CLARIFICATION", "READY", "status"),
            failed("next_action_match", "ASK_USER", "CALL_TOOL", "action"),
            failed("params_match", {}, {"user_id": 0}, "parameters"),
            failed("missing_params_match", ["user_id"], [], "missing"),
        ],
        case=EvalCase.model_validate(module_case()),
        capabilities=capability_registry,
        rules=(MiniAgentQueryUserDiagnosticRule(),),
    )

    assert [item.code for item in diagnoses] == ["INVALID_PARAM_ACCEPTED"]
    assert diagnoses[0].title == "非法参数未识别"
    assert set(diagnoses[0].source_assertions) == {
        "status_match",
        "next_action_match",
        "params_match",
        "missing_params_match",
    }


def test_or_query_reports_or_acceptance_and_parameter_type(capability_registry):
    raw_case = module_case("MINI-QUSER-042")
    raw_case["labels"].extend(["batch_unsupported", "slot:batch_mixed_or_conditions"])
    case = EvalCase.model_validate(raw_case)
    diagnoses = build_diagnoses(
        [
            failed("status_match", "NEED_CLARIFICATION", "READY", "status"),
            failed("next_action_match", "ASK_USER", "CALL_TOOL", "action"),
            failed(
                "params_match",
                {},
                {"user_id": 1, "email": "a@example.test"},
                "parameters",
            ),
            failed(
                "missing_params_match",
                ["single_user_query_condition"],
                [],
                "missing",
            ),
            failed(
                "intent_parameters_schema_valid",
                {"intent": "query_user", "schema": "QueryUserInfoArguments"},
                {
                    "parameters": {
                        "user_id": "9075343",
                        "email": "alternate@example.test",
                    },
                    "errors": [
                        {"type": "int_type", "loc": ["user_id"]},
                    ],
                },
                "module_output:/parameters",
            ),
        ],
        case=case,
        capabilities=capability_registry,
        rules=(MiniAgentQueryUserDiagnosticRule(),),
    )

    assert [item.code for item in diagnoses] == [
        "UNSUPPORTED_OR_QUERY_ACCEPTED",
        "PARAM_TYPE_MISMATCH",
    ]
    assert diagnoses[0].title == "OR 查询被错误接受"
    assert diagnoses[1].title == "user_id 类型错误"


def test_missing_parameter_name_only_is_protocol_naming_mismatch(
    capability_registry,
):
    diagnoses = build_diagnoses(
        [failed("missing_params_match", ["query_condition"], ["user_id"], "missing")],
        case=EvalCase.model_validate(module_case()),
        capabilities=capability_registry,
        rules=(MiniAgentQueryUserDiagnosticRule(),),
    )

    assert [item.code for item in diagnoses] == ["PROTOCOL_NAMING_MISMATCH"]
    assert diagnoses[0].category == "protocol"


def test_added_missing_parameter_is_not_protocol_naming_mismatch(
    capability_registry,
):
    diagnoses = build_diagnoses(
        [failed("missing_params_match", [], ["single_user_id"], "missing")],
        case=EvalCase.model_validate(module_case()),
        capabilities=capability_registry,
        rules=(MiniAgentQueryUserDiagnosticRule(),),
    )

    assert [item.code for item in diagnoses] == ["CLARIFICATION_TARGET_MISMATCH"]
    assert diagnoses[0].category == "decision"


def test_ambiguous_slot_is_not_reported_as_invalid_parameter(capability_registry):
    raw_case = module_case("MINI-QUSER-028")
    raw_case["labels"].append("slot:ambiguous_bare_positive_integer")
    case = EvalCase.model_validate(raw_case)
    diagnoses = build_diagnoses(
        [
            failed("status_match", "NEED_CLARIFICATION", "READY", "status"),
            failed("missing_params_match", ["user_id_or_room_id"], [], "missing"),
        ],
        case=case,
        capabilities=capability_registry,
        rules=(MiniAgentQueryUserDiagnosticRule(),),
    )

    assert diagnoses[0].code == "AMBIGUOUS_REQUEST_NOT_CLARIFIED"


def test_two_rules_cannot_duplicate_consumed_assertion(capability_registry):
    class DuplicateRule:
        def diagnose(self, case, failed, registry):
            if "params_match" not in failed:
                return None
            return DiagnosticOutcome(
                diagnoses=[
                    {
                        "code": "CUSTOM",
                        "title": "custom",
                        "category": "parameters",
                        "source_assertions": ["params_match"],
                    }
                ],
                consumed_assertions={"params_match"},
            )

    assertions = [failed("params_match", {"user_id": 1}, {"user_id": "1"}, "p")]
    diagnoses = build_diagnoses(
        assertions,
        case=EvalCase.model_validate(module_case()),
        capabilities=capability_registry,
        rules=(DuplicateRule(), DuplicateRule()),
    )

    assert [item.code for item in diagnoses] == ["CUSTOM"]


def test_specialized_diagnosis_order_is_stable(capability_registry):
    assertions = [
        failed("status_match", "NEED_CLARIFICATION", "READY", "status"),
        failed("params_match", {"user_id": 1}, {"user_id": "1"}, "params"),
        failed("missing_params_match", ["user_id"], [], "missing"),
    ]

    diagnoses = build_diagnoses(
        assertions,
        case=EvalCase.model_validate(module_case()),
        capabilities=capability_registry,
        rules=(MiniAgentQueryUserDiagnosticRule(),),
    )

    assert [item.code for item in diagnoses] == ["INVALID_PARAM_ACCEPTED"]


def test_diagnostic_registry_routes_multiple_rules_by_expected_intent():
    first = object()
    second = object()
    registry = DiagnosticRegistry()
    registry.register("query_information", first)
    registry.register("query_information", second)

    rules = registry.rules_for(EvalCase.model_validate(module_case()), [])

    assert rules == (first, second)


def test_diagnostic_registry_uses_actual_intent_when_expected_is_missing():
    rule = object()
    registry = DiagnosticRegistry()
    registry.register("future_intent", rule)
    raw = module_case()
    raw["oracle"]["expected_module_output"].pop("intent")

    rules = registry.rules_for(
        EvalCase.model_validate(raw),
        [failed("intent_match", None, "future_intent", "intent")],
    )

    assert rules == (rule,)


def test_diagnostic_registry_unknown_or_missing_intent_returns_no_rules():
    registry = DiagnosticRegistry()
    raw = module_case()
    raw["oracle"]["expected_module_output"].pop("intent")
    case = EvalCase.model_validate(raw)

    assert registry.rules_for(case, []) == ()
    assert registry.rules_for(
        case,
        [failed("intent_match", None, None, "intent")],
    ) == ()


def test_diagnostic_registry_deduplicates_same_rule_instance():
    rule = object()
    registry = DiagnosticRegistry()
    registry.register("query_information", rule)
    registry.register("query_information", rule)

    assert registry.rules_for(
        EvalCase.model_validate(module_case()), []
    ) == (rule,)
