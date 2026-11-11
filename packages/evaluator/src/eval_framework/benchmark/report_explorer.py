"""独立离线调试索引；保存结果为唯一正式判定来源。"""

# HTML/CSS 保持可读的模板行。
# ruff: noqa: E501
from __future__ import annotations

import hashlib
import html
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from urllib.parse import quote

from ..aggregator import evidence_summary
from .report_diagnostics import build_diagnostics, canonical
from .report_insights import estimate_cost, report_usage, token_parts
from .report_links import load_links, safe_base

VERSION = "report-explorer-v1"
ISSUE_LABELS = {
    "schema_mismatch": "字段契约偏差",
    "missing_confirmation_context": "确认上下文缺口",
    "business_failure_status": "业务失败状态不一致",
    "restricted_response": "受限回复 / InvalidModelOutputError",
}


def known_sum(values):
    return (
        sum(values)
        if values
        and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values)
        else None
    )


def summarize(run, analysis, usages, estimate):
    rows = run["trials"]
    if len(usages) != len(rows):
        raise ValueError("usage coverage differs")
    diagnostics = {(d["case_id"], d["trial"]): d for d in analysis["trials"]}
    if len(diagnostics) != len(rows) or set(diagnostics) != {
        (r["case_id"], r["trial"]) for r in rows
    }:
        raise ValueError("diagnostic trial coverage differs")
    parts = [token_parts(u) for u in usages]
    complete = bool(parts) and all(p is not None for p in parts)
    latency = [r.get("latency_seconds") for r in rows]
    latency_known = known_sum(latency) is not None
    summary = evidence_summary(run)
    tools = [
        sum(e.get("type") == "tool" for e in r["observation"].get("events", []))
        if r["observation"].get("evidence_complete") is True
        and "events" in r["observation"]
        else None
        for r in rows
    ]
    tool_total = known_sum(tools)
    stats = {
        "trial_count": len(rows),
        "latency_mean_seconds": mean(latency) if latency_known else None,
        "latency_p50_seconds": median(latency) if latency_known else None,
        "latency_p95_seconds": summary["latency_p95"] if latency_known else None,
        "input_tokens": sum(p[0] + p[1] for p in parts) if complete else None,
        "noncached_input_tokens": sum(p[0] for p in parts) if complete else None,
        "cached_input_tokens": sum(p[1] for p in parts) if complete else None,
        "output_tokens": known_sum([u.get("output_tokens") for u in usages]),
        "total_tokens": known_sum([u.get("total_tokens") for u in usages]),
        "tool_calls_total": tool_total,
        "tool_calls_mean": tool_total / len(rows)
        if tool_total is not None and rows
        else None,
        "actual_cost_usd": summary["usage"]["cost_usd"]["total"],
    }
    issues, categories, metrics, trials = {}, {}, {}, []
    for r in rows:
        key = (r["case_id"], r["trial"])
        d = diagnostics[key]
        if d["verdict"] != r["assessment"]["verdict"]:
            raise ValueError("saved verdict mismatch")
        kinds = sorted({f["kind"] for f in d["findings"]})
        trial = {
            "case_id": key[0],
            "trial": key[1],
            "category": d["category"],
            "operation": d["operation"],
            "verdict": d["verdict"],
            "issues": kinds,
            "latency_seconds": r.get("latency_seconds"),
        }
        trials.append(trial)
        for kind in kinds:
            issues.setdefault(kind, []).append(trial)
        categories.setdefault(d["category"], []).append(trial)
        for m in r["assessment"].get("metrics", []):
            if (
                m.get("formal") is True
                and m.get("status") == "SCORED"
                and type(m.get("score")) in (float, int)
                and math.isfinite(m["score"])
            ):
                metrics.setdefault(m["name"], {"count": 0, "values": []})
                metrics[m["name"]]["count"] += 1
                metrics[m["name"]]["values"].append(m["score"])
    unsafe = {
        m["name"]
        for r in rows
        for m in r["assessment"].get("metrics", [])
        if m.get("score") is not None
        and (m.get("formal") is not True or m.get("status") != "SCORED")
    }
    return {
        "histogram_eligible": sorted(set(metrics) - unsafe),
        "version": VERSION,
        "formal": False,
        "run_id": run["run_id"],
        "source_hash": analysis["source_hash"],
        "analysis_id": analysis["analysis_id"],
        "finished_at": run["finished_at"],
        "stats": stats,
        "estimate": estimate,
        "formal_metrics": metrics,
        "issues": issues,
        "trials": trials,
        "categories": {
            name: {
                "total": len(group),
                "passed": sum(t["verdict"] == "PASS" for t in group),
                "pass_rate_percent": 100
                * sum(t["verdict"] == "PASS" for t in group)
                / len(group),
                "trials": group,
            }
            for name, group in sorted(categories.items())
        },
    }


def observation_url(base, project, root_ids, date_range):
    ids = sorted(set(root_ids))
    if not ids or any(not isinstance(i, str) or not i for i in ids):
        raise ValueError("empty observation set")
    escaped = [i.replace("\\", "\\\\").replace("|", "\\|") for i in ids]
    encoded = "id;stringOptions;;any of;" + quote("|".join(escaped), safe="")
    if len(encoded) > 4000:
        raise ValueError("exact filter exceeds URL budget; never drop filters")
    return (
        f"{safe_base(base)}/project/{quote(project, safe='')}/observations?filter="
        f"{quote(encoded, safe='')}&dateRange={date_range[0]}-{date_range[1]}"
    )


def build_explorer(run_dir):
    root = Path(run_dir)
    run = json.loads((root / "results.json").read_text())
    analysis = build_diagnostics(root)
    usages, sources, warnings = report_usage(root, run)
    pricing = (
        json.loads((root / "report-pricing.json").read_text())
        if (root / "report-pricing.json").exists()
        else None
    )
    result = summarize(run, analysis, usages, estimate_cost(run, usages, pricing))
    result.update(usage_sources=sources, warnings=warnings)
    if run.get("identity", {}).get("dataset", {}).get("task_contract") == "builder-full-benchmark-v1":
        from .dashboard_evaluation import display_statistics
        from .report_evaluation import evaluation_summary
        from .report_insights import load_report_tasks
        tasks, task_warnings = load_report_tasks(run)
        if task_warnings or len(tasks) < len(run["planned_case_ids"]):
            raise ValueError("v4 dashboard requires verified complete task definitions")
        result["evaluation"] = evaluation_summary(run, tasks)
        result["stats"].update({"evaluation." + k: v for k, v in display_statistics(result["evaluation"]).items()})

    links = load_links(root)
    if len(links) != len(run["trials"]):
        raise ValueError("explorer requires verified complete Trace links")
    receipt = json.loads((root / "langfuse_export.json").read_text())
    saved = json.loads((root / "report-links.json").read_text())
    traces = {(t["case_id"], t["trial"]): t for t in receipt["traces"]}
    times = [
        datetime.fromisoformat(r[k].replace("Z", "+00:00")).timestamp()
        for r in run["trials"]
        for k in ("started_at", "finished_at")
    ]
    result["date_range"] = [
        int(min(times) * 1000) - 1000,
        int(max(times) * 1000) + 1000,
    ]
    result["base_url"], result["project_id"] = saved["base_url"], saved["project_id"]
    result["destination"] = receipt["destination"]
    experiments = {t["experiment_id"] for t in traces.values()}
    if len(experiments) != 1:
        raise ValueError("explorer requires one experiment per run")
    result["experiment_id"] = next(iter(experiments))
    for t in result["trials"]:
        remote = traces[(t["case_id"], t["trial"])]
        t.update(
            root_id=remote["root_id"],
            trace_id=remote["trace_id"],
            url=links[(t["case_id"], t["trial"])],
        )
    result["drilldowns"] = []
    for kind, groups in [
        ("issue", result["issues"]),
        ("category", result["categories"]),
    ]:
        for name, group in sorted(groups.items()):
            members = group if kind == "issue" else group["trials"]
            ids = sorted({t["root_id"] for t in members})
            try:
                url = observation_url(
                    saved["base_url"], saved["project_id"], ids, result["date_range"]
                )
            except ValueError:
                url = None
            result["drilldowns"].append(
                {
                    "kind": kind,
                    "name": name,
                    "count": len(members),
                    "root_ids": ids,
                    "case_ids": sorted({t["case_id"] for t in members}),
                    "trace_ids": sorted({t["trace_id"] for t in members}),
                    "url": url,
                }
            )
    result["explorer_id"] = hashlib.sha256(canonical(result)).hexdigest()
    return result


def write_explorer(run_dir):
    root = Path(run_dir)
    x = build_explorer(root)
    (root / "explorer.json").write_text(
        json.dumps(x, ensure_ascii=False, indent=2) + "\n"
    )

    def esc(v):
        return html.escape(str(v), quote=True)

    def fmt(v):
        return "未知" if v is None else f"{v:,.4f}".rstrip("0").rstrip(".")

    stats = x["stats"]
    est = x["estimate"]
    cards = [
        ("Trial / Trace 数", stats["trial_count"]),
        ("平均延迟 · 秒", stats["latency_mean_seconds"]),
        ("P95 · 秒", stats["latency_p95_seconds"]),
        ("总 Token", stats["total_tokens"]),
        ("平均工具调用", stats["tool_calls_mean"]),
        ("实际费用 · USD", stats["actual_cost_usd"]),
    ]
    parts = [
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>评测调试入口</title><style>body{font:15px/1.7 system-ui;color:#18263e;background:#f3f6fc;max-width:1240px;margin:30px auto;padding:0 20px}h1{font-size:30px}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.card,section{background:white;border:1px solid #dce5f2;padding:18px;border-radius:12px;margin:14px 0}.card strong{display:block;font-size:30px;color:#2458a0}a{color:#175fc2}button,select{padding:9px;border:1px solid #bfcde0;border-radius:7px;background:white;cursor:pointer;margin:5px}button.active{background:#e4eeff}table{width:100%;border-collapse:collapse}td,th{padding:10px;text-align:left;border-bottom:1px solid #e5eaf0}.muted{color:#5a687b}.fail{color:#b32336}@media(max-width:650px){.cards{grid-template-columns:1fr 1fr}table{font-size:12px}td,th{padding:5px}}</style><h1>评测调试入口</h1>',
        f'<p>{esc(x["run_id"])} · <a href="report.html">完整报告</a> · <a href="explorer.json">汇总与精确 Trace 集合</a></p><div class="cards">',
    ]
    parts.extend(
        f'<div class="card">{esc(k)}<strong>{fmt(v)}</strong></div>' for k, v in cards
    )
    parts.append(
        '</div><p class="muted">延迟取每条 trial 的完整执行耗时，P95 沿用报告口径；不混入子事件。缓存读取是输入的一部分。未知费用不按零计算。</p>'
    )
    if est:
        parts.append(
            f"<p>额度/目录价值估算：USD {est['low']:.8f}–{est['high']:.8f}，非实际扣费；价格口径：{esc(est['pricing']['kind'])}。</p>"
        )
    parts.append(
        '<section><h2>从问题定位 Trace</h2><p>点击分类筛选下方用例；“Langfuse 列表”按根节点 ID 精确定位，进入任一记录即可查看完整 Trace。类别可重叠。</p><button data-kind="all" data-name="">全部用例</button>'
    )
    for d in x["drilldowns"]:
        name = ISSUE_LABELS.get(d["name"], d["name"])
        count = d["count"]
        if d["kind"] == "category":
            g = x["categories"][d["name"]]
            name += f" · {g['passed']}/{g['total']}（{g['pass_rate_percent']:g}%）"
        parts.append(
            f'<div><button data-kind="{d["kind"]}" data-name="{esc(d["name"])}">{esc(name)} · {count} 条</button>'
        )
        if d["url"]:
            parts.append(
                f'<a href="{esc(d["url"])}" target="_blank" rel="noopener">Langfuse 列表 ↗</a>'
            )
        parts.append("</div>")
    parts.append(
        '</section><section><h2 id="selection">全部用例</h2><table><thead><tr><th>用例</th><th>任务族</th><th>结果</th><th>延迟</th><th>证据</th></tr></thead><tbody>'
    )
    for t in x["trials"]:
        parts.append(
            f'<tr class="trial" data-category="{esc(t["category"])}" data-issues="{esc(json.dumps(t["issues"]))}"><td>{esc(t["case_id"])} / {t["trial"]}</td><td>{esc(t["category"])}</td><td class="{"fail" if t["verdict"] != "PASS" else ""}">{esc(t["verdict"])}</td><td>{fmt(t["latency_seconds"])}s</td><td><a href="{esc(t["url"])}" target="_blank" rel="noopener">完整 Trace ↗</a></td></tr>'
        )
    parts.append(
        "</tbody></table></section><section><h2>已有正式 Score 分布</h2><p>仅展示保存的 SCORED 正式指标，各项分母为其适用样本数，不把缺失项视为通过。</p><table><tr><th>指标</th><th>适用数</th><th>分值分布</th></tr>"
    )
    for name, m in sorted(x["formal_metrics"].items()):
        parts.append(
            f"<tr><td>{esc(name)}</td><td>{m['count']}</td><td>{esc(dict(sorted(Counter(m['values']).items())))}</td></tr>"
        )
    parts.append(
        """</table></section><script>document.querySelectorAll('button[data-kind]').forEach(b=>b.onclick=()=>{let count=0;document.querySelectorAll('tr.trial').forEach(r=>{let show=b.dataset.kind==='all'||(b.dataset.kind==='category'?r.dataset.category===b.dataset.name:JSON.parse(r.dataset.issues).includes(b.dataset.name));r.hidden=!show;if(show)count++;});document.getElementById('selection').textContent=b.textContent+' · 显示 '+count+' 条';document.querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));});</script></html>"""
    )
    (root / "explorer.html").write_text("".join(parts))
    return root / "explorer.html"
