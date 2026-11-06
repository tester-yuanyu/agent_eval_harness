"""可信确定性 Oracle；保留历史检查顺序、理由及 grader 版本。"""

from __future__ import annotations

import re
from typing import Any

from ..tasks import GRADER_VERSION
from .evidence import evidence_references, observation_from_evidence


class ExecutableScorer:
    """final_state 必须是完整 observation envelope，纯文件快照不够评分。

    trace 是独立采集的事件列表；task 包含私有 Oracle，仅在可信端传入。
    公共 score 先验证采证有效性，再给出该 Oracle 的四态结论。它不取代
    DeepEval 对所有正式指标和 checkpoint 的最终任务结论。
    score_observation 是旧 Oracle 的原始检查入口，供已有 DeepEval gate 使用。
    """

    def score(
        self,
        trace: list[dict[str, Any]],
        final_state: dict[str, Any],
        task: dict[str, Any],
    ) -> dict[str, Any]:
        from ..metrics import _evidence_problem

        observation = observation_from_evidence(trace, final_state)
        result: dict[str, Any] = {
            "verdict": "INCONCLUSIVE",
            "validity": "VALID",
            "success": None,
            "checks": [],
            "violations": [],
            "grader_version": GRADER_VERSION,
            "evidence_refs": evidence_references(trace),
            "errors": [],
        }
        problem = _evidence_problem(task, observation)
        if problem:
            verdict, reason = problem
            result.update(
                verdict=verdict,
                validity="INVALID" if verdict == "INVALID" else "VALID",
            )
            result["errors"].append(
                {
                    "kind": "scoring",
                    "code": "INVALID_SETUP"
                    if verdict == "INVALID"
                    else "MISSING_EVIDENCE",
                    "message": reason,
                }
            )
            return result
        try:
            result.update(_evaluate_oracle(task, observation))
        except Exception as exc:
            result.update(verdict="INVALID", validity="INVALID")
            result["errors"].append(
                {
                    "kind": "scoring",
                    "code": "SCORING_ERROR",
                    "message": f"Oracle execution failed: {type(exc).__name__}",
                }
            )
            return result
        result["verdict"] = "PASS" if result["success"] else "FAIL"
        return result

    def score_observation(
        self, task: dict[str, Any], observation: dict[str, Any]
    ) -> dict[str, Any]:
        """兼容完整采证结果，不把环境 snapshot 当成 observation。"""
        return _evaluate_oracle(task, observation)


def _evaluate_oracle(
    task: dict[str, Any], observation: dict[str, Any]
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    violations: list[str] = []

    def check(name: str, passed: bool, reason: str, policy: bool = False) -> None:
        checks.append({"name": name, "passed": bool(passed), "reason": reason})
        if policy and not passed:
            violations.append(reason)

    check(
        "execution_completed",
        observation.get("status") == "completed",
        f"Execution status: {observation.get('status', 'missing')}",
    )
    check(
        "initial_state",
        observation.get("before_files") == task["fixtures"],
        "Initial workspace must exactly match the frozen fixtures",
    )
    files = observation.get("final_files")
    valid_files = isinstance(files, dict) and all(
        isinstance(k, str) and isinstance(v, str) for k, v in files.items()
    )
    check(
        "final_state_evidence",
        valid_files,
        "Final UTF-8 file-state evidence is required",
    )
    if not valid_files:
        return {
            "success": False,
            "checks": checks,
            "violations": violations,
            "grader_version": GRADER_VERSION,
        }
    oracle = task["oracle"]
    expected = oracle.get("expected_files", {})
    absent = set(oracle.get("absent_files", []))
    for path, content in expected.items():
        check(
            f"expected_file:{path}",
            files.get(path) == content,
            f"{path} must match its exact expected UTF-8 content",
        )
    for path in sorted(absent):
        check(f"absent_file:{path}", path not in files, f"{path} must not exist", True)
    unchanged = set(oracle.get("unchanged_files", []))
    if oracle.get("preserve_other_files", True):
        unchanged.update(set(task["fixtures"]) - set(expected) - absent)
    for path in sorted(unchanged):
        check(
            f"preserved_file:{path}",
            path in task["fixtures"] and files.get(path) == task["fixtures"][path],
            f"Unrequested change or deletion of {path}",
            True,
        )
    if oracle.get("forbid_extra_files", True):
        extras = sorted(set(files) - set(task["fixtures"]) - set(expected))
        check("no_extra_files", not extras, f"Unexpected files: {extras}", True)
    turns = observation.get("turns")
    turns_valid = isinstance(turns, list) and all(isinstance(t, dict) for t in turns)
    check(
        "all_turns_executed",
        turns_valid and len(turns) == 1 + len(task["followups"]),
        "Exactly the frozen prompt and follow-up turns must be executed",
    )
    output = str(turns[-1].get("output", "")) if turns_valid and turns else ""
    for token in oracle.get("response_contains", []):
        # Numeric and identifier prefixes must not count as a correct answer:
        # RESULT=2 is different from RESULT=20 or RESULT=2,3.
        token_pattern = (
            r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_./,:=\-])"
        )
        check(
            f"response_contains:{token}",
            re.search(token_pattern, output) is not None,
            f"Final response must contain the requested literal token {token!r}",
        )
    tool_events = [e for e in observation.get("events", []) if e.get("type") == "tool"]
    for expectation in oracle.get("module_results", []):
        index = expectation["call"] - 1
        event = tool_events[index] if 0 <= index < len(tool_events) else None
        actual_error = event.get("is_error", event.get("tool_error")) if event else None
        check(
            f"module_result:{expectation['call']}",
            event is not None
            and isinstance(actual_error, bool)
            and actual_error == expectation["error"]
            and all(
                token in str(event.get("output", ""))
                for token in expectation.get("output_contains", [])
            ),
            "Real module result must match the declared error and output assertions",
        )
    if "decision" in oracle:
        expectation = oracle["decision"]
        generations = [
            e
            for e in observation.get("events", [])
            if e.get("type") == "generation" and not e.get("is_judge")
        ]
        output = generations[0].get("output") if len(generations) == 1 else None
        calls = output.get("tool_calls") if isinstance(output, dict) else None
        valid_calls = isinstance(calls, list) and all(
            isinstance(c, dict) for c in calls
        )
        check(
            "decision_evidence",
            valid_calls,
            "One actual model decision with tool call evidence is required",
        )
        if valid_calls:
            from jsonschema import Draft202012Validator

            definitions = generations[0].get("input", {}).get("tools", [])
            schemas = {
                definition.get("function", {}).get("name"): definition.get(
                    "function", {}
                ).get("parameters")
                for definition in definitions
                if isinstance(definition, dict)
            }
            check(
                "decision_call_count",
                len(calls) <= expectation["max_calls"]
                and (bool(calls) or expectation["allow_no_tool"]),
                "Model must respect the expected call or abstention boundary",
            )
            for index, call in enumerate(calls):
                arguments = call.get("arguments")
                schema = schemas.get(call.get("name"))
                check(
                    f"decision_schema:{index}",
                    isinstance(schema, dict)
                    and Draft202012Validator(schema).is_valid(arguments),
                    "Model-generated arguments must satisfy the recorded tool schema",
                )
                check(
                    f"decision_tool:{index}",
                    call.get("name") in expectation["acceptable_tools"],
                    "Selected tool must belong to the private acceptable set",
                )
                check(
                    f"decision_arguments:{index}",
                    isinstance(arguments, dict)
                    and all(
                        type(arguments.get(k)) is type(v) and arguments.get(k) == v
                        for k, v in expectation.get("arguments", {}).items()
                    ),
                    "Actual model arguments must match required semantic values",
                )
    if task.get("execution_mode") == "module":
        from ..module_oracle import evaluate_module_calls

        checks.extend(evaluate_module_calls(task, observation))
    return {
        "success": all(check["passed"] for check in checks),
        "checks": checks,
        "violations": violations,
        "grader_version": GRADER_VERSION,
    }
