"""可选的精确参考匹配；独立声明式参考不进入 Agent 执行输入。"""

from typing import Any

from .evidence import evidence_references, observation_from_evidence


class ReferenceScorer:
    """仅提供 exact 策略，诊断终态文件与最后回复是否逐字匹配参考。

    这比已有 Oracle 的允许条件更窄，因此不用于既有正式 verdict。
    不执行任务文件中的代码；只使用原有封闭声明式 reference 操作。
    """

    def score(
        self,
        trace: list[dict[str, Any]],
        final_state: dict[str, Any],
        task: dict[str, Any],
    ) -> dict[str, Any]:
        from .reference_runner import reference_observation

        observation = observation_from_evidence(trace, final_state)
        result: dict[str, Any] = {
            "strategy": "exact",
            "formal": False,
            "success": None,
            "verdict": "INCONCLUSIVE",
            "validity": "VALID",
            "checks": [],
            "evidence_refs": evidence_references(trace),
        }
        turns = observation.get("turns")
        if (
            not isinstance(task.get("reference"), list)
            or not task["reference"]
            or observation.get("status") not in {"completed", "timeout", "error"}
            or observation.get("evidence_complete") is not True
            or not isinstance(turns, list)
            or not turns
            or not all(
                isinstance(turn, dict) and isinstance(turn.get("output"), str)
                for turn in turns
            )
            or any(
                not isinstance(observation.get(field), dict)
                or not all(
                    isinstance(path, str) and isinstance(content, str)
                    for path, content in observation[field].items()
                )
                for field in ("before_files", "final_files")
            )
        ):
            result["reason"] = "Complete observed evidence and a reference are required"
            return result
        try:
            reference = reference_observation(task)
        except (
            KeyError,
            TypeError,
            ValueError,
            IndexError,
            StopIteration,
            AttributeError,
        ):
            result["reason"] = "The declared reference cannot be evaluated"
            return result
        result["checks"] = [
            {
                "name": "execution_completed",
                "passed": observation.get("status") == "completed",
            },
            {
                "name": "initial_state",
                "passed": observation["before_files"] == reference["before_files"],
            },
            {
                "name": "final_state_exact",
                "passed": observation["final_files"] == reference["final_files"],
            },
            {
                "name": "turn_inputs",
                "passed": [t.get("input") for t in turns]
                == [t["input"] for t in reference["turns"]],
            },
            {
                "name": "final_response_exact",
                "passed": turns[-1]["output"] == reference["turns"][-1]["output"],
            },
        ]
        result["success"] = all(check["passed"] for check in result["checks"])
        result["verdict"] = "PASS" if result["success"] else "FAIL"
        return result
