"""Execution/oracle leakage checks."""

from __future__ import annotations

import json
import re

from eval_framework.schemas import EvalCase

from .schemas import GateResult

EXECUTION_FORBIDDEN = {
    "expected",
    "oracle",
    "goal_state",
    "answer",
    "score",
    "assertion",
    "golden",
    "rubric",
    "case_id",
}
INPUT_PATTERNS = (
    r"expected[_ ]?(intent|status|parameters)",
    r"标准答案",
    r"评分(规则|指令)",
    r"oracle",
)


def leakage_gate(cases: list[EvalCase]) -> GateResult:
    issues: list[str] = []
    for case in cases:
        serialized = json.dumps(
            case.execution.model_dump(mode="json"), ensure_ascii=False
        )
        lowered = serialized.casefold()
        leaked = sorted(word for word in EXECUTION_FORBIDDEN if word in lowered)
        if leaked:
            issues.append(f"{case.case_id}: execution leakage tokens {leaked}")
        for pattern in INPUT_PATTERNS:
            if re.search(pattern, case.execution.user_input, re.IGNORECASE):
                issues.append(f"{case.case_id}: user_input contains answer hint")
                break
    return GateResult(name="leakage", passed=not issues, issues=issues)
