"""离线文件工具重复候选诊断，不判断调用必要性，不参与正式 verdict。

只覆盖 read_file/write_file/edit_file/list_dir。每条调用先要求完整轨迹、
唯一事件 ID、明确轮次、已执行的完整结果、无冲突错误标志、规范化 JSON
参数以及独立 before_files/after_files；最终状态、工具输出不能补齐快照。
快照错误字段缺省兼容现有成功采集格式，非空错误使证据不可用。

同轮最近一次同工具、同规范化参数是比较锚点。参数对象键序无关，数组序
和 JSON 类型保留；不自行补默认值或重写路径。先前错误单列 retry_after_error。
其余调用要求比较区间内工具顺序由时间证明，所有前后快照都相同才标记
repeated_same_state。中间写入再恢复也归为 state_changed。不同轮不比较。
无先前同参数调用为 first_call；自身或此前同轮的证据不足均为 MISSING，
避免把未完成记录当作无重复。非本地工具不适用，跨越这类工具的比较缺证据。
turn 事件必须显式提供互不重复的非 bool 正整数轮次。现有文件工具运行时
直接以 turn 为父节点；给定 parent_id 必须引用该节点，不把悬空引用或其他
事件类型推断为轮次。无 parent_id/值为 None 的历史记录仍可使用工具显式轮次。

分数 1 仅表示上述规则未观测到同状态重复，0 表示可观察重复候选，均是诊断。
合法验证性读取也可能成为候选；重试标记不表示重试成功或必要。未知不记满分。
"""

from __future__ import annotations

import json
from importlib.metadata import version
from typing import Any

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from .recovery_scoring import _times
from .trajectory import _valid_snapshot

REPETITION_VERSION = "file-tools-repetition-v1"
_LOCAL_TOOLS = frozenset({"read_file", "write_file", "edit_file", "list_dir"})
_SEMANTICS = (
    "Observable same-state repetition candidate only; necessity is not established. "
    "Legitimate verification reads may be candidates; "
    "this never determines a formal failure."
)


class RepetitionMetric(BaseMetric):
    """DeepEval 的确定性诊断封装，不初始化或调用模型。"""

    threshold = 1.0
    async_mode = False
    strict_mode = True
    include_reason = True
    verbose_mode = False
    evaluation_model = "deterministic-file-state-repetition"

    @property
    def __name__(self) -> str:
        return "tool_nonrepetition"

    def measure(self, test_case: LLMTestCase, **_kwargs: Any) -> float:
        evidence = test_case.metadata or {}
        self.score = float(evidence["score"])
        self.reason = evidence["reason"]
        self.success = self.score >= self.threshold
        return self.score

    async def a_measure(self, test_case: LLMTestCase, **kwargs: Any) -> float:
        return self.measure(test_case, **kwargs)


def _record(
    classification: str,
    reason: str,
    event: dict[str, Any] | None = None,
    *,
    score: float | None = None,
    evidence_ids: list[str] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    result = {
        "name": "tool_nonrepetition",
        "backend": "deepeval",
        "version": REPETITION_VERSION,
        "library_version": version("deepeval"),
        "implementation": "RepetitionMetric",
        "formal": False,
        "scope": "tool" if event else "task",
        "event_id": event["id"] if event else None,
        "evidence_ids": evidence_ids
        if evidence_ids is not None
        else [event["id"]]
        if event
        else [],
        "classification": classification,
        "current_is_error": _error(event) if event else None,
        "threshold": 1.0,
        "score": None,
        "success": None,
        "reason": reason,
        "semantics": _SEMANTICS,
        "status": status or ("MISSING" if score is None else "SCORED"),
    }
    if score is not None:
        metric = RepetitionMetric()
        metric.measure(
            LLMTestCase(
                input="Diagnose saved file-tool repetition",
                actual_output=reason,
                metadata={"score": score, "reason": reason},
            )
        )
        result.update(score=metric.score, success=metric.is_successful())
    return result


def _error(event: dict[str, Any]) -> bool | None:
    flags = [event[key] for key in ("is_error", "tool_error") if key in event]
    if not flags or any(type(flag) is not bool for flag in flags):
        return None
    if len(set(flags)) != 1 or (not flags[0] and event.get("error")):
        return None
    return flags[0]


def _json_value(value: Any) -> bool:
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _json_value(item) for key, item in value.items()
        )
    if isinstance(value, list):
        return all(_json_value(item) for item in value)
    return value is None or type(value) in (str, int, float, bool)


def _arguments(event: dict[str, Any]) -> str | None:
    arguments = event.get("normalized_input")
    if not isinstance(arguments, dict) or not _json_value(arguments):
        return None
    try:
        return json.dumps(
            arguments, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
    except (TypeError, ValueError):
        return None


def _problem(event: dict[str, Any], turn: Any) -> str | None:
    if type(turn) is not int or turn < 1:
        return "A positive, unambiguous turn number is required"
    if (
        event.get("execution_started") is not True
        or _times(event) is None
        or not isinstance(event.get("output"), str)
        or _error(event) is None
        or _arguments(event) is None
    ):
        return (
            "Executed result, timing, error status or normalized arguments "
            "are missing/conflicting"
        )
    for prefix in ("before", "after"):
        if (
            not _valid_snapshot(event.get(f"{prefix}_files"))
            or event.get(f"{prefix}_snapshot_errors", []) != []
        ):
            return "Independent complete before/after file snapshots are required"
    return None


def score_repetition(
    task: dict[str, Any], observation: dict[str, Any]
) -> list[dict[str, Any]]:
    """输出工具级诊断；只消费 observation，task 保留统一接口，不读取 Oracle。"""
    events = observation.get("events")
    if (
        not isinstance(events, list)
        or observation.get("evidence_complete") is not True
        or any(
            not isinstance(event, dict)
            or not isinstance(event.get("id"), str)
            or not event["id"]
            or event.get("incomplete")
            for event in events
        )
        or len({event["id"] for event in events}) != len(events)
    ):
        return [
            _record(
                "missing_evidence",
                "Complete trace with unique nonempty event IDs is required",
            )
        ]
    tools = [event for event in events if event.get("type") == "tool"]
    if any(
        not isinstance(event.get("name"), str) or not event["name"] for event in tools
    ):
        return [_record("missing_evidence", "Tool names must be nonempty strings")]
    if not tools:
        return [
            _record(
                "no_tool_calls",
                "No tool calls in the complete trace",
                status="NOT_APPLICABLE",
            )
        ]

    turns = {
        event["id"]: event.get("turn")
        for event in events
        if event.get("type") == "turn"
    }
    invalid_turns = any(type(turn) is not int or turn < 1 for turn in turns.values())
    # Validate types before hashing: malformed JSON values may be unhashable,
    # and Python considers True equal to 1 despite distinct round identities.
    if not invalid_turns:
        invalid_turns = len(set(turns.values())) != len(turns)
    resolved: dict[str, int | None] = {}
    for event in tools:
        parent_id = event.get("parent_id")
        if invalid_turns or (
            parent_id is not None
            and (not isinstance(parent_id, str) or parent_id not in turns)
        ):
            resolved[event["id"]] = None
            continue
        parent_turn = turns.get(parent_id)
        turn = event.get("turn", parent_turn)
        resolved[event["id"]] = (
            None
            if type(turn) is not int
            or turn < 1
            or (parent_turn is not None and turn != parent_turn)
            else turn
        )

    records = []
    for index, event in enumerate(tools):
        if event.get("name") not in _LOCAL_TOOLS:
            records.append(
                _record(
                    "unsupported_tool",
                    "Tool is outside the four local file tools",
                    event,
                    status="NOT_APPLICABLE",
                )
            )
            continue
        turn = resolved[event["id"]]
        problem = _problem(event, turn)
        prior = [item for item in tools[:index] if resolved[item["id"]] in (None, turn)]
        if not problem and any(
            item.get("name") in _LOCAL_TOOLS and _problem(item, resolved[item["id"]])
            for item in prior
        ):
            problem = (
                "Earlier same-turn tool evidence is incomplete; "
                "nonrepetition cannot be established"
            )
        if problem:
            records.append(_record("missing_evidence", problem, event))
            continue
        matching = [
            item
            for item in prior
            if item.get("name") == event["name"]
            and _arguments(item) == _arguments(event)
        ]
        if not matching:
            records.append(
                _record(
                    "first_call",
                    "No earlier comparable call with the same tool and "
                    "normalized arguments in this turn",
                    event,
                    score=1,
                )
            )
            continue
        previous = matching[-1]
        start_index = tools.index(previous)
        interval = tools[start_index : index + 1]
        evidence_ids = [item["id"] for item in interval]
        if any(
            item.get("name") not in _LOCAL_TOOLS or resolved[item["id"]] != turn
            for item in interval
        ):
            problem = (
                "Comparison crosses unsupported tool state "
                "or inconsistent turn ordering"
            )
        elif any(
            _times(left)[1] > _times(right)[0]
            for left, right in zip(interval, interval[1:], strict=False)
        ):
            problem = (
                "Overlapping or reversed tool timing cannot establish "
                "completed-call order"
            )
        if problem:
            records.append(
                _record("missing_evidence", problem, event, evidence_ids=evidence_ids)
            )
        elif _error(previous):
            records.append(
                _record(
                    "retry_after_error",
                    "Same call follows a known tool error; "
                    "retry is not classified as redundant or necessarily successful",
                    event,
                    score=1,
                    evidence_ids=evidence_ids,
                )
            )
        elif all(
            item[field] == previous["before_files"]
            for item in interval
            for field in ("before_files", "after_files")
        ):
            records.append(
                _record(
                    "repeated_same_state",
                    "Observable repeated-call candidate with unchanged file state; "
                    "verification may be legitimate",
                    event,
                    score=0,
                    evidence_ids=evidence_ids,
                )
            )
        else:
            records.append(
                _record(
                    "state_changed",
                    "Observed file state changed within the comparison interval",
                    event,
                    score=1,
                    evidence_ids=evidence_ids,
                )
            )
    return records
