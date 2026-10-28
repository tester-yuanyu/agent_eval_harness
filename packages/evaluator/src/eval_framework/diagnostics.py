"""Agent-neutral deterministic diagnosis dispatcher."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .capabilities import CapabilityRegistry
from .provider import DiagnosticRule
from .schemas import AssertionResult, Diagnosis, EvalCase
from .taxonomy import GENERIC_DIAGNOSES


class DiagnosticRegistry:
    def __init__(self) -> None:
        self._rules: dict[str, list[DiagnosticRule]] = {}

    def register(self, intent_id: str, rule: DiagnosticRule) -> None:
        if not intent_id:
            raise ValueError("intent_id must be non-empty")
        rules = self._rules.setdefault(intent_id, [])
        if not any(existing is rule for existing in rules):
            rules.append(rule)

    def rules_for(
        self,
        case: EvalCase,
        assertions: Sequence[AssertionResult],
    ) -> tuple[DiagnosticRule, ...]:
        expected = case.oracle.expected_module_output or {}
        intent_id = expected.get("intent")
        if not isinstance(intent_id, str) or not intent_id:
            match = next(
                (item for item in assertions if item.name == "intent_match"),
                None,
            )
            intent_id = match.actual if match is not None else None
        if not isinstance(intent_id, str) or not intent_id:
            return ()
        return tuple(self._rules.get(intent_id, ()))


def build_diagnoses(
    assertions: list[AssertionResult],
    *,
    case: EvalCase,
    capabilities: CapabilityRegistry,
    rules: Sequence[DiagnosticRule] = (),
) -> list[Diagnosis]:
    """Classify observed failures without claiming an unproven root cause."""

    failed = {item.name: item for item in assertions if item.passed is False}
    assertion_order = {item.name: index for index, item in enumerate(assertions)}
    if not failed:
        return []
    diagnoses: list[Diagnosis] = []
    consumed: set[str] = set()
    for rule in rules:
        remaining = {
            name: item for name, item in failed.items() if name not in consumed
        }
        if not remaining:
            break
        outcome = rule.diagnose(case, remaining, capabilities)
        if outcome is None:
            continue
        newly_consumed = outcome.consumed_assertions & set(remaining)
        if not newly_consumed:
            continue
        diagnoses.extend(outcome.diagnoses)
        consumed.update(newly_consumed)

    missing = failed.get("missing_params_match")
    if missing is not None and "missing_params_match" not in consumed:
        expected = missing.expected if isinstance(missing.expected, list) else []
        actual = missing.actual if isinstance(missing.actual, list) else []
        if expected and actual:
            diagnoses.append(
                _diagnosis(
                    "PROTOCOL_NAMING_MISMATCH",
                    "协议命名不一致",
                    "protocol",
                    missing,
                )
            )
            consumed.add("missing_params_match")

    diagnoses.extend(_generic(failed, consumed))
    return _sort_diagnoses(_dedupe_diagnoses(diagnoses), assertion_order)


def _generic(failed: dict[str, AssertionResult], consumed: set[str]) -> list[Diagnosis]:
    diagnoses = []
    for name, assertion in failed.items():
        if name in consumed:
            continue
        code, title, category = GENERIC_DIAGNOSES.get(
            name, (f"ASSERTION_{name.upper()}", name, "other")
        )
        diagnoses.append(_diagnosis(code, title, category, assertion))
    return diagnoses


def _diagnosis(
    code: str, title: str, category: str, assertion: AssertionResult
) -> Diagnosis:
    return Diagnosis(
        code=code,
        title=title,
        category=category,
        source_assertions=[assertion.name],
        evidence_refs=assertion.evidence_refs,
    )


def evidence(assertions: Iterable[AssertionResult]) -> list[str]:
    return list(
        dict.fromkeys(
            ref for assertion in assertions for ref in assertion.evidence_refs
        )
    )


def _dedupe_diagnoses(diagnoses: list[Diagnosis]) -> list[Diagnosis]:
    unique = []
    seen = set()
    for diagnosis in diagnoses:
        key = (diagnosis.code, tuple(diagnosis.source_assertions))
        if key not in seen:
            seen.add(key)
            unique.append(diagnosis)
    return unique


def _sort_diagnoses(
    diagnoses: list[Diagnosis], assertion_order: dict[str, int]
) -> list[Diagnosis]:
    return sorted(
        diagnoses,
        key=lambda item: min(
            (
                assertion_order.get(name, len(assertion_order))
                for name in item.source_assertions
            ),
            default=len(assertion_order),
        ),
    )
