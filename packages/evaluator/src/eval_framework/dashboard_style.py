"""Native dashboard presentation of saved results and intake inventory."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .observability import stable_id


def partition_kind(run: dict[str, Any]) -> str:
    saved = run["loaded"].result.onboarding or {}
    return saved.get("partition") or run["partition"]


def main_partition(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    runs = snapshot["runs"]
    return next(
        (r for r in runs if partition_kind(r) == "behavior"), runs[0] if runs else None
    )


def presentation_scores(snapshot: dict[str, Any], exports: dict) -> list:
    from langfuse.api import CreateScoreRequest

    """Copy display labels/counts; never derive a quality metric or create a Trial."""
    main = main_partition(snapshot)
    if main is None:
        return []
    loaded = main["loaded"]
    exported = exports[loaded.sha256]
    stamp = datetime.fromisoformat(loaded.result.finished_at.replace("Z", "+00:00"))
    metadata = {
        "run_id": loaded.result.evaluator_run_id,
        "results_sha256": loaded.sha256,
        "source_sha256": snapshot["source_sha256"],
    }
    items = []
    for trial in exported["trials"]:
        items.append(
            CreateScoreRequest(
                id=stable_id(
                    "dashboard-style-v2",
                    snapshot["source_sha256"],
                    trial["trace_id"],
                    "context.scope",
                ),
                trace_id=trial["trace_id"],
                observation_id=trial["observation_id"],
                name="context.scope",
                value=trial["test_scope"],
                data_type="CATEGORICAL",
                timestamp=stamp,
                metadata={**metadata, "authority": "saved_case_metadata"},
            )
        )
    blocked = snapshot["context"].get("counts", {}).get("blocked")
    if isinstance(blocked, int) and not isinstance(blocked, bool) and blocked >= 0:
        items.append(
            CreateScoreRequest(
                id=stable_id(
                    "dashboard-style-v2", snapshot["source_sha256"], "blocked"
                ),
                trace_id=exported["summary_trace_id"],
                name="delivery.blocked",
                value=blocked,
                data_type="NUMERIC",
                timestamp=stamp,
                metadata={**metadata, "authority": "saved_intake"},
            )
        )
    return items


def widgets(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    main = main_partition(snapshot)
    if main is None:
        return []
    items = []
    prefix = "static · " if partition_kind(main) == "static" else ""
    execution_label = {"static": "静态检查", "behavior": "实际行为执行"}.get(
        partition_kind(main), "已执行案例"
    )

    def add(
        run,
        key,
        title,
        description,
        score,
        view,
        dimensions,
        measure,
        agg,
        chart,
        layout,
        *,
        operator="=",
        extra_filters=None,
    ):
        loaded = run["loaded"]
        filters = [
            {
                "column": "Metadata",
                "key": k,
                "operator": "=",
                "value": v,
                "type": "stringObject",
            }
            for k, v in (
                ("run_id", loaded.result.evaluator_run_id),
                ("results_sha256", loaded.sha256),
            )
        ]
        filters.append(
            {
                "column": "Score Name",
                "operator": operator,
                "value": score,
                "type": "string",
            }
        )
        filters.extend(extra_filters or [])
        config = {"show_value_labels": True} if chart == "HORIZONTAL_BAR" else {}
        if chart == "PIVOT_TABLE":
            config = {"row_limit": 100}
        items.append(
            {
                "key": f"{loaded.sha256}.{key}",
                "layout": layout,
                "spec": {
                    "name": prefix + title,
                    "description": description,
                    "view": view,
                    "dimensions": [{"field": d} for d in dimensions],
                    "metrics": [{"measure": measure, "agg": agg}],
                    "filters": filters,
                    "chart_type": chart,
                    "chart_config": config,
                },
            }
        )

    def scalar(run, field, title, description, layout):
        if getattr(run["loaded"].result.summary, field) is not None:
            add(
                run,
                field,
                title,
                description,
                f"run.{field}",
                "scores-numeric",
                [],
                "value",
                "max",
                "NUMBER",
                layout,
            )

    scalar(
        main,
        "total_cases",
        f"{execution_label} / 例",
        "读取 Inspect 保存的本分区案例数。静态契约检查与行为执行分别展示。",
        (0, 0, 3, 2),
    )
    scalar(
        main,
        "strict_assertion_pass_rate",
        "严格通过率 / %",
        "读取 Inspect 保存的严格通过率；分母为排除 NOT_APPLICABLE 的 Trial，"
        "不代表全包验收通过。",
        (3, 0, 3, 2),
    )
    scalar(
        main,
        "median_latency_ms",
        "典型耗时 / ms",
        "读取 Inspect 保存的单 Trial 中位耗时，不重新聚合，不代表多轮稳定性。",
        (6, 0, 3, 2),
    )
    blocked = snapshot["context"].get("counts", {}).get("blocked")
    inventory_filter = [
        {
            "column": "Metadata",
            "key": "source_sha256",
            "operator": "=",
            "value": snapshot["source_sha256"],
            "type": "stringObject",
        }
    ]
    if isinstance(blocked, int) and not isinstance(blocked, bool) and blocked >= 0:
        reasons = snapshot["context"].get("blocked_reasons", {})
        description = "读取接入账本的未执行数量；不计为通过或 Agent 失败。"
        if reasons:
            description += " " + "；".join(f"{k}: {v}" for k, v in reasons.items())
        add(
            main,
            "delivery.blocked",
            "未执行 / 项",
            description,
            "delivery.blocked",
            "scores-numeric",
            [],
            "value",
            "max",
            "NUMBER",
            (9, 0, 3, 2),
            extra_filters=inventory_filter,
        )
    else:
        scalar(
            main,
            "max_latency_ms",
            "最大耗时 / ms",
            "读取保存的本分区最大耗时；未提供未执行账本时不把缺失数量填为零。",
            (9, 0, 3, 2),
        )
    for key, title, x in (
        ("quality.conclusion", "质量结论 · PASS / FAIL / INCONCLUSIVE", 0),
        ("evaluation.validity", "证据与评测有效性", 6),
    ):
        add(
            main,
            key,
            title,
            "逐 Trial 原始结论分类计数；仅本分区，不重新计算通过率。",
            key,
            "scores-categorical",
            ["stringValue"],
            "count",
            "count",
            "HORIZONTAL_BAR",
            (x, 2, 6, 4),
        )
    add(
        main,
        "assertions",
        "断言结果 · 失败定位",
        "包含成功、失败和未知；断言数量不是失败案例数。仅展示本执行分区。",
        "assertion.",
        "scores-categorical",
        ["name", "stringValue"],
        "count",
        "count",
        "PIVOT_TABLE",
        (0, 6, 7, 5),
        operator="starts with",
    )
    add(
        main,
        "scope",
        "执行范围 · 模块 / 链路 / 端到端",
        "按保存的 test_scope 分类计数；module / link / end_to_end 不代表额外验证闭环。",
        "context.scope",
        "scores-categorical",
        ["stringValue"],
        "count",
        "count",
        "HORIZONTAL_BAR",
        (7, 6, 5, 5),
        extra_filters=inventory_filter,
    )
    y = 11
    for run in snapshot["runs"]:
        if run is main:
            continue
        label = "静态契约检查" if run["partition"] == "static" else run["partition"]
        scalar(
            run,
            "total_cases",
            f"{label} / 例",
            "独立分区的保存计数，不并入上方行为通过率。",
            (0, y, 3, 3),
        )
        scalar(
            run,
            "median_latency_ms",
            f"{label} · 中位耗时 / ms",
            "读取该分区的保存耗时。",
            (3, y, 3, 3),
        )
        add(
            run,
            "quality.conclusion",
            f"{label} · 原始结论",
            "仅本静态/独立分区的原始分类计数，不代表 Agent 行为通过。",
            "quality.conclusion",
            "scores-categorical",
            ["stringValue"],
            "count",
            "count",
            "HORIZONTAL_BAR",
            (6, y, 6, 3),
        )
        y += 3
    return items
