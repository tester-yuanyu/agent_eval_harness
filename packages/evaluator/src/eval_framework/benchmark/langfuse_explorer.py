"""可选 Langfuse 调试面板；仅保存非正式展示汇总与查询配置。"""

from __future__ import annotations

import json
import time
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from langfuse.api import CreateScoreRequest

from ..observability import client_from_env, destination_fingerprint, stable_id
from .langfuse_presentation import _remote_scores, _save
from .report_explorer import ISSUE_LABELS, build_explorer
from .report_trends import load_trend

VERSION = "langfuse-explorer-v1"
PREFIX = "display.v1."
LABELS = {
    "trial_count": "Trial / Trace 数",
    "latency_mean_seconds": "平均延迟 · 秒",
    "latency_p95_seconds": "P95 延迟 · 秒",
    "total_tokens": "总 Token",
    "pass_rate_percent": "通过率 · %",
    "actual_cost_usd": "实际费用 · USD",
}


class _PacedClient:
    """共享节流器：当前托管 API 限额为每分钟 30 次，避免重放写入。"""

    def __init__(self, client, clock=None):
        self._client = client
        self._clock = clock if clock is not None else [0.0]

    def __getattr__(self, name):
        member = getattr(self._client, name)
        if not callable(member):
            return _PacedClient(member, self._clock)

        def call(*args, **kwargs):
            delay = self._clock[0] - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._clock[0] = time.monotonic() + 2.1
            return member(*args, **kwargs)

        return call


def _pass_rate(x):
    total = x["stats"]["trial_count"]
    return (
        100 * sum(g["passed"] for g in x["categories"].values()) / total
        if total
        else None
    )


def summary_payload(explorer, cohort_id, view_id=None):
    view_id = view_id or stable_id(VERSION, explorer["explorer_id"])
    values = {**explorer["stats"], "pass_rate_percent": _pass_rate(explorer)}
    if explorer["estimate"]:
        values.update(
            estimate_low_usd=explorer["estimate"]["low"],
            estimate_high_usd=explorer["estimate"]["high"],
        )
    values.update(
        {
            "family." + k: v["pass_rate_percent"]
            for k, v in explorer["categories"].items()
        }
    )
    payload = []
    for key, value in sorted(values.items()):
        if value is None:
            continue
        payload.append(
            CreateScoreRequest(
                id=stable_id(VERSION, cohort_id, view_id, explorer["source_hash"], key),
                name=PREFIX + key,
                value=value,
                data_type="NUMERIC",
                dataset_run_id=explorer["experiment_id"],
                timestamp=datetime.fromisoformat(
                    explorer["finished_at"].replace("Z", "+00:00")
                ),
                metadata={
                    "formal": False,
                    "scope": "saved_run_display",
                    "cohort_id": cohort_id,
                    "source_hash": explorer["source_hash"],
                    "explorer_id": explorer["explorer_id"],
                    "run_id": explorer["run_id"],
                    "display_version": VERSION,
                    "view_id": view_id,
                },
                comment=(
                    "保存证据的展示汇总，非正式评分；延迟按 trial，"
                    "缓存为输入子集，估算不是实付。"
                ),
            )
        )
    return payload


def _scope(key, value):
    return {
        "column": "metadata",
        "key": key,
        "type": "stringObject",
        "operator": "=",
        "value": value,
    }


def _spec(
    name, desc, view, chart, filters, dimensions=None, measure="value", agg="avg"
):
    return {
        "name": name,
        "description": desc,
        "view": view,
        "chart_type": chart,
        "chart_config": {
            "type": chart,
            **({"bins": 10} if chart == "HISTOGRAM" else {}),
        },
        "filters": filters,
        "dimensions": dimensions or [],
        "metrics": [{"measure": measure, "agg": agg}],
    }


def explorer_widgets(x, cohort_id, view_id=None):
    result = []
    source = _scope("source_hash", x["source_hash"])
    cohort = _scope("cohort_id", cohort_id)
    version = _scope("display_version", VERSION)
    snapshot = _scope("view_id", view_id or stable_id(VERSION, x["explorer_id"]))

    def score_filter(names):
        return {
            "column": "name",
            "type": "stringOptions",
            "operator": "any of",
            "value": names,
        }

    def add(key, spec, width=6, height=5):
        result.append({"key": key, "spec": spec, "width": width, "height": height})

    if "evaluation" in x:
        from .dashboard_evaluation import cards

        for key, label, desc in cards(x["evaluation"]):
            if x["stats"].get("evaluation." + key) is None:
                continue
            add(
                "evaluation:" + key,
                _spec(
                    label,
                    desc,
                    "scores-numeric",
                    "NUMBER",
                    [
                        source,
                        cohort,
                        version,
                        snapshot,
                        score_filter([PREFIX + "evaluation." + key]),
                    ],
                ),
                4,
                3,
            )
    for key, label in LABELS.items():
        if "evaluation" in x and key != "trial_count":
            continue
        value = _pass_rate(x) if key == "pass_rate_percent" else x["stats"].get(key)
        if value is None:
            continue
        desc = "从保存的 trial 聚合；不包含补跑，不混入子事件。"
        if key == "latency_p95_seconds":
            desc += "分位数沿用 HTML 的排序取值口径，小样本仅描述本轮。"
        if key == "pass_rate_percent":
            passed = sum(g["passed"] for g in x["categories"].values())
            label = f"通过率 {value:.1f}%"
            desc = f"{passed}/{x['stats']['trial_count']} PASS；INVALID 保留在分母。"
        add(
            "health:" + key,
            _spec(
                label,
                desc,
                "scores-numeric",
                "NUMBER",
                [source, cohort, version, snapshot, score_filter([PREFIX + key])],
            ),
            4,
            3,
        )
    if x["estimate"] and x["stats"].get("actual_cost_usd") is None:
        e = x["estimate"]
        label = (
            "额度价值估算"
            if e["pricing"]["kind"] == "subscription_allowance"
            else "目录价值估算"
        )
        add(
            "health:estimate",
            _spec(
                f"估算费用下限 ${e['low']:.5f}",
                f"{label} ${e['low']:.8f}–${e['high']:.8f}；非实际扣费。"
                "实际成本缺失，不能视作 $0。",
                "scores-numeric",
                "NUMBER",
                [
                    source,
                    cohort,
                    version,
                    snapshot,
                    score_filter([PREFIX + "estimate_low_usd"]),
                ],
            ),
            4,
            3,
        )
    trends = [
        (
            "latency",
            "P50 / P95 延迟趋势 · 秒",
            ["latency_p50_seconds", "latency_p95_seconds"],
        ),
        (
            "tokens",
            "输入 / 输出 / 缓存趋势 · Token",
            ["input_tokens", "output_tokens", "cached_input_tokens"],
        ),
    ]
    if x["stats"].get("actual_cost_usd") is not None:
        trends.append(("cost", "实际费用趋势 · USD", ["actual_cost_usd"]))
    elif x["estimate"]:
        trends.append(
            (
                "cost",
                "额度/目录价值估算趋势 · USD（非实际扣费）",
                ["estimate_low_usd", "estimate_high_usd"],
            )
        )
    for key, label, names in [] if "evaluation" in x else trends:
        add(
            "trend:" + key,
            _spec(
                label,
                "每 run 一组保存值；同口径分组，自动时间分桶，同桶为各 run 等权均值。"
                "仅一轮是基线。缓存包含在输入内，不再次加总。",
                "scores-numeric",
                "LINE_TIME_SERIES",
                [cohort, version, snapshot, score_filter([PREFIX + n for n in names])],
                [{"field": "name"}],
            ),
        )
    add(
        "families",
        _spec(
            "按任务族通过率 · %",
            "PASS / 全部 trial，INVALID 留在分母。任务族入口可下钻；不新增正式判定。",
            "scores-numeric",
            "HORIZONTAL_BAR",
            [
                source,
                cohort,
                version,
                snapshot,
                score_filter([PREFIX + "family." + name for name in x["categories"]]),
            ],
            [{"field": "name"}],
        ),
    )
    for d in x["drilldowns"]:
        label = ISSUE_LABELS.get(d["name"], d["name"])
        if d["kind"] == "category":
            g = x["categories"][d["name"]]
            rate = round(g["pass_rate_percent"], 1)
            label += f" · {g['passed']}/{g['total']} 通过（{rate:g}%）"
        add(
            d["kind"] + ":" + d["name"],
            _spec(
                ("用例数 · " if "evaluation" in x else "") + label + " · 下钻",
                "View as table → 对应用例 Trace；数字为用例数，问题类别可重叠。",
                "observations",
                "NUMBER",
                [
                    _scope("category", d["name"])
                    if d["kind"] == "category"
                    else {
                        "column": "name",
                        "type": "stringOptions",
                        "operator": "any of",
                        "value": d.get("root_names", d["case_ids"]),
                    },
                    _scope("results_sha256", x["source_hash"]),
                    {
                        "column": "type",
                        "type": "stringOptions",
                        "operator": "any of",
                        "value": ["AGENT"],
                    },
                ],
                measure="count",
                agg="count",
            ),
            4,
            3,
        )
    selected = [
        n
        for n in ("intent_match", "tool_args_match", "status_match")
        if n in x["formal_metrics"]
    ]
    if not selected:
        selected = sorted(x["formal_metrics"])[:3]
    for name in selected:
        if name not in x.get("histogram_eligible", x["formal_metrics"]):
            continue
        discrete = len(set(x["formal_metrics"][name]["values"])) <= 20
        add(
            "scores:" + name,
            _spec(
                "正式 Score 分布 · " + name,
                "保存的 DeepEval 正式指标，"
                f"适用样本数 {x['formal_metrics'][name]['count']}；"
                "缺失不计通过。"
                + (
                    "按原始分值精确计数。"
                    if discrete
                    else "平台近似分桶，频数可能非整数；精确值见调试页。"
                ),
                "scores-numeric",
                "HORIZONTAL_BAR" if discrete else "HISTOGRAM",
                [_scope("results_sha256", x["source_hash"]), score_filter([name])],
                dimensions=[{"field": "value"}] if discrete else [],
                measure="count" if discrete else "value",
                agg="count" if discrete else "histogram",
            ),
            4,
            5,
        )
    return result


def arrange_widgets(dashboard_id, original, extras, ids, category_order=()):
    """12 列网格，按全局、拆分、趋势、诊断、定位、指标排列。"""
    items = []
    active = {e["key"] for e in extras}

    def put(wid, x, y, width, height):
        items.append(
            {
                "type": "widget",
                "id": stable_id(VERSION, dashboard_id, wid),
                "widget_id": wid,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
            }
        )

    def row(keys, y, width, height):
        for index, key in enumerate(keys):
            put(
                ids[key],
                index % (12 // width) * width,
                y + index // (12 // width) * height,
                width,
                height,
            )

    if any(k.startswith("evaluation:") for k in active):
        # Reuse the same widget definitions and grid; one-run v4 has no fake trend.
        keys = (["health:trial_count"] if "health:trial_count" in active else []) + [
            e["key"] for e in extras if e["key"].startswith("evaluation:")
        ]
        row(keys, 0, 4, 3)
        y = ((len(keys) + 2) // 3) * 3
        if len(original) > 2:
            put(original[2], 0, y, 12, 5)
            y += 5
        details = [
            e["key"] for e in extras if e["key"].startswith(("issue:", "category:"))
        ]
        row(details, y, 4, 3)
        y += ((len(details) + 2) // 3) * 3
        row([e["key"] for e in extras if e["key"].startswith("scores:")], y, 4, 5)
        return items
    health_order = [
        "trial_count",
        "pass_rate_percent",
        "latency_mean_seconds",
        "latency_p95_seconds",
        "total_tokens",
        "estimate",
        "actual_cost_usd",
    ]
    health = ["health:" + k for k in health_order if "health:" + k in active]
    row(health, 0, 2, 2)
    y = max(1, (len(health) + 5) // 6) * 2
    # 通过率已在首行展示，保留旧 donut 资产但不重复放入布局。
    if len(original) > 1:
        put(original[1], 0, y, 12, 5)
    y += 5
    trend_keys = [
        k for k in ("trend:latency", "trend:tokens", "trend:cost") if k in active
    ]
    trend_ids = ([original[3]] if len(original) > 3 else []) + [
        ids[k] for k in trend_keys
    ]
    for index, wid in enumerate(trend_ids):
        put(wid, index * 3, y, 3, 6)
    y += 6
    if len(original) > 2:
        put(original[2], 0, y, 8, 6)
    issue_order = [
        "schema_mismatch",
        "missing_confirmation_context",
        "business_failure_status",
        "restricted_response",
    ]
    issues = sorted(
        [k for k in active if k.startswith("issue:")],
        key=lambda k: (
            issue_order.index(k[6:]) if k[6:] in issue_order else len(issue_order),
            k,
        ),
    )
    for index, key in enumerate(issues):
        put(ids[key], 8 + index % 2 * 2, y + index // 2 * 3, 2, 3)
    y += max(6, (len(issues) + 1) // 2 * 3)
    categories = sorted(
        [k for k in active if k.startswith("category:")],
        key=lambda k: (
            category_order.index(k[9:])
            if k[9:] in category_order
            else len(category_order),
            k,
        ),
    )
    row(categories, y, 2, 4)
    y += max(1, (len(categories) + 5) // 6) * 4
    score_order = ["status_match", "intent_match", "tool_args_match"]
    scores = sorted(
        [k for k in active if k.startswith("scores:")],
        key=lambda k: (
            score_order.index(k[7:]) if k[7:] in score_order else len(score_order),
            k,
        ),
    )
    row(scores, y, 4, 5)
    return items


def preserve_unmanaged(current, items, managed):
    others = [dict(w) for w in current["widgets"] if w.get("widget_id") not in managed]
    if others:
        offset = max((w["y"] + w["height"] for w in items), default=0) - min(
            w["y"] for w in others
        )
        for w in others:
            w["y"] += offset
    return {**current, "widgets": items + others}


def sync_summaries(root, explorers, cohort_id, client, *, destination=None):
    destination = destination or destination_fingerprint()
    path = root / "langfuse_explorer_export.json"
    state = (
        json.loads(path.read_text())
        if path.exists()
        else {
            "version": VERSION,
            "destination": destination,
            "cohort_id": cohort_id,
            "submitted": [],
        }
    )
    if state["destination"] != destination or state["cohort_id"] != cohort_id:
        raise ValueError("explorer destination/cohort changed")
    view_id = stable_id(VERSION, *sorted(x["explorer_id"] for x in explorers))
    if state.get("view_id") != view_id and path.exists():
        _save(
            root
            / "langfuse-explorer-history"
            / f"{sha256(path.read_bytes()).hexdigest()}.json",
            state,
        )
    state["view_id"] = view_id
    payload = [s for x in explorers for s in summary_payload(x, cohort_id, view_id)]
    ids = [s.id for s in payload]
    found = _remote_scores(client, ids)
    missing = [s for s in payload if s.id not in found]
    if not any(s.id in state["submitted"] for s in missing):
        for start in range(0, len(missing), 100):
            batch = missing[start : start + 100]
            state["submitted"] = sorted(set(state["submitted"]) | {s.id for s in batch})
            state["status"] = "AWAITING_READBACK"
            _save(path, state)
            response = client.scores.create(
                request=batch, request_options={"max_retries": 0}
            )
            if (
                getattr(response, "errors", None)
                or getattr(response, "rejected", 0)
                or getattr(response, "accepted", len(batch)) != len(batch)
            ):
                raise ValueError("display summary rejected")
        found = _remote_scores(client, ids)
    errors = []
    for s in payload:
        if s.id not in found:
            errors.append(s.id)
            continue
        row = found[s.id]
        subject = row.get("subject") or {}
        meta = row.get("metadata") or {}
        if (
            row.get("name") != s.name
            or row.get("value") != s.value
            or subject.get("kind") != "experiment"
            or subject.get("id") != s.dataset_run_id
            or any(meta.get(k) != v for k, v in s.metadata.items())
        ):
            raise ValueError("existing display summary content mismatch: " + s.id)
    state.update(
        status="VERIFIED" if not errors else "AWAITING_READBACK",
        errors=errors,
        score_ids=ids,
        summary_count=len(ids),
        explorer_ids=[x["explorer_id"] for x in explorers],
    )
    _save(path, state)
    return state


def observation_ids(client, filters):
    """Verify whole populations, including the 233-case Schema group."""
    result, cursor, cursors = set(), None, set()
    while True:
        response = client.observations.get_many(
            limit=100,
            fields="core,basic",
            filter=json.dumps(filters),
            **({"cursor": cursor} if cursor else {}),
        )
        result.update(row.id for row in response.data)
        cursor = response.meta.cursor if response.meta else None
        if not cursor:
            return result
        if cursor in cursors:
            raise ValueError("Repeated observation cursor")
        cursors.add(cursor)


def sync_explorer(run_dir, run_dirs, *, client=None, destination=None):
    destination = destination or destination_fingerprint()
    root = Path(run_dir)
    trend = load_trend(run_dirs)
    explorers = [build_explorer(p) for p in run_dirs]
    if any(x["destination"] != destination for x in explorers):
        raise ValueError("explorer destination mismatch")
    client = client if client is not None else _PacedClient(client_from_env())
    state = sync_summaries(
        root, explorers, trend["cohort_id"], client, destination=destination
    )
    if state["status"] != "VERIFIED":
        return state
    x = next(
        x
        for x in explorers
        if x["run_id"] == json.loads((root / "results.json").read_text())["run_id"]
    )
    dashboard = json.loads((root / "langfuse_dashboard.json").read_text())
    if dashboard["status"] != "VERIFIED" or dashboard["destination"] != destination:
        raise ValueError("verified dashboard required")
    did = dashboard["dashboard_id"]
    path = root / "langfuse_explorer_dashboard.json"
    ui = (
        json.loads(path.read_text())
        if path.exists()
        else {
            "dashboard_id": did,
            "destination": destination,
            "widgets": {},
        }
    )
    if ui["dashboard_id"] != did or ui["destination"] != destination:
        raise ValueError("dashboard destination changed")
    if path.exists():
        _save(
            root
            / "langfuse-dashboard-history"
            / f"{sha256(path.read_bytes()).hexdigest()}.json",
            ui,
        )
    # 读取原根名，兼容历史 case_id 命名和首次导出的增强命名。
    root_ids = sorted({t["root_id"] for t in x["trials"]})
    names = {}
    for start in range(0, len(root_ids), 100):
        batch = root_ids[start : start + 100]
        response = client.observations.get_many(
            limit=100,
            fields="core,basic",
            filter=json.dumps(
                [
                    {
                        "column": "id",
                        "type": "stringOptions",
                        "operator": "any of",
                        "value": batch,
                    }
                ]
            ),
        )
        if {r.id for r in response.data} != set(batch):
            raise ValueError("root observation coverage mismatch")
        names.update({r.id: r.name for r in response.data})
    for d in x["drilldowns"]:
        d["root_names"] = sorted({names[rid] for rid in d["root_ids"]})
    specs = explorer_widgets(x, trend["cohort_id"], state["view_id"])
    for entry in specs:
        spec = entry["spec"]
        if entry["key"].startswith(("issue:", "category:")):
            expected_ids = next(
                d["root_ids"]
                for d in x["drilldowns"]
                if d["kind"] + ":" + d["name"] == entry["key"]
            )
            if observation_ids(client, spec["filters"]) != set(expected_ids):
                raise ValueError("widget filters do not resolve exact roots")
        if entry["key"].startswith("scores:"):
            name = entry["key"].split(":", 1)[1]
            remote, cursor = [], None
            while True:
                response = client.scores.get_many(
                    name=name, limit=100, fields="subject,details", cursor=cursor
                )
                remote.extend(
                    r
                    for r in response.data
                    if (r.metadata or {}).get("results_sha256") == x["source_hash"]
                )
                cursor = response.meta.cursor if response.meta else None
                if not cursor:
                    break
            expected = x["formal_metrics"][name]
            if sorted(r.value for r in remote) != sorted(expected["values"]) or any(
                (r.metadata or {}).get("metric", {}).get("formal") is not True
                or (r.metadata or {}).get("metric", {}).get("status") != "SCORED"
                for r in remote
            ):
                raise ValueError("formal histogram remote population mismatch")
    available = client.unstable.dashboard_widgets.list(limit=100).data
    for entry in specs:
        key = entry["key"]
        spec = {
            **entry["spec"],
            "description": entry["spec"]["description"] + " Run: " + x["run_id"],
        }
        existing = next((w for w in available if w.id == ui["widgets"].get(key)), None)
        if existing is not None:
            expected = type(existing).model_validate({**existing.model_dump(), **spec})
            if all(
                existing.model_dump().get(k) == expected.model_dump().get(k)
                for k in spec
            ):
                continue
        if key in ui["widgets"]:
            widget = client.unstable.dashboard_widgets.update(
                ui["widgets"][key], **spec, request_options={"max_retries": 0}
            )
        else:
            matches = [
                w
                for w in available
                if w.name == spec["name"] and w.description == spec["description"]
            ]
            if len(matches) > 1:
                raise ValueError("duplicate explorer widget names")
            widget = (
                matches[0]
                if matches
                else client.unstable.dashboard_widgets.create(
                    **spec, request_options={"max_retries": 0}
                )
            )
            ui["widgets"][key] = widget.id
            ui["status"] = "UPDATING"
            _save(path, ui)
        actual = client.unstable.dashboard_widgets.get(widget.id)
        expected = type(actual).model_validate({**actual.model_dump(), **spec})
        if any(actual.model_dump()[k] != expected.model_dump()[k] for k in spec):
            raise ValueError("explorer widget readback mismatch")
    from langfuse.api.unstable.dashboards.types.dashboard_definition import (
        DashboardDefinition,
    )

    current = client.unstable.dashboards.get(did).definition.model_dump()
    _save(
        root
        / "langfuse-dashboard-history"
        / (sha256(json.dumps(current, sort_keys=True).encode()).hexdigest() + ".json"),
        current,
    )
    managed = set(dashboard["widgets"]) | set(ui["widgets"].values())
    layout_path = root / "report-dashboard.json"
    layout = json.loads(layout_path.read_text()) if layout_path.exists() else {}
    items = arrange_widgets(
        did,
        dashboard["widgets"],
        specs,
        ui["widgets"],
        layout.get("task_group_order", []),
    )
    definition = DashboardDefinition.model_validate(
        preserve_unmanaged(current, items, managed)
    )
    client.unstable.dashboards.update(
        did,
        definition=definition,
        description=(
            "评测健康度 → 失败分类下钻（菜单 View as table）→ 任务族与正式评分。"
            "费用估算与实付分开；多 run 必须同口径。"
        ),
        request_options={"max_retries": 0},
    )
    if (
        client.unstable.dashboards.get(did).definition.model_dump()
        != definition.model_dump()
    ):
        raise ValueError("explorer layout readback mismatch")
    ui.update(
        status="VERIFIED",
        explorer_id=x["explorer_id"],
        definitions=specs,
        visible_widget_ids=[w["widget_id"] for w in items],
        layout_version="reading-order-v2",
        url=dashboard["url"],
    )
    _save(path, ui)
    return {**state, "dashboard_status": ui["status"], "dashboard_url": ui["url"]}


def verify_display_metrics(run_dir, *, client):
    """Read the actual chart aggregates; correct widget JSON alone is insufficient."""
    import math
    from datetime import UTC

    root = Path(run_dir)
    x = build_explorer(root)
    state = json.loads((root / "langfuse_explorer_export.json").read_text())
    if state["status"] != "VERIFIED":
        raise ValueError("Verified display summaries required")
    payload = summary_payload(x, state["cohort_id"], state["view_id"])
    expected = {s.name: s.value for s in payload}
    query = {
        "view": "scores-numeric",
        "dimensions": [{"field": "name"}],
        "metrics": [
            {"measure": "value", "aggregation": "avg"},
            {"measure": "count", "aggregation": "count"},
        ],
        "filters": [
            _scope("source_hash", x["source_hash"]),
            _scope("cohort_id", state["cohort_id"]),
            _scope("view_id", state["view_id"]),
            {
                "column": "name",
                "type": "stringOptions",
                "operator": "any of",
                "value": list(expected),
            },
        ],
        "fromTimestamp": datetime.fromtimestamp(
            x["date_range"][0] / 1000, UTC
        ).isoformat(),
        "toTimestamp": datetime.fromtimestamp(
            x["date_range"][1] / 1000, UTC
        ).isoformat(),
        "config": {"row_limit": 1000},
    }
    rows = client.metrics.metrics(
        query=json.dumps(query), request_options={"max_retries": 0}
    ).data
    actual = {r.get("name"): r for r in rows}
    errors = []
    for name, value in expected.items():
        row = actual.get(name, {})
        mean = row.get("avg_value")
        if (
            row.get("count_count") != 1
            or type(mean) not in (int, float)
            or not math.isclose(mean, value, rel_tol=1e-9, abs_tol=1e-9)
        ):
            errors.append(name)
    if len(actual) != len(rows) or set(actual) != set(expected):
        errors.append("population_mismatch")
    result = {
        "status": "VERIFIED" if not errors else "MISMATCH",
        "source_hash": x["source_hash"],
        "view_id": state["view_id"],
        "expected": expected,
        "actual": rows,
        "errors": errors,
    }
    _save(root / "langfuse_dashboard_metrics.json", result)
    return result
