"""Step → Turn → Task → Trial → Benchmark 的保存证据视图。

层级只保留和关联已有指标，不生成新分数、不平均正式硬约束。
孤立事件和无法绑定的指标单独保留；缺证据不会被补成成功。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal

from .summaries import evidence_summary, summarize


@dataclass
class StepAggregate:
    event: dict[str, Any]
    metrics: list[dict[str, Any]]
    level: Literal["step"] = field(default="step", init=False)


@dataclass
class TurnAggregate:
    event: dict[str, Any]
    steps: list[StepAggregate]
    metrics: list[dict[str, Any]]
    level: Literal["turn"] = field(default="turn", init=False)


@dataclass
class TaskAggregate:
    task_id: str
    turns: list[TurnAggregate]
    metrics: list[dict[str, Any]]
    unbound_steps: list[StepAggregate]
    unbound_metrics: list[dict[str, Any]]
    level: Literal["task"] = field(default="task", init=False)


@dataclass
class TrialAggregate:
    case_id: str
    trial: int
    verdict: str
    validity: str
    task: TaskAggregate
    level: Literal["trial"] = field(default="trial", init=False)


@dataclass
class BenchmarkAggregate:
    summary: dict[str, Any]
    trials: list[TrialAggregate]
    level: Literal["benchmark"] = field(default="benchmark", init=False)


def aggregate_step(
    event: dict[str, Any], metrics: list[dict[str, Any]]
) -> StepAggregate:
    """关联当前事件的已保存指标；无分数时保留空列表。"""
    return StepAggregate(deepcopy(event), deepcopy(metrics))


def aggregate_turn(
    event: dict[str, Any],
    steps: list[StepAggregate],
    metrics: list[dict[str, Any]],
) -> TurnAggregate:
    return TurnAggregate(deepcopy(event), deepcopy(steps), deepcopy(metrics))


def aggregate_task(
    task_id: str,
    observation: dict[str, Any],
    metrics: list[dict[str, Any]],
) -> TaskAggregate:
    events = observation.get("events", [])
    if not isinstance(events, list) or any(not isinstance(e, dict) for e in events):
        raise ValueError("saved events must be a list of objects")
    ids = [e["id"] for e in events if e.get("id") is not None]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("duplicate or invalid saved event id")
    turns = [event for event in events if event.get("type") == "turn"]
    bound: dict[str, list[dict[str, Any]]] = {identifier: [] for identifier in ids}
    task_metrics, unbound_metrics = [], []
    for metric in metrics:
        identifier = metric.get("event_id")
        if metric.get("scope", "task") in {"task", "chain"}:
            task_metrics.append(metric)
        elif isinstance(identifier, str) and identifier in bound:
            bound[identifier].append(metric)
        else:
            unbound_metrics.append(metric)
    children: list[list[StepAggregate]] = [[] for _ in turns]
    unbound_steps = []
    for event in events:
        if event.get("type") == "turn":
            continue
        step = aggregate_step(event, bound.get(event.get("id"), []))
        parent = event.get("parent_id")
        if parent is not None:
            candidates = [
                i
                for i, turn in enumerate(turns)
                if turn.get("id") == parent
                and (
                    "turn" not in event
                    or "turn" not in turn
                    or (
                        type(event["turn"]) is int
                        and event["turn"] > 0
                        and type(turn["turn"]) is int
                        and event["turn"] == turn["turn"]
                    )
                )
            ]
        else:
            # 历史事件可没有 parent_id；只接受明确且唯一的正整数轮次。
            number = event.get("turn")
            candidates = [
                i
                for i, turn in enumerate(turns)
                if type(number) is int
                and number > 0
                and type(turn.get("turn")) is int
                and turn["turn"] == number
            ]
        if len(candidates) == 1:
            children[candidates[0]].append(step)
        else:
            unbound_steps.append(step)
    return TaskAggregate(
        task_id=task_id,
        turns=[
            aggregate_turn(turn, children[i], bound.get(turn.get("id"), []))
            for i, turn in enumerate(turns)
        ],
        metrics=deepcopy(task_metrics),
        unbound_steps=unbound_steps,
        unbound_metrics=deepcopy(unbound_metrics),
    )


def aggregate_trial(row: dict[str, Any]) -> TrialAggregate:
    assessment = row["assessment"]
    return TrialAggregate(
        case_id=row["case_id"],
        trial=row["trial"],
        verdict=assessment["verdict"],
        validity=assessment["validity"],
        task=aggregate_task(
            row["case_id"], row["observation"], assessment.get("metrics", [])
        ),
    )


def aggregate_benchmark(run: dict[str, Any]) -> BenchmarkAggregate:
    """验证计划与 trial 唯一性，再创建五层视图；不执行任何评分器。"""
    evidence_summary(run)
    return BenchmarkAggregate(
        summary=summarize(
            run["trials"], run["planned_case_ids"], run["trials_per_case"]
        ),
        trials=[aggregate_trial(row) for row in run["trials"]],
    )
