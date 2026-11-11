"""从保存证据生成执行/评分分区视图；不改变评分和历史身份。"""

from __future__ import annotations

from collections import Counter
from html import escape
from math import ceil
from statistics import mean


def is_judge_event(event: dict) -> bool:
    name = str(event.get("name", ""))
    return (
        event.get("is_judge") is True
        or name.startswith(("Judge:", "geval:"))
        or name == "deepeval_response_judge"
    )


def execution_group(row: dict, task: dict) -> str:
    kind = row.get("observation", {}).get("execution_kind", "")
    if task.get("live") is False or kind in {
        "deterministic_environment_check",
        "real_module",
        "deterministic_reference_not_agent",
    }:
        return "deterministic"
    if task.get("live") is True or kind in {
        "real_model_agent",
        "real_model_decision",
        "harness_raw_model",
    }:
        return "agent"
    if any(
        e.get("type") == "generation" and not is_judge_event(e)
        for e in row.get("observation", {}).get("events", [])
    ):
        return "agent"
    return "unclassified"


def evaluation_summary(run: dict, tasks: dict) -> dict:
    groups, usage, metrics = {}, {}, []
    expected_failure_cases, recovery_items = set(), 0
    for row in run["trials"]:
        task = tasks.get(row["case_id"], {})
        group = execution_group(row, task)
        entry = groups.setdefault(
            group, {"trials": 0, "passed": 0, "verdicts": Counter()}
        )
        entry["trials"] += 1
        entry["passed"] += row["assessment"]["verdict"] == "PASS"
        entry["verdicts"][row["assessment"]["verdict"]] += 1
        for metric in row["assessment"].get("metrics", []):
            if "judge_repeat" not in metric:
                continue
            metrics.append(metric)
            if (
                metric.get("name") == "recovery_appropriateness"
                and metric.get("status") == "SCORED"
            ):
                recovery_items += 1
                checks = task.get("oracle", {}).get("checks", [])
                if task.get("plan", {}).get("fault") and any(
                    c.get("actual") == "agent_result.status"
                    and c.get("op") == "equals"
                    and c.get("expected") == "FAILED"
                    for c in checks
                ):
                    expected_failure_cases.add((row["case_id"], row["trial"]))
    for group, entry in groups.items():
        durations = [
            row.get("latency_seconds")
            for row in run["trials"]
            if execution_group(row, tasks.get(row["case_id"], {})) == group
        ]
        if durations and all(type(v) in (int, float) and v >= 0 for v in durations):
            entry["latency"] = {
                "mean_seconds": mean(durations),
                "p95_seconds": sorted(durations)[ceil(0.95 * len(durations)) - 1],
            }
    for actor in ("agent", "judge"):
        events = [
            e
            for row in run["trials"]
            for e in row.get("observation", {}).get("events", [])
            if e.get("type") == "generation" and is_judge_event(e) == (actor == "judge")
        ]
        totals = []
        for e in events:
            u = e.get("usage", {})
            value = u.get("total_tokens")
            # Judge's client records standard total-input tokens (cache inclusive).
            if (
                value is None
                and actor == "judge"
                and all(
                    type(u.get(k)) is int for k in ("input_tokens", "output_tokens")
                )
            ):
                value = u["input_tokens"] + u["output_tokens"]
            totals.append(value if type(value) is int and value >= 0 else None)
        usage[actor] = {
            "calls": len(events),
            "known_calls": sum(v is not None for v in totals),
            "known_total_tokens": sum(v for v in totals if v is not None),
            "unknown_calls": sum(v is None for v in totals),
        }
    dimensions = {}
    for name in sorted({m["name"] for m in metrics}):
        subset = [m for m in metrics if m["name"] == name]
        scored = [
            m["score"]
            for m in subset
            if m.get("status") == "SCORED" and type(m.get("score")) in (int, float)
        ]
        counts = Counter(m.get("status", "MISSING") for m in subset)
        dimensions[name] = {
            "scored": len(scored),
            "applicable": len(subset) - counts["NOT_APPLICABLE"],
            "mean": mean(scored) if scored else None,
            "statuses": dict(counts),
        }
    return {
        "groups": groups,
        "usage": usage,
        "dimensions": dimensions,
        "deterministic_model_usage": "NOT_APPLICABLE",
        "recovery_context": {
            "expected_failure_cases": len(expected_failure_cases),
            "scored_items": recovery_items,
        },
    }


def evaluation_html(summary: dict) -> str:
    labels = {
        "agent": "真实模型执行",
        "deterministic": "确定性检查",
        "unclassified": "未分类执行",
    }
    rows = "".join(
        f"<tr><td>{labels[k]}</td><td>{v['passed']}/{v['trials']}</td>"
        f"<td>{100 * v['passed'] / v['trials']:.1f}%</td></tr>"
        for k, v in summary["groups"].items()
    )
    dims = "".join(
        f"<tr><td>{escape(k)}</td><td>{v['scored']}/{v['applicable']}</td><td>{v['mean']:.3f}</td></tr>"
        if v["mean"] is not None
        else f"<tr><td>{escape(k)}</td><td>{v['scored']}/{v['applicable']}</td>"
        "<td>不适用或未评分</td></tr>"
        for k, v in summary["dimensions"].items()
    )
    usage = "".join(
        f"<li>{name}：{v['calls']}次请求，已知Token {v['known_total_tokens']}"
        f"，{v['unknown_calls']}次请求用量未知。</li>"
        for name, v in summary["usage"].items()
    )
    recovery = summary["recovery_context"]
    return (
        '<section id="evaluation-partitions"><h2>执行类型与 G-Eval</h2>'
        "<table><tr><th>执行范围</th><th>通过/已执行</th><th>通过率</th></tr>"
        + rows
        + "</table>"
        "<p>确定性检查的模型用量为不适用；未执行案例与基础设施失败不计为通过。总体混合通过率不代表模型能力。</p><ul>"
        + usage
        + "</ul>"
        "<table><tr><th>质量维度</th><th>已评分/适用评分项</th><th>均分</th></tr>"
        + dims
        + "</table>"
        "<p>评分项不等于独立案例。G-Eval未校准，不是成功概率，不覆盖规则FAIL。"
        f"恢复维度含{recovery['expected_failure_cases']}条注入故障且规则期望FAILED的案例；应分别理解正确终止、错误说明质量和实际恢复行为，不能将低分直接解释为恢复失败率。</p></section>"
    )
