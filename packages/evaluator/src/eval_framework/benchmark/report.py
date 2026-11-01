"""Standalone, network-free reports rendered only from saved trial evidence."""

# HTML/CSS template literals intentionally retain their natural markup width.
# ruff: noqa: E501

from __future__ import annotations

import difflib
import hashlib
import html
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _number(value: Any) -> str:
    if value is None:
        return "未知"
    return f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"


def _percent(numerator: int, denominator: int) -> str:
    return f"{100 * numerator / denominator:.1f}%" if denominator else "—"


def _usage_total(rows: list[dict], aliases: tuple[str, ...]) -> dict:
    values = []
    for row in rows:
        usage = row.get("observation", {}).get("usage", {})
        value = next(
            (usage[key] for key in aliases if isinstance(usage.get(key), (int, float))),
            None,
        )
        values.append(value)
    known = [value for value in values if value is not None]
    return {
        "total": sum(known) if known and len(known) == len(rows) else None,
        "known_subtotal": sum(known) if known else None,
        "known_trials": len(known),
    }


def evidence_summary(run: dict) -> dict:
    """Aggregate saved verdicts, without rerunning a metric or an Agent."""
    rows = run["trials"]
    planned_ids = run["planned_case_ids"]
    repeats = run["trials_per_case"]
    if len(planned_ids) != len(set(planned_ids)) or repeats < 1:
        raise ValueError("invalid planned case selection")
    observed_keys = [(row["case_id"], row["trial"]) for row in rows]
    if len(observed_keys) != len(set(observed_keys)):
        raise ValueError("duplicate saved case/trial evidence")
    expected_keys = {
        (case_id, trial) for case_id in planned_ids for trial in range(1, repeats + 1)
    }
    if not set(observed_keys) <= expected_keys:
        raise ValueError("saved trial is outside the planned selection")
    counts = Counter(row["assessment"]["verdict"] for row in rows)
    valid = sum(row["assessment"].get("validity") == "VALID" for row in rows)
    planned = len(expected_keys)
    cases: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        cases[row["case_id"]].append(row)
    all_pass = sum(
        len(cases[case_id]) == repeats
        and all(row["assessment"]["verdict"] == "PASS" for row in cases[case_id])
        for case_id in planned_ids
    )
    latency = sorted(
        row["latency_seconds"]
        for row in rows
        if isinstance(row.get("latency_seconds"), (float, int))
    )
    summary = {
        "unique_tasks": len(planned_ids),
        "observed_unique_tasks": len(cases),
        "trials_per_case": repeats,
        "planned_trials": planned,
        "completed_trials": len(rows),
        "missing_trials": planned - len(rows),
        "valid_trials": valid,
        "verdicts": dict(counts),
        "all_trials_pass_tasks": all_pass,
        "latency_median": statistics.median(latency) if latency else None,
        "latency_p95": (
            latency[min(len(latency) - 1, int(0.95 * len(latency)))]
            if latency
            else None
        ),
        "usage": {
            "input_tokens": _usage_total(rows, ("input_tokens", "prompt_tokens")),
            "output_tokens": _usage_total(rows, ("output_tokens", "completion_tokens")),
            "total_tokens": _usage_total(rows, ("total_tokens",)),
            "cached_tokens": _usage_total(rows, ("cached_tokens",)),
            "cost_usd": _usage_total(rows, ("cost_usd",)),
        },
    }
    recorded_summary = run.get("summary", {})
    for field in (
        "unique_tasks",
        "trials_per_case",
        "planned_trials",
        "completed_trials",
        "missing_trials",
        "valid_trials",
        "verdicts",
    ):
        if field in recorded_summary and recorded_summary[field] != summary[field]:
            raise ValueError(f"saved summary disagrees with trial evidence: {field}")
    for dimension in ("split", "category"):
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            groups[str(row.get(dimension, "unknown"))].append(row)
        summary["by_" + dimension] = {
            name: {
                "unique_tasks": len({row["case_id"] for row in group}),
                "trials": len(group),
                "verdicts": dict(
                    Counter(row["assessment"]["verdict"] for row in group)
                ),
            }
            for name, group in sorted(groups.items())
        }
    return summary


def _mode(run: dict) -> tuple[str, str]:
    if run.get("mode") == "real_agent" and not run.get("identity", {}).get("offline"):
        return "real", "REAL AGENT · 真实模型调用"
    if run.get("mode") == "offline_reference_smoke" or run.get("identity", {}).get(
        "offline"
    ):
        return "offline", "OFFLINE REFERENCE SMOKE · 离线参考执行，非真实 Agent 成绩"
    return "unknown", "未声明执行模式 · 不能认定为真实 Agent 成绩"


def _group_table(groups: dict) -> str:
    rows = []
    for name, group in groups.items():
        counts = group["verdicts"]
        rows.append(
            "<tr>"
            f"<td>{_escape(name)}</td><td>{group['unique_tasks']}</td>"
            f"<td>{group['trials']}</td><td>{counts.get('PASS', 0)}</td>"
            f"<td>{counts.get('FAIL', 0)}</td><td>{counts.get('INVALID', 0)}</td>"
            f"<td>{counts.get('INCONCLUSIVE', 0)}</td>"
            f"<td>{_percent(counts.get('PASS', 0), group['trials'])}</td></tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th>分组</th><th>任务</th>'
        "<th>Trials</th><th>PASS</th><th>FAIL</th><th>无效</th>"
        "<th>证据不足</th><th>通过率</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _file_diff(observation: dict) -> str:
    before, after = observation.get("before_files"), observation.get("final_files")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return "初态或终态证据缺失。"
    chunks = []
    for name in sorted(before.keys() | after.keys()):
        if before.get(name) == after.get(name):
            continue
        chunks.extend(
            difflib.unified_diff(
                before.get(name, "").splitlines(keepends=True),
                after.get(name, "").splitlines(keepends=True),
                fromfile="before/" + name,
                tofile="after/" + name,
            )
        )
        chunks.append("\n")
    return "".join(chunks) or "无文件变更。"


def _event_html(event: dict) -> str:
    duration = "未知时长"
    if event.get("start_time") and event.get("end_time"):
        try:
            seconds = (
                datetime.fromisoformat(event["end_time"])
                - datetime.fromisoformat(event["start_time"])
            ).total_seconds()
            duration = f"{seconds:.3f}s"
        except (TypeError, ValueError):
            pass
    state = "调用被拒绝，未执行" if event.get("execution_started") is False else ""
    if event.get("incomplete"):
        state = "事件未完整结束"
    if not state and event.get("error"):
        state = "错误"
    model = ""
    if event.get("type") == "generation":
        model = (
            f" · requested={_escape(event.get('model', event.get('name', '未知')))}"
            f" · resolved={_escape(event.get('response_model') or '未知')}"
        )
    return (
        '<details class="event">'
        f"<summary>{_escape(event.get('type', 'event'))} · "
        f"{_escape(event.get('name', ''))} <small>{duration} "
        f"{_escape(state)}{model}</small></summary>"
        f"<pre>{_escape(_pretty(event))}</pre></details>"
    )


def _trial_html(row: dict, *, detail_url: str | None = None) -> str:
    assessment, observation = row["assessment"], row.get("observation", {})
    verdict = assessment["verdict"]
    metric_rows = []
    for metric in assessment.get("metrics", []):
        metric_rows.append(
            f"<tr><td>{_escape(metric.get('name'))}</td>"
            f"<td>{_escape(metric.get('score'))}</td>"
            f"<td>{_escape(metric.get('threshold'))}</td>"
            f"<td>{_escape(metric.get('reason', ''))}</td>"
            f"<td>{'正式' if metric.get('formal', True) else '诊断（不决定 verdict）'}</td>"
            f"<td>{_escape(metric.get('version', ''))}</td></tr>"
        )
    reasons = [
        metric.get("reason", "")
        for metric in assessment.get("metrics", [])
        if metric.get("success") is False and metric.get("formal", True)
    ]
    errors = [*assessment.get("errors", []), *observation.get("errors", [])]
    if errors:
        reasons.append(_pretty(errors))
    if detail_url is not None:
        details = (
            f'<p><a class="detail-link" href="{_escape(detail_url)}">'
            "打开完整对话、文件快照与 Trace →</a> "
            f"<small>{len(observation.get('events', []))} 个事件 · 独立离线详情页</small></p>"
        )
    else:
        turns = "".join(
            f"<details><summary>Turn {index + 1} · 用户请求与 Agent 回复</summary>"
            f"<h4>输入</h4><pre>{_escape(turn.get('input', ''))}</pre>"
            f"<h4>输出</h4><pre>{_escape(turn.get('output', ''))}</pre></details>"
            for index, turn in enumerate(observation.get("turns", []))
        )
        trace = "".join(_event_html(event) for event in observation.get("events", []))
        details = (
            turns
            + "<details><summary>独立文件证据：初态 → 终态</summary>"
            + f"<pre>{_escape(_file_diff(observation))}</pre>"
            + "<details><summary>完整文件快照</summary>"
            + f"<pre>{_escape(_pretty({'before_files': observation.get('before_files'), 'final_files': observation.get('final_files')}))}</pre>"
            + "</details></details>"
            + f'<details class="trace"><summary>完整 Trace · {len(observation.get("events", []))} 个事件</summary>'
            + trace
            + "</details>"
        )
    return (
        f'<article class="trial" data-verdict="{_escape(verdict)}" '
        f'data-category="{_escape(row.get("category", "unknown"))}" '
        f'data-search="{_escape(row["case_id"].lower())}">'
        f'<div class="trial-heading"><span class="badge {_escape(verdict.lower())}">'
        f"{_escape(verdict)}</span><h3>{_escape(row['case_id'])}</h3>"
        f"<span>Trial {row['trial']}</span></div>"
        f'<p class="muted">{_escape(row.get("split", "unknown"))} · '
        f"validity={_escape(assessment.get('validity', '未知'))} · "
        f"status={_escape(observation.get('status', '未知'))} · "
        f"stop={_escape(observation.get('stop_reason', '未知'))} · "
        f"{_number(row.get('latency_seconds'))}s</p>"
        + (
            f'<p class="failure-reason">{_escape("; ".join(reasons))}</p>'
            if reasons
            else ""
        )
        + "<details><summary>DeepEval 指标与评分理由</summary>"
        '<div class="table-wrap"><table><thead><tr><th>指标</th><th>分数</th>'
        "<th>阈值</th><th>理由</th><th>用途</th><th>版本</th></tr></thead><tbody>"
        + "".join(metric_rows)
        + "</tbody></table></div></details>"
        + details
        + "</article>"
    )


_STYLE = """
:root { color-scheme:light; --ink:#17283d; --muted:#5c6c80; --line:#dae3ed;
--teal:#086d69; --red:#a32636; --paper:#f4f7fa; }
* {box-sizing:border-box} body {margin:0;background:var(--paper);color:var(--ink);
font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header {background:#142b43;color:white;padding:36px max(24px,calc((100% - 1180px)/2))}
header p {color:#d0deec;max-width:900px} h1 {font-size:32px;line-height:1.2;margin:16px 0}
header a {color:#d0eaff}
main {max-width:1228px;margin:auto;padding:24px} h2 {margin-top:30px;font-size:21px}
.eyebrow {font-size:12px;letter-spacing:.12em} .badge {display:inline-block;border-radius:5px;
padding:3px 9px;font-weight:700;font-size:12px;background:#e9eef5;color:var(--ink)}
.real,.pass {background:#d8f4eb;color:#075647}.offline,.unknown,.inconclusive {background:#fff0c7;color:#815700}
.fail,.invalid {background:#fde1e4;color:#922737}.cards {display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.card,section,.trial {background:white;border:1px solid var(--line);border-radius:10px;padding:20px}
.card strong {display:block;font-size:29px;line-height:1.3;margin:8px 0}.muted,small {color:var(--muted)}
.card small {font-size:12px}.grid {display:grid;grid-template-columns:1fr 1fr;gap:18px}
.table-wrap {overflow:auto}table {border-collapse:collapse;width:100%;font-size:13px}
th,td {padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th {background:#f5f8fb;font-weight:600} details {margin:10px 0} summary {cursor:pointer;font-weight:600}
pre {background:#f3f6fa;border:1px solid #e3e9f0;padding:14px;border-radius:6px;
white-space:pre-wrap;word-break:break-word;max-height:540px;overflow:auto;font:12px/1.6 ui-monospace,monospace}
.controls {position:sticky;top:0;z-index:2;padding:12px;background:#edf2f7;display:flex;gap:10px;
flex-wrap:wrap;border-radius:8px;margin:16px 0} input,select {font:inherit;padding:8px 12px;border:1px solid #c4d0dd;border-radius:5px}
input {min-width:280px;flex:1}.trial {margin:14px 0}.trial-heading {display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.trial-heading h3 {font-size:15px;margin:0;flex:1;word-break:break-word}.trial p {margin:9px 0}
.failure-reason {color:var(--red);background:#fff7f7;padding:10px;border-left:3px solid #d2707d}
.event {padding:9px 12px;border-left:3px solid #c9d8e6;background:#fafcfe}.event small {font-weight:400}
a {color:#075e9c} footer {padding:28px 0;color:var(--muted);font-size:12px}[hidden] {display:none!important}
@media(max-width:800px){.cards,.grid {grid-template-columns:1fr 1fr}main {padding:16px}.card strong {font-size:23px}}
@media(max-width:520px){.grid {grid-template-columns:1fr}.controls input {min-width:0;width:100%}}
"""

_SCRIPT = """
const search=document.getElementById('search');
const verdict=document.getElementById('verdict');
const category=document.getElementById('category');
function filter(){let shown=0;document.querySelectorAll('.trial').forEach(row=>{
 const match=row.dataset.search.includes(search.value.toLowerCase())&&
 (!verdict.value||row.dataset.verdict===verdict.value)&&
 (!category.value||row.dataset.category===category.value);
 row.hidden=!match;if(match)shown++;
});document.getElementById('visible').textContent=shown+' 个 trial';}
[search,verdict,category].forEach(el=>el.addEventListener('input',filter));filter();
"""


def _write_trial_page(run_dir: Path, run: dict, row: dict) -> str:
    """Hash filenames keep task IDs out of paths, including untrusted IDs."""
    key = f"{row['case_id']}\0{row['trial']}"
    relative = (
        "report-trials/"
        + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        + ".html"
    )
    destination = run_dir / relative
    destination.parent.mkdir(exist_ok=True)
    mode, label = _mode(run)
    page = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        f"<title>{_escape(row['case_id'])} · Trial {row['trial']}</title>"
        f"<style>{_STYLE}</style></head><body><header>"
        '<a href="../report.html">← 返回报告与筛选</a>'
        "<h1>单次 Trial 完整证据</h1>"
        f'<span class="badge {mode}">{_escape(label)}</span>'
        f"<p>{_escape(run.get('run_id', ''))}<br>"
        f"Identity: {_escape(run.get('identity_hash', '未知'))}</p></header><main>"
        + _trial_html(row)
        + "<footer>此页包含保存的完整公开轨迹，不调用网络或重新评分。"
        '<a href="../results.json">原始 results.json</a> · '
        '<a href="../report.html">返回主报告</a></footer></main></body></html>'
    )
    destination.write_text(page, encoding="utf-8")
    return relative


def write_report(run_dir: Path | str) -> Path:
    """Write report.html/report.md beside immutable results; return HTML path."""
    run_dir = Path(run_dir)
    run = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    summary = evidence_summary(run)
    counts, usage = summary["verdicts"], summary["usage"]
    mode, mode_label = _mode(run)
    identity = run.get("identity", {})
    runtime = identity.get("runtime", {})
    dataset = identity.get("dataset", {})
    rows = run["trials"]
    models = sorted(
        {
            str(event["response_model"])
            for row in rows
            for event in row.get("observation", {}).get("events", [])
            if event.get("type") == "generation" and event.get("response_model")
        }
    )
    pass_count, planned = counts.get("PASS", 0), summary["planned_trials"]
    title = str(run.get("run_id", run_dir.name))
    cards = [
        (
            "实际执行",
            f"{summary['completed_trials']} / {planned}",
            f"{summary['observed_unique_tasks']} 个已执行任务 · {summary['missing_trials']} 个缺失 trial",
        ),
        (
            "计划 trial 通过率",
            _percent(pass_count, planned),
            f"{pass_count} PASS · {counts.get('FAIL', 0)} FAIL · {counts.get('INVALID', 0)} INVALID",
        ),
        (
            "Agent 总 Token",
            _number(usage["total_tokens"]["total"]),
            f"用量已知 {usage['total_tokens']['known_trials']}/{len(rows)} trials",
        ),
        (
            "延迟 P50 / P95",
            f"{_number(summary['latency_median'])} / {_number(summary['latency_p95'])} s",
            f"费用 USD：{_number(usage['cost_usd']['total'])}；未知不按 0 计算",
        ),
    ]
    cards_html = "".join(
        f'<div class="card"><span class="muted">{_escape(label)}</span>'
        f"<strong>{_escape(value)}</strong><small>{_escape(note)}</small></div>"
        for label, value, note in cards
    )
    identity_display = {
        "run_id": run.get("run_id"),
        "identity_hash": run.get("identity_hash"),
        "mode": run.get("mode"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "dataset": dataset,
        "scoring_backend": run.get("scoring_backend"),
        "scoring_version": identity.get("scoring_version"),
        "execution_backend": run.get("execution_backend"),
        "harness_version": identity.get("harness_version"),
        "harness_source": identity.get("harness_source"),
        "scoring_identity": identity.get("scoring_identity"),
        "runtime": runtime,
        "config": run.get("config", {}),
        "response_models_observed": models,
    }
    categories = "".join(
        f'<option value="{_escape(category)}">{_escape(category)}</option>'
        for category in summary["by_category"]
    )
    verdict_options = "".join(
        f'<option value="{_escape(verdict)}">{_escape(verdict)}</option>'
        for verdict in counts
    )
    limitations = "".join(
        f"<li>{_escape(item)}</li>" for item in dataset.get("limitations", [])
    )
    ordered_rows = sorted(
        rows,
        key=lambda row: (
            row["assessment"]["verdict"] == "PASS",
            row["case_id"],
            row["trial"],
        ),
    )
    split_details = len(rows) > 100
    trial_fragments = []
    for row in ordered_rows:
        detail_url = _write_trial_page(run_dir, run, row) if split_details else None
        trial_fragments.append(_trial_html(row, detail_url=detail_url))
    trials_html = "".join(trial_fragments)
    detail_notice = (
        '<p class="muted">本次运行超过 100 个 trial。主报告保留筛选和评分理由，'
        "完整轨迹按 trial 拆为离线详情页；分享时请将 report-trials/ 目录一并保留。</p>"
        if split_details
        else ""
    )
    document = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        f"<title>{_escape(title)} · Agent Benchmark</title><style>{_STYLE}</style></head><body>"
        '<header><div class="eyebrow">AGENT EVAL SUITE / SAVED EVIDENCE REPORT</div>'
        f'<h1>工具型 Agent 评测</h1><span class="badge {mode}">{_escape(mode_label)}</span>'
        f"<p>{_escape(title)} · {_escape(runtime.get('agent', 'reference'))} · "
        f"requested model: {_escape(runtime.get('model', '未知'))}<br>"
        f"Dataset: {_escape(dataset.get('dataset_id', '未知'))} · "
        f"Inspect execution → DeepEval scoring → 本地证据报告</p></header><main>"
        f'<div class="cards">{cards_html}</div>'
        '<p class="muted">报告只展示已保存结果，不调用模型、不重新评分。'
        "PASS 同时要求任务结果与正式约束通过；INVALID / INCONCLUSIVE 与 FAIL 分开统计。</p>"
        f"<p>有效 trial 通过率：{_percent(pass_count, summary['valid_trials'])}；"
        f"每个任务全部 {summary['trials_per_case']} 次计划 trial 通过："
        f"{summary['all_trials_pass_tasks']}/{summary['unique_tasks']}。"
        "缺失或无效 trial 不能证明全部通过。</p>"
        '<div class="grid"><section><h2>按任务类别</h2>'
        + _group_table(summary["by_category"])
        + "</section><section><h2>按数据划分</h2>"
        + _group_table(summary["by_split"])
        + "</section></div>"
        "<h2>用量与身份</h2><section>"
        f"<p>输入 Token：{_number(usage['input_tokens']['total'])} · "
        f"输出 Token：{_number(usage['output_tokens']['total'])} · "
        f"缓存命中 Token：{_number(usage['cached_tokens']['total'])}。"
        "prompt_tokens / completion_tokens 仅按字段别名展示，不重复累加。</p>"
        f"<p>响应实际 model：{_escape(', '.join(models) or '未知')}。"
        "字节估算 tokenizer 仅用于 Agent 上下文预算，以上用量来自模型响应。</p>"
        "<details><summary>数据集、Agent、评分与运行配置</summary>"
        f"<pre>{_escape(_pretty(identity_display))}</pre></details>"
        "<details><summary>用量完整性及已知部分</summary>"
        f"<pre>{_escape(_pretty(usage))}</pre></details>"
        f"<details><summary>数据集限制与来源</summary><ul>{limitations}</ul>"
        f"<pre>{_escape(_pretty(dataset.get('provenance', {})))}</pre></details></section>"
        "<h2>逐条结果与完整 Trace</h2>" + detail_notice + '<div class="controls">'
        '<input id="search" aria-label="搜索任务" placeholder="搜索 task ID">'
        f'<select id="verdict" aria-label="结果筛选"><option value="">全部结果</option>{verdict_options}</select>'
        f'<select id="category" aria-label="类别筛选"><option value="">全部类别</option>{categories}</select>'
        '<span id="visible"></span></div>'
        + trials_html
        + '<footer>来源：<a href="results.json">results.json</a> · '
        '<a href="report.md">Markdown 报告</a>。页面无需网络或第三方资源。'
        "工具调用被拒绝时明确标注未执行；不把拒绝记录当作真实外部副作用。</footer>"
        f"<script>{_SCRIPT}</script></main></body></html>"
    )
    path = run_dir / "report.html"
    path.write_text(document, encoding="utf-8")
    markdown = [
        f"# Agent Benchmark · {_escape(title)}",
        "",
        f"**{mode_label}**",
        "",
        f"计划 {planned} 次，实际完成 {len(rows)} 次；"
        f"{summary['observed_unique_tasks']} 个任务，每任务计划 {summary['trials_per_case']} 次。",
        f"PASS {pass_count}；FAIL {counts.get('FAIL', 0)}；"
        f"INVALID {counts.get('INVALID', 0)}；INCONCLUSIVE {counts.get('INCONCLUSIVE', 0)}。",
        f"计划通过率 {_percent(pass_count, planned)}；有效通过率 {_percent(pass_count, summary['valid_trials'])}。",
        f"输入/输出/总 Token：{_number(usage['input_tokens']['total'])} / "
        f"{_number(usage['output_tokens']['total'])} / {_number(usage['total_tokens']['total'])}。",
        f"费用 USD：{_number(usage['cost_usd']['total'])}。未知成本不按 0 计算。",
        "",
        "## 分组",
        "",
        "| 维度 | 分组 | 任务 | Trials | PASS | FAIL | INVALID | INCONCLUSIVE |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for dimension in ("split", "category"):
        for name, group in summary["by_" + dimension].items():
            group_counts = group["verdicts"]
            markdown.append(
                f"| {dimension} | {_escape(name).replace('|', '&#124;')} | "
                f"{group['unique_tasks']} | {group['trials']} | {group_counts.get('PASS', 0)} | "
                f"{group_counts.get('FAIL', 0)} | {group_counts.get('INVALID', 0)} | "
                f"{group_counts.get('INCONCLUSIVE', 0)} |"
            )
    markdown.extend(["", "## 非 PASS 记录", ""])
    for row in rows:
        assessment = row["assessment"]
        if assessment["verdict"] != "PASS":
            markdown.extend(
                [
                    f"### {_escape(row['case_id'])} · Trial {row['trial']}",
                    "",
                    f"{_escape(assessment['verdict'])} / {_escape(assessment.get('validity', '未知'))}",
                    "",
                    "<pre>" + _escape(_pretty(assessment)) + "</pre>",
                    "",
                ]
            )
    markdown.extend(
        [
            "## 身份与复现边界",
            "",
            "<pre>" + _escape(_pretty(identity_display)) + "</pre>",
            "",
            "完整模型请求/响应、工具参数/结果、逐轮输出和文件快照见 [本地 HTML](report.html)。",
            "超过 100 个 trial 时，完整轨迹拆分到 report-trials/；请连同主报告一起保留。",
            "来源：[保存结果](results.json)。报告仅聚合已保存 verdict，不重新评分或调用网络。",
            "",
        ]
    )
    (run_dir / "report.md").write_text("\n".join(markdown), encoding="utf-8")
    return path
