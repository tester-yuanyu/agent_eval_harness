"""Scorer 的可信 evidence adapter；不接受纯 snapshot 作为完整采证结果。"""

from typing import Any


def evidence_references(trace: list[dict[str, Any]]) -> list[str]:
    """只引用实际采集的非空事件 ID，不合成缺失快照或悬空节点。"""
    if not isinstance(trace, list):
        return []
    return list(
        dict.fromkeys(
            event["id"]
            for event in trace
            if isinstance(event, dict)
            and isinstance(event.get("id"), str)
            and event["id"]
        )
    )


def observation_from_evidence(
    trace: list[dict[str, Any]], final_state: dict[str, Any]
) -> dict[str, Any]:
    """组合独立 trace 与完整 observation envelope，不推断任何缺失字段。

    Environment.final_state() 的文件字典需要由 Harness 加入 status、turns、
    before_files、final_files、evidence_complete 等证据后再交给 Scorer。
    此处不把文件字典自动升级成成功执行。Scorer 对嵌套证据只读。
    """
    return {**final_state, "events": trace}
