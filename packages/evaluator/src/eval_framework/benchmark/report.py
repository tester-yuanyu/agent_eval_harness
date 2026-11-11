"""Standalone, network-free reports rendered only from saved trial evidence."""

# HTML/CSS template literals intentionally retain their natural markup width.
# ruff: noqa: E501

from __future__ import annotations

import difflib
import hashlib
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .report_context import METHODOLOGY_HTML, scope_html
from .report_diagnostics import write_diagnostics
from .report_evaluation import evaluation_html, evaluation_summary
from .report_insights import (
    comparisons,
    estimate_cost,
    intent_mode,
    latency_details,
    load_contracts,
    load_report_tasks,
    report_usage,
    schema_advice,
    token_parts,
)
from .report_links import load_links


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


def _event_anchor(event_id: str, row: dict) -> str:
    key = f"{row['case_id']}\0{row['trial']}\0{event_id}"
    return "event-" + hashlib.sha256(key.encode()).hexdigest()[:24]


def _trial_anchor(case_id: str, trial: int) -> str:
    return "trial-" + hashlib.sha256(f"{case_id}\0{trial}".encode()).hexdigest()[:24]


def _findings_html(row: dict, detail_url: str | None = None) -> str:
    findings = row.get("_report_findings", [])
    result = []
    for finding in findings:
        links = " · ".join(
            f'<a href="{_escape((detail_url or "") + "#" + _event_anchor(ref, row))}">证据 {index + 1}</a>'
            for index, ref in enumerate(finding["evidence"]) if ref
        )
        contract = finding.get("contract")
        source = (
            "<details><summary>参考契约来源（已核对 Hash）</summary>"
            f"<pre>{_escape(_pretty(contract))}</pre></details>" if contract else ""
        )
        result.append(
            '<div class="finding">'
            f'<a href="{_escape(row.get("_report_overview_url", "") + "#issue-" + str(finding["number"]))}">同问题 #{finding["number"]}</a>：'
            f"{_escape(finding.get('short', finding['title']))}"
            f"<details><summary>诊断详情与证据</summary><p>{_escape(finding['description'])}</p><p>{links}</p>{source}</details></div>"
        )
    if not findings and row["assessment"]["verdict"] != "PASS":
        result.append('<p class="muted">根因待核实：当前证据未触发可确认的诊断规则，不能仅凭评分差异归责模型或执行层。</p>')
    url = row.get("_report_langfuse_url")
    result.append(f'<p><a href="{_escape(url)}" target="_blank" rel="noopener noreferrer">在 Langfuse 中查看完整 Trace →</a>（保存结果已回读核验）</p>' if url else '<p class="muted">Langfuse：未导出或未核验；本页保留完整离线证据。</p>')
    return "".join(result)


def _overview_html(rows: list[dict], contracts: dict, warnings: list[str]) -> str:
    labels = {"read": "读操作", "write": "写操作", "mixed": "混合目标", "unknown": "目标待确认"}
    groups = {mode: [r for r in rows if intent_mode(r, contracts) == mode] for mode in labels}
    lines, rates = [], []
    for mode, label in labels.items():
        group = groups[mode]
        if group:
            passed = sum(r["assessment"]["verdict"] == "PASS" for r in group)
            failed = sum(r["assessment"]["verdict"] == "FAIL" for r in group)
            lines.append(f"{label}：{passed}/{len(group)} 通过，{failed} 条 FAIL。")
            rates.append(f"{label}通过率 {_percent(passed, len(group))}（{passed}/{len(group)}）")
    issues, actions = {}, {}
    for row in rows:
        for finding in row.get("_report_findings", []):
            issues.setdefault(finding["kind"], []).append((row, finding))
            actions[finding["kind"]] = finding["action"]
    details = []
    for kind, entries in issues.items():
        pattern_table = ""
        finding = entries[0][1]
        cases = {(r["case_id"], r["trial"]) for r, _ in entries}
        diagnosis = finding["description"] if kind != "schema_mismatch" else "模型候选参数使用参考契约未声明的字段，随后执行校验拒绝。以下按不同失败执行去重统计，同一执行可出现多个字段变体。"
        if kind == "missing_confirmation_context":
            diagnosis = "确认轮可见请求只携带确认语句与通用指令，没有前轮参数或消息；模型随后返回空参数并要求澄清。证据指向上下文传递缺口，不能归为模型遗忘。具体轮次见各条证据，内部状态保存仍需核对。"
        if kind == "schema_mismatch":
            patterns = {}
            for row, item in entries:
                for alias, canonical in item.get("aliases", {}).items():
                    patterns.setdefault((alias, canonical), set()).add((row["case_id"], row["trial"]))
            actions[kind] = schema_advice({a:c for a,c in patterns}, any(f.get("prompt_contract_gap") for _,f in entries))
            pattern_table = '<div class="table-wrap"><table><thead><tr><th>候选字段 → 契约字段</th><th>受影响执行数</th></tr></thead><tbody>' + "".join(
                f"<tr><td>{_escape(a)} → {_escape(c)}</td><td>{len(affected)}</td></tr>"
                for (a, c), affected in sorted(patterns.items())
            ) + '</tbody></table></div><p class="muted">同一执行可出现多个映射，以上数量不能相加。</p>'
            gaps = {(r["case_id"], r["trial"]) for r, f in entries if f.get("prompt_contract_gap")}
            if gaps:
                diagnosis += f"其中 {len(gaps)} 条执行呈现两层问题：①可见意图请求只提供通用 Schema，parameters 允许任意字段，未列出上述标准字段；②模型在该请求下输出了参考契约未声明的字段，随后被执行校验拒绝。优先修复 Schema 传递，使模型看到标准字段；验证后再按需增加别名映射兜底。当前证据不支持‘模型已看到标准字段但拒不遵守’的归因，也尚未通过对照重跑证明哪项修复足以消除失败。"
            else:
                diagnosis += "是否已向模型传递具体字段约束，仍需核对请求；字段偏差本身不能证明模型无视 Schema。"
            diagnosis += "这些候选映射只用于诊断和修复建议，未修改参数或评分；修复后仍需验证类型、范围和多轮确认。"
        affected_links = "、".join(f'<a href="#{_trial_anchor(c, t)}">{_escape(c)} / 第 {t} 次</a>' for c, t in sorted(cases))
        details.append(f'<li id="issue-{finding["number"]}"><strong>问题 #{finding["number"]}：{_escape(finding["title"])} · {len(cases)} 条</strong><p>{_escape(diagnosis)}</p>{pattern_table}<a href="#trial-results" class="issue-filter" data-issue="{_escape(finding["number"])}">筛选本问题全部 {len(cases)} 条执行 →</a><details><summary>受影响执行 · 点击定位</summary>{affected_links}</details></li>')
    failures = [r for r in rows if r["assessment"]["verdict"] == "FAIL"]
    diagnosed = sum(bool(r.get("_report_findings")) for r in failures)
    coverage = f"失败归因覆盖：{diagnosed}/{len(failures)} 条；问题计数可重叠，不能相加。"
    if diagnosed < len(failures):
        coverage += " 待核实：" + "、".join(r["case_id"] for r in failures if not r.get("_report_findings")) + "。"
    notes = []
    if all("_report_task" in r for r in rows) and rows:
        notes.append("按冻结任务目标分组；多轮中的意图偏移不改变所属场景。")
    else:
        notes.append("有冻结任务证据时按目标分组；缺失时回退到观察意图，无法确定则标记目标待确认，不猜测。")
    write_passes = [r for r in groups["write"] if r["assessment"]["verdict"] == "PASS"]
    guarded = [r for r in write_passes if any(m.get("name") == "tool_not_called" and m.get("success") is True for m in r["assessment"].get("metrics", []))]
    if guarded:
        notes.append(f"写场景中 {len(guarded)} 条 PASS 属于要求不调用工具的保护路径（" + "、".join(r["case_id"] for r in guarded) + "）；不能解释为成功写入。")
    if groups["write"] and (not write_passes or len(guarded) == len(write_passes)):
        notes.append("本批没有通过的成功写入路径；不能将场景通过率视为实际发放成功率。")
        actions["write_coverage"] = "修复 Agent 后优先复测一条请求→确认→实际写入的成功路径，再验证重复确认无额外副作用；保持原始结果不变，新运行单独比较。"
    write_failures = sum(r["assessment"]["verdict"] == "FAIL" for r in groups["write"])
    if write_failures > len(failures) / 2:
        notes.insert(0, f"本批写场景是主要失败区：占全部失败的 {write_failures}/{len(failures)}；这是 Agent 在当前任务集上的表现，不是模型通用能力结论。")
    chain_lines = []
    for category in sorted({r.get("category", "") for r in failures}):
        category_rows = [r for r in rows if r.get("category", "") == category]
        if any(r.get("evaluation_level") in {"chain", "link"} for r in category_rows):
            passed = sum(r["assessment"]["verdict"] == "PASS" for r in category_rows)
            failed_ids = "、".join(r["case_id"] for r in category_rows if r["assessment"]["verdict"] == "FAIL")
            chain_lines.append(f"{category}：{passed}/{len(category_rows)} 通过（{_percent(passed, len(category_rows))}）；失败：{failed_ids}。")
    if not actions:
        actions["coverage"] = "依据本批覆盖范围补充未验证路径；失败项先核对期望与实际，再沿 Trace 排查。"
    read_failures = [r for r in groups["read"] if r["assessment"]["verdict"] == "FAIL"]
    read_summary = ""
    if read_failures:
        read_summary = '<details class="read-failures" open><summary>读场景失败摘要</summary><ul>' + "".join(
            f'<li><a href="#{_trial_anchor(r["case_id"], r["trial"])}">{_escape(r["case_id"])} / 第 {r["trial"]} 次</a>：'
            + _escape("；".join(dict.fromkeys(f.get("short", f["title"]) for f in r.get("_report_findings", []))) or "根因待核实")
            + "</li>" for r in read_failures
        ) + "</ul></details>"
    latency = _latency_html(rows)
    return (
        '<section class="overview" id="findings"><h2>问题摘要</h2><p class="headline"><strong>' + _escape("；".join(rates)) + "</strong></p>"
        + "<p>" + _escape(" ".join(lines)) + "</p>"
        + "".join("<p>" + _escape(note) + "</p>" for note in notes + chain_lines)
        + read_summary
        + '<ol class="issues">' + ("".join(details) or "<li>未触发可确认的诊断；通过仅覆盖本次实际执行范围。</li>") + "</ol>"
        + '<p class="muted">' + _escape(coverage) + " 诊断是证据解释，不改变正式评分，也不代表模型通用能力。</p>"
        + '<h2 id="actions">下一步建议</h2><ol>' + "".join(f"<li>{_escape(a)}</li>" for a in actions.values()) + "</ol>"
        + '<details class="supporting-evidence"><summary>耗时解释与最慢执行</summary>' + latency + "</details>"
        + ("<details><summary>解释与用量的证据限制</summary><ul>" + "".join(f"<li>{_escape(w)}</li>" for w in warnings) + "</ul></details>" if warnings else "")
        + "</section>"
    )


def _latency_html(rows: list[dict]) -> str:
    from math import ceil
    from statistics import median

    values = sorted(r["latency_seconds"] for r in rows if isinstance(r.get("latency_seconds"), (int, float)))
    overall = ""
    if values and median(values) > 0:
        p50, p95 = median(values), values[min(len(values) - 1, int(.95 * len(values)))]
        overall = f"<p>总体 P50 {p50:.2f} 秒，P95 {p95:.2f} 秒，约 {p95 / p50:.1f} 倍。该统计混合不同执行层级，需结合以下轮数及模型调用耗时理解。</p>"
    table = []
    for level in sorted({r.get("evaluation_level", r.get("execution_mode", "未知")) for r in rows}):
        values = sorted(r["latency_seconds"] for r in rows if r.get("evaluation_level", r.get("execution_mode", "未知")) == level and isinstance(r.get("latency_seconds"), (int, float)))
        if values:
            table.append(f"<tr><td>{_escape(level)}</td><td>{len(values)}</td><td>{median(values):.2f}</td><td>{values[max(0, ceil(.95 * len(values)) - 1)]:.2f}</td></tr>")
    slow = []
    for item in latency_details(rows):
        model = f"{item['model_seconds']:.2f} 秒" if item["model_seconds"] is not None else "未知（时间证据不全）"
        slow.append(f"<li>{_escape(item['case'])} / 第 {item['trial']} 次：总耗时 {_number(item['latency'])} 秒，{item['turns']} 轮、{item['calls']} 次模型调用；模型调用耗时累计 {model}。</li>")
    return ('<h2>耗时解释</h2>' + overall + '<p>不同执行层级的模型调用次数和轮数不同，总体尾延迟不能直接归因于写意图。以下列出最慢执行；不能仅凭调用次数判定重试或超时。模型耗时为事件时长之和，并行时不可作为总耗时占比；剩余时间可能包含运行环境、工具或调度开销，未细分部分不猜测。</p><ul>' + "".join(slow) + '</ul><details><summary>按执行层级统计延迟（秒）</summary><table><thead><tr><th>层级</th><th>执行数</th><th>P50</th><th>P95</th></tr></thead><tbody>' + "".join(table) + '</tbody></table><p>各层级独立计算，P95 使用最近秩法；小样本仅作本批描述。</p></details>')


def evidence_summary(run: dict) -> dict:
    """保持历史报表汇总格式，只读取保存的证据。"""
    from ..aggregator import evidence_summary as aggregate

    return aggregate(run)


def _mode(run: dict) -> tuple[str, str]:
    if run.get("mode") == "real_module":
        return "real", "程序模块 · 真实模块调用，不计作模型决策成绩"
    if run.get("mode") == "real_model_decision":
        return "real", "模型决策 · 真实单次模型决策，未执行工具"
    if run.get("mode") == "real_model_intent":
        return "real", "意图模块 · 真实模型调用，未执行工具"
    if run.get("mode") == "real_agent_test_environment":
        return "real", "真实 Agent · 真实模型与隔离测试工具，非线上业务环境"
    if run.get("mode") == "mixed_execution":
        return "real", "分层执行 · 各适配器声明执行类型，模块与工具链分别统计"
    if run.get("mode") == "mixed_real_execution":
        return "real", "分层执行 · 模块与 Agent 分层统计，不混作模型成功率"
    if run.get("mode") == "real_agent" and not run.get("identity", {}).get("offline"):
        return "real", "真实 Agent · 真实模型调用"
    if run.get("mode") == "offline_reference_smoke" or run.get("identity", {}).get(
        "offline"
    ):
        return "offline", "离线参考验证 · 非真实 Agent 成绩"
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
        "<th>执行次数</th><th>通过（PASS）</th><th>失败（FAIL）</th><th>无效</th>"
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


def _event_html(event: dict, metrics: list[dict] | None = None, *, row: dict | None = None) -> str:
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
            f" · 请求模型={_escape(event.get('model', event.get('name', '未知')))}"
            f" · 响应模型={_escape(event.get('response_model') or '未知')}"
        )
    scoped = "".join(
        f"<li>{_escape(m['name'])}: {_escape(m.get('score'))} · "
        f"{_escape(m.get('status', 'SCORED'))} · {_escape(m.get('reason', ''))}</li>"
        for m in (metrics or []) if m.get("event_id") == event.get("id")
    )
    return (
        f'<details class="event" id="{_event_anchor(event.get("id", ""), row or {"case_id": "", "trial": 0})}">'
        f"<summary>{_escape(event.get('type', 'event'))} · "
        f"{_escape(event.get('name', ''))} <small>{duration} "
        f"{_escape(state)}{model}</small></summary>"
        f"<ul>{scoped}</ul><pre>{_escape(_pretty(event))}</pre></details>"
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
            f"<td>{_escape(metric.get('version', ''))}<br>"
            f"{_escape(metric.get('scope', 'task'))} / {_escape(metric.get('event_id') or 'root')}</td></tr>"
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
            f"<details><summary>第 {index + 1} 轮 · 用户请求与 Agent 回复</summary>"
            f"<h4>输入</h4><pre>{_escape(turn.get('input', ''))}</pre>"
            f"<h4>输出</h4><pre>{_escape(turn.get('output', ''))}</pre></details>"
            for index, turn in enumerate(observation.get("turns", []))
        )
        trace = "".join(_event_html(event, assessment.get("metrics", []), row=row) for event in observation.get("events", []))
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
        f'<article class="trial" id="{_trial_anchor(row["case_id"], row["trial"])}" data-verdict="{_escape(verdict)}" '
        f'data-issues="{_escape(" ".join(str(f["number"]) for f in row.get("_report_findings", [])))}" '
        f'data-category="{_escape(row.get("category", "unknown"))}" '
        f'data-search="{_escape(row["case_id"].lower())}">'
        f'<div class="trial-heading"><span class="badge {_escape(verdict.lower())}">'
        f"{_escape(verdict)}</span><h3>{_escape(row['case_id'])}</h3>"
        f"<span>第 {row['trial']} 次执行</span></div>"
        f'<p class="muted">{_escape(row.get("split", "unknown"))} · '
        f"有效性={_escape(assessment.get('validity', '未知'))} · "
        f"状态={_escape(observation.get('status', '未知'))} · "
        f"停止原因={_escape(observation.get('stop_reason', '未知'))} · "
        f"{_number(row.get('latency_seconds'))}s</p>"
        + ("<div class=\"failure-reason\"><strong>结果差异</strong><ul>"
           + "".join(f"<li>{_escape(item['metric'])}：期望 {_escape(item['expected'])}；实际 {_escape(item['actual'])}。</li>" for item in comparisons(row))
           + (f"<li>执行或评分发生错误：{len(errors)} 条，详见原始评分证据。</li>" if errors else "")
           + "</ul></div>" if reasons else "")
        + _findings_html(row, detail_url)
        + ("<details><summary>原始评分证据</summary><pre>" + _escape("\n".join(reasons)) + "</pre></details>" if reasons else "")
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
header {background:#142b43;color:white;padding:20px max(24px,calc((100% - 1180px)/2))}
header p {color:#d0deec;max-width:900px} h1 {font-size:26px;line-height:1.2;margin:10px 0}
header a {color:#d0eaff}
main {max-width:1228px;margin:auto;padding:24px} h2 {margin-top:30px;font-size:21px}
.eyebrow {font-size:12px;letter-spacing:.12em} .badge {display:inline-block;border-radius:5px;
padding:3px 9px;font-weight:700;font-size:12px;background:#e9eef5;color:var(--ink)}
.real,.pass {background:#d8f4eb;color:#075647}.offline,.unknown,.inconclusive {background:#fff0c7;color:#815700}
.fail,.invalid {background:#fde1e4;color:#922737}.cards {display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.card,section,.trial {background:white;border:1px solid var(--line);border-radius:10px;padding:20px}
.card strong {display:block;font-size:29px;line-height:1.3;margin:8px 0}.muted,small {color:var(--muted)}
.summary-strip {display:flex;flex-wrap:wrap;gap:8px 22px;font-size:13px;padding:10px 0;border-bottom:1px solid var(--line)}
.summary-stat strong {margin-left:6px}.evidence-group {background:white;border:1px solid var(--line);border-radius:8px;padding:12px 16px}
.summary-notes {font-size:13px;color:var(--muted)}
.report-nav {display:flex;flex-wrap:wrap;gap:8px 18px;padding:12px 0;font-size:13px}
.report-scope {padding:14px 20px}.report-scope h2 {margin:0;font-size:17px}.report-scope p {margin:8px 0;font-size:13px}
.methodology dt {font-weight:600}.methodology dd {margin:4px 0 14px}.read-failures {font-size:14px}
[id] {scroll-margin-top:90px}
.card small {font-size:12px}.grid {display:grid;grid-template-columns:1fr 1fr;gap:18px}
.table-wrap {overflow:auto}table {border-collapse:collapse;width:100%;font-size:13px}
th,td {padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th {background:#f5f8fb;font-weight:600} details {margin:10px 0} summary {cursor:pointer;font-weight:600}
pre {background:#f3f6fa;border:1px solid #e3e9f0;padding:14px;border-radius:6px;
white-space:pre-wrap;word-break:break-word;max-height:540px;overflow:auto;font:12px/1.6 ui-monospace,monospace}
.controls {position:sticky;top:0;z-index:2;padding:12px;background:#edf2f7;display:flex;gap:10px;
flex-wrap:wrap;border-radius:8px;margin:16px 0} input,select {font:inherit;padding:8px 12px;border:1px solid #c4d0dd;border-radius:5px}
input {min-width:280px;flex:1}.trial {margin:14px 0}.trial-heading {display:flex;align-items:center;gap:12px;flex-wrap:wrap}
select {min-width:0;max-width:100%}
.trial-heading h3 {font-size:15px;margin:0;flex:1;word-break:break-word}.trial p {margin:9px 0}
.failure-reason {color:var(--red);background:#fff7f7;padding:10px;border-left:3px solid #d2707d}
.headline {font-size:23px;line-height:1.5;padding:16px;background:#fff5e8;border-left:4px solid #cc7722}.issues>li {margin:16px 0}.overview {margin:18px 0}.overview h2:first-child {margin-top:0}
.finding {padding:14px 16px;margin:12px 0;background:#f2f8fb;border-left:3px solid #388291;border-radius:4px}
.finding a {color:#086d69}details:target {outline:2px solid #388291}
.event {padding:9px 12px;border-left:3px solid #c9d8e6;background:#fafcfe}.event small {font-weight:400}
a {color:#075e9c} footer {padding:28px 0;color:var(--muted);font-size:12px}[hidden] {display:none!important}
@media(max-width:800px){.cards,.grid {grid-template-columns:1fr 1fr}main {padding:16px}.card strong {font-size:23px}}
@media(max-width:520px){.grid {grid-template-columns:1fr}.controls input {min-width:0;width:100%}}
"""

_SCRIPT = """
const search=document.getElementById('search');
const verdict=document.getElementById('verdict');
const category=document.getElementById('category');
const issue=document.getElementById('issue');
function filter(){let shown=0;document.querySelectorAll('.trial').forEach(row=>{
 const match=row.dataset.search.includes(search.value.toLowerCase())&&
 (!verdict.value||row.dataset.verdict===verdict.value)&&
 (!category.value||row.dataset.category===category.value)&&
 (!issue.value||row.dataset.issues.split(' ').includes(issue.value));
 row.hidden=!match;if(match)shown++;
});document.getElementById('visible').textContent=shown+' 条执行结果';}
[search,verdict,category,issue].forEach(el=>el.addEventListener('input',filter));filter();
function clearFilters(){[search,verdict,category,issue].forEach(el=>el.value='');}
document.querySelectorAll('.issue-filter').forEach(link=>link.addEventListener('click',()=>{
 clearFilters();issue.value=link.dataset.issue;filter();
}));
document.querySelectorAll('a[href^="#trial-"],a[href^="#event-"]').forEach(link=>link.addEventListener('click',()=>{
 const target=document.getElementById(link.hash.slice(1));
 if(target?.closest('.trial')?.hidden){clearFilters();filter();}
}));
function revealEvidence(){const el=document.getElementById(location.hash.slice(1));
 if(!el)return;const trial=el.closest('.trial');if(trial&&trial.hidden){clearFilters();filter();}
 let p=el;while(p){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}
 el.scrollIntoView({block:'center'});}
window.addEventListener('hashchange',revealEvidence);revealEvidence();
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
        f"<title>{_escape(row['case_id'])} · 第 {row['trial']} 次执行</title>"
        f"<style>{_STYLE}</style></head><body><header>"
        '<a href="../report.html">← 返回报告与筛选</a>'
        "<h1>单次执行完整证据</h1><p>说明文字使用中文；原始输入、输出、评分规则和工具证据保留执行时的原文。</p>"
        f'<span class="badge {mode}">{_escape(label)}</span>'
        f"<p>{_escape(run.get('run_id', ''))}<br>"
        f"运行身份 Hash：{_escape(run.get('identity_hash', '未知'))}</p></header><main>"
        + _trial_html({**row, "_report_overview_url": "../report.html"})
        + "<footer>此页包含保存的完整公开轨迹，不调用网络或重新评分。"
        '<a href="../results.json">原始 results.json</a> · '
        '<a href="../report.html">返回主报告</a></footer></main>'
        '<script>function reveal(){const e=document.getElementById(location.hash.slice(1));if(!e)return;'
        "let p=e;while(p){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}e.scrollIntoView();}"
        "window.addEventListener('hashchange',reveal);reveal();</script></body></html>"
    )
    destination.write_text(page, encoding="utf-8")
    return relative


def write_report(run_dir: Path | str, *, format: str = "auto") -> Path:
    """Prefer Inspect View; keep explicit domain/legacy report compatibility."""
    if format not in {"auto", "inspect", "domain"}:
        raise ValueError("report format must be auto, inspect or domain")
    run_dir = Path(run_dir)
    if format != "domain":
        from .native_reporting import native_logs, write_native_report

        if format == "inspect" or native_logs(run_dir):
            run = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
            return write_native_report(run_dir, summary=evidence_summary(run))
    return write_domain_report(run_dir)


def write_domain_report(run_dir: Path | str) -> Path:
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
    contracts, warnings = load_contracts(run)
    tasks, task_warnings = load_report_tasks(run)
    warnings.extend(task_warnings)
    partitions = evaluation_summary(run, tasks)
    from .report_links import load_dashboard_link, load_run_links
    run_links = load_run_links(run_dir)
    dashboard_url = load_dashboard_link(run_dir)
    experiment_links = " · ".join(
        f'<a href="{_escape(item["url"])}" target="_blank" rel="noopener">Langfuse 完整实验 · 第{item["trial"]}轮</a>'
        for item in run_links.get("experiments", [])
    )
    if dashboard_url:
        experiment_links = f'<a href="{_escape(dashboard_url)}" target="_blank" rel="noopener">Langfuse 统计看板</a> · ' + experiment_links
    run_links_html = f'<nav class="run-links">{experiment_links}</nav>' if experiment_links else ""

    analysis = json.loads(write_diagnostics(run_dir).read_text())
    warnings.extend(analysis["warnings"])
    by_trial = {(t["case_id"], t["trial"]): t for t in analysis["trials"]}
    links = load_links(run_dir)
    for row in rows:
        diagnostic = by_trial[(row["case_id"], row["trial"])]
        row["_report_operation"] = diagnostic["operation"]
        if diagnostic["goal_bound"]:
            row["_report_task"] = {}
        row["_report_findings"] = diagnostic["findings"]
        row["_report_langfuse_url"] = links.get((row["case_id"], row["trial"]))
    # Enrichment validates the original rows, never the presentation fields.
    original_run = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    native_usage, usage_sources, usage_warnings = report_usage(run_dir, original_run)
    warnings.extend(usage_warnings)
    cache_values = [u.get("cached_tokens") for u in native_usage]
    cached = sum(cache_values) if cache_values and all(v is not None for v in cache_values) else None
    pricing_path = run_dir / "report-pricing.json"
    pricing = json.loads(pricing_path.read_text(encoding="utf-8")) if pricing_path.is_file() else None
    estimate = estimate_cost(run, native_usage, pricing)
    estimate_label = (
        f"{'额度价值估算' if pricing['kind'] == 'subscription_allowance' else '目录价格估算'} USD："
        f"${estimate['low']:.8f}–${estimate['high']:.8f}（非实际扣费）"
        if estimate else "成本估算不可用：缺少适用价格或完整、可核对的用量。"
    )
    parts = [token_parts(u) for u in native_usage]
    if parts and all(p is not None for p in parts):
        token_note = f"非缓存输入 {_number(sum(p[0] for p in parts))} + 缓存读取 {_number(cached)} + 输出 {_number(sum(p[2] for p in parts))} = 总 Token {_number(usage['total_tokens']['total'])}。"
    else:
        token_note = "缓存是否包含在输入 Token 内需按提供方口径核对；未知值不补零。"
    performance_notes = []
    if summary["latency_median"] and summary["latency_p95"] is not None:
        performance_notes.append(f"本批 P95 约为 P50 的 {summary['latency_p95'] / summary['latency_median']:.1f} 倍；混合执行层级，不能据此判定模型慢或发生重试。")
    if parts and all(p is not None for p in parts):
        total = sum(sum(p) for p in parts)
        if total:
            performance_notes.append(f"可核对 Token 中，输入（含缓存读取）占 {100 * sum(p[0] + p[1] for p in parts) / total:.1f}%，输出占 {100 * sum(p[2] for p in parts) / total:.1f}%；这是用量结构，不代表冗余率或效率达标。")
    cost_html = "<p>" + _escape(estimate_label) + "</p>"
    if estimate:
        cost_html += (
            f'<p>价格核对日期：{_escape(pricing["checked_at"])} · <a href="{_escape(pricing["source"])}">价格来源</a>。'
            "按下列价格情景估算；没有恢复运行时峰谷档位，不代表历史账单或订阅现金支出。</p>"
            "<details><summary>计算口径与价格快照</summary><pre>"
            + _escape(_pretty(estimate)) + "</pre></details>"
        )
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
            f"{summary['observed_unique_tasks']} 个已执行任务 · {summary['missing_trials']} 次执行缺失",
        ),
        (
            "计划通过率",
            _percent(pass_count, planned),
            f"{pass_count} PASS · {counts.get('FAIL', 0)} FAIL · {counts.get('INVALID', 0)} INVALID",
        ),
        (
            "Agent 总 Token",
            _number(usage["total_tokens"]["total"]),
            f"用量已知 {usage['total_tokens']['known_trials']}/{len(rows)} 次执行",
        ),
        (
            "延迟 P50 / P95",
            f"{_number(summary['latency_median'])} / {_number(summary['latency_p95'])} s",
            f"费用 USD：{_number(usage['cost_usd']['total'])}；{estimate_label}",
        ),
    ]
    if "agent" in partitions["groups"] and "deterministic" in partitions["groups"]:
        cards[1] = ("真实模型执行通过率", _percent(partitions["groups"]["agent"]["passed"], partitions["groups"]["agent"]["trials"]), "仅已执行真实模型案例；确定性检查另列")
    agent_usage = partitions["usage"]["agent"]
    if agent_usage["calls"]:
        cards[2] = ("Agent 已知 Token", str(agent_usage["known_total_tokens"]), f"{agent_usage['unknown_calls']}次请求用量未知；Judge用量另列")
    cards_html = "".join(
        f'<span class="summary-stat" title="{_escape(note)}"><span class="muted">{_escape(label)}</span>'
        f"<strong>{_escape(value)}</strong></span>"
        for label, value, note in cards
    )
    identity_display = {
        "report_diagnostics": {"analysis_id": analysis["analysis_id"], "rules_version": analysis["rules_version"], "rules_sha256": analysis["rules_sha256"], "source_hash": analysis["source_hash"], "profile": analysis["profile"]},
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
    issue_options = "".join(
        f'<option value="{_escape(n)}">问题 #{_escape(n)} · {_escape(title)}</option>'
        for n, title in sorted({f["number"]: f["title"] for row in rows for f in row.get("_report_findings", [])}.items())
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
        '<p class="muted">本次运行超过 100 次执行。主报告保留筛选和评分理由，'
        "完整轨迹按单次执行拆为离线详情页；分享时请将 report-trials/ 目录一并保留。</p>"
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
        f"<p>{_escape(title)} · {_escape(runtime.get('agent', runtime.get('provider_id', run.get('config', {}).get('provider', '未标注运行主体'))))} · "
        f"请求模型：{_escape(runtime.get('model', '未知'))}<br>"
        f"数据集：{_escape(dataset.get('dataset_id', '未知'))} · "
        f"Inspect 执行 → DeepEval 评分 → 本地证据报告</p></header><main>"
        f'<div class="summary-strip" aria-label="本轮概览">{cards_html}</div>'
        + '<nav class="report-nav" aria-label="报告目录"><a href="#scope">范围与比较</a><a href="#findings">问题摘要</a><a href="#actions">修复建议</a><a href="#methodology">统计口径</a><a href="#category-summary">任务类别</a><a href="#identity-audit">用量与身份</a><a href="#trial-results">逐条结果</a></nav>'
        + run_links_html + evaluation_html(partitions)
        + scope_html(run, tasks)
        + '<p class="muted performance-note">' + _escape(" ".join(performance_notes)) + ' 未应用性能验收阈值；<a href="#methodology">查看口径</a>。</p>'
        + _overview_html(rows, contracts, warnings)
        +
        '<details class="evidence-group" data-evidence="basis" id="methodology"><summary>统计口径与冻结证据</summary>'
        + METHODOLOGY_HTML
        + '<ul class="summary-notes">' + ''.join(f'<li>{_escape(note)}</li>' for _, _, note in cards) + '</ul>'
        + '<p class="muted">报告只展示已保存结果，不调用模型、不重新评分。'
        "PASS 同时要求任务结果与正式约束通过；INVALID / INCONCLUSIVE 与 FAIL 分开统计。</p>"
        f"<p>有效执行通过率：{_percent(pass_count, summary['valid_trials'])}；"
        f"每个任务全部 {summary['trials_per_case']} 次计划执行通过："
        f"{summary['all_trials_pass_tasks']}/{summary['unique_tasks']}。"
        "缺失或无效执行不能证明全部通过。</p></details>"
        '<details class="evidence-group" data-evidence="category" id="category-summary"><summary>按任务类别</summary>'
        + _group_table(summary["by_category"])
        + '</details><details class="evidence-group" data-evidence="split"><summary>按数据划分</summary>'
        + _group_table(summary["by_split"])
        + '</details><details class="evidence-group" data-evidence="level"><summary>评测层次</summary>'
        + _group_table(summary["by_evaluation_level"])
        + "<p>模块直接执行与真实模型任务分开统计；总体数量不代表单一模型成功率。</p></details>"
        + ("<section><h2>LLM Judge 量化（未完成人工校准）</h2><pre>"
           + _escape(_pretty({"summary": run["judge_summary"], "stability": run.get("judge_stability"),
                             "judge_usage": run.get("judge_usage")})) + "</pre></section>" if "judge_summary" in run else "")
        +
        '<details class="evidence-group" data-evidence="identity" id="identity-audit"><summary>用量与身份 · 配置、模型与价格来源</summary>'
        f"<p>输入 Token：{_number(usage['input_tokens']['total'])} · "
        f"输出 Token：{_number(usage['output_tokens']['total'])} · "
        f"缓存命中 Token：{_number(cached)}。"
        "prompt_tokens / completion_tokens 仅按字段别名展示，不重复累加。</p>"
        f"<p>{_escape(token_note)}</p>"
        + cost_html
        +
        f"<p>响应实际模型：{_escape(', '.join(models) or '未知')}。"
        "字节估算 tokenizer 仅用于 Agent 上下文预算，以上用量来自模型响应。</p>"
        "<details><summary>数据集、Agent、评分与运行配置</summary>"
        f"<pre>{_escape(_pretty(identity_display))}</pre></details>"
        "<details><summary>用量完整性及已知部分</summary>"
        f"<pre>{_escape(_pretty({'saved_summary': usage, 'report_usage': native_usage, 'native_sources': usage_sources}))}</pre></details>"
        f"<details><summary>数据集限制与来源</summary><ul>{limitations}</ul>"
        f"<pre>{_escape(_pretty(dataset.get('provenance', {})))}</pre></details></details>"
        '<h2 id="trial-results">逐条结果与完整 Trace</h2>' + detail_notice + '<div class="controls">'
        '<input id="search" aria-label="搜索任务" placeholder="搜索任务 ID">'
        f'<select id="verdict" aria-label="结果筛选"><option value="">全部结果</option>{verdict_options}</select>'
        f'<select id="category" aria-label="类别筛选"><option value="">全部类别</option>{categories}</select>'
        f'<select id="issue" aria-label="问题筛选"><option value="">全部问题</option>{issue_options}</select>'
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
        token_note,
        estimate_label,
        "",
        _overview_html(rows, contracts, warnings),
        cost_html,
        "",
        "## 分组",
        "",
        "| 维度 | 分组 | 任务 | 执行次数 | 通过（PASS） | 失败（FAIL） | 执行无效（INVALID） | 证据不足（INCONCLUSIVE） |",
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
                    f"### {_escape(row['case_id'])} · 第 {row['trial']} 次执行",
                    "",
                    f"{_escape(assessment['verdict'])} / {_escape(assessment.get('validity', '未知'))}",
                    "",
                    *[f"- {_escape(item['metric'])}：期望 {_escape(item['expected'])}；实际 {_escape(item['actual'])}。" for item in comparisons(row)],
                    *[f"- 同问题 #{finding['number']}：{_escape(finding.get('short', finding['title']))}" for finding in row.get('_report_findings', [])],
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
            "超过 100 次执行 时，完整轨迹拆分到 report-trials/；请连同主报告一起保留。",
            "来源：[保存结果](results.json)。报告仅聚合已保存 verdict，不重新评分或调用网络。",
            "",
        ]
    )
    (run_dir / "report.md").write_text("\n".join(markdown), encoding="utf-8")
    return path
