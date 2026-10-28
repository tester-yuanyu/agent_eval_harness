"""Reproducible weighted scoring and phase-one quality conclusions."""

from decimal import ROUND_HALF_UP, Decimal

from .schemas import AssertionResult, QualityConclusion


def score_assertions(
    assertions: list[AssertionResult], threshold: float
) -> tuple[float | None, QualityConclusion]:
    applicable = [item for item in assertions if item.applicable]
    if not applicable:
        return None, "INCONCLUSIVE"
    if any(item.passed is None for item in applicable):
        return None, (
            "FAIL" if any(item.passed is False for item in applicable)
            else "INCONCLUSIVE"
        )
    total = sum(Decimal(str(item.weight)) for item in applicable)
    passed = sum(
        Decimal(str(item.weight)) for item in applicable if item.passed is True
    )
    score = (passed * Decimal(100) / total).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    critical_failure = any(
        item.critical and item.passed is False for item in applicable
    )
    conclusion: QualityConclusion = (
        "FAIL" if critical_failure or score < Decimal(str(threshold)) else "PASS"
    )
    return float(score), conclusion
