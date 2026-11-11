"""报告与云端共用的评测分区；只投影保存统计，不执行或评分。"""

from __future__ import annotations


def display_statistics(summary: dict) -> dict:
    values = {}
    for group, record in summary["groups"].items():
        values.update(
            {
                group + ".trials": record["trials"],
                group + ".passed": record["passed"],
                group + ".pass_rate_percent": 100 * record["passed"] / record["trials"],
            }
        )
        for name, value in record.get("latency", {}).items():
            values[group + ".latency_" + name] = value
    for actor, usage in summary["usage"].items():
        values.update({actor + "." + key: value for key, value in usage.items()})
    counts = {}
    for name, metric in summary["dimensions"].items():
        values.update(
            {
                "geval." + name + "." + key: metric[key]
                for key in ("scored", "applicable", "mean")
            }
        )
        for status, count in metric["statuses"].items():
            counts[status] = counts.get(status, 0) + count
    values.update(
        {
            "geval.scored": counts.get("SCORED", 0),
            "geval.not_applicable": counts.get("NOT_APPLICABLE", 0),
            "geval.errors": counts.get("ERROR", 0) + counts.get("MISSING", 0),
        }
    )
    values["recovery.expected_failure_cases"] = summary["recovery_context"][
        "expected_failure_cases"
    ]
    return values


def cards(summary: dict) -> list[tuple[str, str, str]]:
    result = []
    for group, label in [
        ("agent", "真实模型案例"),
        ("deterministic", "确定性检查"),
        ("unclassified", "未分类执行"),
    ]:
        r = summary["groups"].get(group)
        if not r:
            continue
        result.append(
            (
                group + ".pass_rate_percent",
                f"{label}通过率 · {r['passed']}/{r['trials']} · "
                f"{100 * r['passed'] / r['trials']:.1f}%",
                "PASS/该组全部执行；FAIL、INVALID均保留在分母。确定性检查不代表模型能力。",
            )
        )
    for name, m in summary["dimensions"].items():
        desc = "保存的G-Eval诊断分数，未人工校准，不是成功概率，不覆盖规则FAIL。"
        if name == "recovery_appropriateness":
            n = summary["recovery_context"]["expected_failure_cases"]
            desc += (
                f"其中{n}条注入故障且规则期望FAILED；评估错误处理质量，不是恢复成功率。"
            )
        label = {
            "action_appropriateness": "动作合理性",
            "recovery_appropriateness": "故障处理合理性",
            "response_groundedness": "回复事实依据",
        }.get(name, name)
        result.append(
            (
                "geval." + name + ".mean",
                f"G-Eval {label} · {m['scored']}/{m['applicable']}项",
                desc,
            )
        )
    result.extend(
        [
            (
                "geval.scored",
                "有效 G-Eval 评分项",
                "评分项不等于独立案例；只统计SCORED。",
            ),
            (
                "geval.not_applicable",
                "不适用的评分项",
                "确定性检查等不需要模型判断；N/A不计零分。",
            ),
            ("geval.errors", "评分 ERROR / MISSING", "不把评分缺失计作通过或0分。"),
        ]
    )
    for actor, label in [("agent", "Agent"), ("judge", "Judge")]:
        u = summary["usage"][actor]
        result.extend(
            [
                (
                    actor + ".calls",
                    label + " 模型请求数",
                    "保存的generation事件数，含保存的失败请求与重试；不是案例数。",
                ),
                (
                    actor + ".known_total_tokens",
                    label + " 已知 Token",
                    f"已知{subtotal(u)}；另有{u['unknown_calls']}次请求用量未知，不补零。",
                ),
                (
                    actor + ".unknown_calls",
                    label + " 用量未知请求",
                    "只计未报告完整Token的请求，未知值不当零。",
                ),
            ]
        )
    for group, label in [("agent", "模型案例"), ("deterministic", "确定性检查")]:
        if summary["groups"].get(group, {}).get("latency"):
            result.extend(
                [
                    (
                        group + ".latency_mean_seconds",
                        label + " 平均执行耗时 · 秒",
                        "保存的trial执行耗时，不含后续Judge、报告和上传；并发任务耗时不等于整批墙钟。",
                    ),
                    (
                        group + ".latency_p95_seconds",
                        label + " P95执行耗时 · 秒",
                        "按该组完整执行耗时排序取nearest-rank；仅描述本轮。",
                    ),
                ]
            )
    return result


def subtotal(usage):
    return str(usage["known_total_tokens"]) + " Token"
