"""mini_agent-specific deterministic diagnostic rules."""

from __future__ import annotations

from collections.abc import Mapping

from ...capabilities import CapabilityRegistry
from ...diagnostics import evidence
from ...provider import DiagnosticOutcome
from ...schemas import AssertionResult, Diagnosis, EvalCase


class MiniAgentQueryUserDiagnosticRule:
    def diagnose(
        self,
        case: EvalCase,
        failed: Mapping[str, AssertionResult],
        registry: CapabilityRegistry,
    ) -> DiagnosticOutcome | None:
        clarification = _clarification(case, failed)
        if clarification is not None:
            consumed = set(clarification.source_assertions)
            diagnoses = [clarification]
            if clarification.code == "INVALID_PARAM_ACCEPTED":
                consumed.add("intent_parameters_schema_valid")
            elif "intent_parameters_schema_valid" in failed:
                diagnoses.extend(
                    _parameter_schema_diagnoses(
                        failed["intent_parameters_schema_valid"],
                        registry,
                        intent_id="query_user",
                    )
                )
                if diagnoses[1:]:
                    consumed.add("intent_parameters_schema_valid")
            return DiagnosticOutcome(
                diagnoses=diagnoses,
                consumed_assertions=consumed,
            )

        params = failed.get("params_match")
        if params is not None:
            diagnoses = _parameter_diagnoses(
                params,
                registry,
                intent_id="query_user",
            )
            if diagnoses:
                return DiagnosticOutcome(
                    diagnoses=diagnoses,
                    consumed_assertions={"params_match"},
                )
        schema = failed.get("intent_parameters_schema_valid")
        if schema is not None:
            diagnoses = _parameter_schema_diagnoses(
                schema,
                registry,
                intent_id="query_user",
            )
            if diagnoses:
                return DiagnosticOutcome(
                    diagnoses=diagnoses,
                    consumed_assertions={"intent_parameters_schema_valid"},
                )
        return None


class MiniAgentParameterDiagnosticRule:
    """Classify parameter-shape differences for one mini_agent intent."""

    def __init__(self, intent_id: str) -> None:
        self._intent_id = intent_id

    def diagnose(
        self,
        case: EvalCase,
        failed: Mapping[str, AssertionResult],
        registry: CapabilityRegistry,
    ) -> DiagnosticOutcome | None:
        del case
        params = failed.get("params_match")
        if params is None:
            return None
        diagnoses = _parameter_diagnoses(
            params,
            registry,
            intent_id=self._intent_id,
        )
        if not diagnoses:
            return None
        return DiagnosticOutcome(
            diagnoses=diagnoses,
            consumed_assertions={"params_match"},
        )


def _clarification(
    case: EvalCase, failed: Mapping[str, AssertionResult]
) -> Diagnosis | None:
    status = failed.get("status_match")
    missing = failed.get("missing_params_match")
    if status is None or missing is None:
        return None
    if status.expected != "NEED_CLARIFICATION" or status.actual != "READY":
        return None
    expected_missing = missing.expected if isinstance(missing.expected, list) else []
    labels = set(case.labels)
    if "slot:batch_mixed_or_conditions" in labels:
        code, title = "UNSUPPORTED_OR_QUERY_ACCEPTED", "OR 查询被错误接受"
    elif (
        "single_user_query_condition" in expected_missing
        or any("_or_" in str(item) for item in expected_missing)
        or labels
        & {
            "slot:ambiguous_bare_positive_integer",
            "slot:repeated_identical_value",
        }
    ):
        code, title = "AMBIGUOUS_REQUEST_NOT_CLARIFIED", "歧义请求未澄清"
    else:
        code, title = "INVALID_PARAM_ACCEPTED", "非法参数未识别"
    names = [
        name
        for name in (
            "status_match",
            "next_action_match",
            "params_match",
            "missing_params_match",
        )
        if name in failed
    ]
    return Diagnosis(
        code=code,
        title=title,
        category="decision",
        source_assertions=names,
        evidence_refs=evidence(failed[name] for name in names),
    )


def _field_label(
    registry: CapabilityRegistry,
    name: str,
    *,
    intent_id: str,
) -> str:
    display = registry.display_metadata(intent_id)
    labels = display.get("field_labels", {}) if isinstance(display, dict) else {}
    return labels.get(name, name) if isinstance(labels, dict) else name


def _parameter_schema_diagnoses(
    assertion: AssertionResult,
    registry: CapabilityRegistry,
    *,
    intent_id: str,
) -> list[Diagnosis]:
    actual = assertion.actual if isinstance(assertion.actual, dict) else {}
    diagnoses = []
    for error in actual.get("errors", []):
        if not isinstance(error, dict):
            continue
        path = error.get("path", error.get("loc", []))
        field = str(path[0]) if path else "parameters"
        error_type = str(error.get("type", ""))
        is_type = error_type in {
            "int_type",
            "string_type",
            "dict_type",
            "list_type",
            "JSON_SCHEMA_TYPE",
        }
        suffix = "类型错误" if is_type else "值非法"
        diagnoses.append(
            Diagnosis(
                code="PARAM_TYPE_MISMATCH" if is_type else "PARAM_VALUE_INVALID",
                title=f"{_field_label(registry, field, intent_id=intent_id)} {suffix}",
                category="parameters",
                source_assertions=[assertion.name],
                evidence_refs=assertion.evidence_refs,
            )
        )
    return diagnoses


def _parameter_diagnoses(
    assertion: AssertionResult,
    registry: CapabilityRegistry,
    *,
    intent_id: str,
) -> list[Diagnosis]:
    expected, actual = assertion.expected, assertion.actual
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return []
    for name in sorted(expected.keys() & actual.keys()):
        if expected[name].__class__ is not actual[name].__class__:
            label = _field_label(registry, name, intent_id=intent_id)
            return [
                Diagnosis(
                    code="PARAM_TYPE_MISMATCH",
                    title=f"{label} 类型错误",
                    category="parameters",
                    source_assertions=[assertion.name],
                    evidence_refs=assertion.evidence_refs,
                )
            ]
    if expected.keys() - actual.keys():
        code, title = "MISSING_REQUIRED_PARAM", "参数缺失"
    elif actual.keys() - expected.keys():
        code, title = "UNEXPECTED_PARAM", "出现多余参数"
    else:
        return []
    return [
        Diagnosis(
            code=code,
            title=title,
            category="parameters",
            source_assertions=[assertion.name],
            evidence_refs=assertion.evidence_refs,
        )
    ]
