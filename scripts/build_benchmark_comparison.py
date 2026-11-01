"""根据不可变的历史证据生成离线对比报告。

读取保存的比较结果与两组运行，核验统计口径并输出可阅读的 HTML。
不导入 Agent、不调用模型，也不重新计算任何判定。
"""

# Preserve readable HTML/CSS template literals without wrapping their markup.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

LABELS = {
    "read_search": "读取与搜索",
    "create_edit": "创建与编辑",
    "multi_file": "多文件、多步骤",
    "multi_turn": "多轮需求变更",
    "missing_error": "缺失资源与异常",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def delta(value: float) -> str:
    return f"{value * 100:+.2f} pp"


def tone(value: float) -> str:
    return "negative" if value < 0 else "positive" if value > 0 else "neutral"


def load_run(path: Path) -> dict:
    """Reduce one large result at a time, checking summaries against trials."""
    raw = path.read_bytes()
    run = json.loads(raw)
    result_hash = hashlib.sha256(raw).hexdigest()
    del raw
    if run.get("mode") != "real_agent" or run["identity"].get("offline"):
        raise ValueError("comparison page requires real Agent runs")
    records = run["trials"]
    counts = Counter(row["assessment"]["verdict"] for row in records)
    planned_ids = run["planned_case_ids"]
    repeats = run["trials_per_case"]
    expected = {
        (case, trial) for case in planned_ids for trial in range(1, repeats + 1)
    }
    pairs = {
        (row["case_id"], row["trial"]): row["assessment"]["verdict"] for row in records
    }
    if len(pairs) != len(records) or set(pairs) != expected:
        raise ValueError("comparison requires complete, unique planned trial evidence")
    summary = run["summary"]
    if summary["completed_trials"] != len(records) or summary["verdicts"] != dict(
        counts
    ):
        raise ValueError("summary disagrees with saved verdicts")
    valid = sum(row["assessment"]["validity"] == "VALID" for row in records)
    if summary["valid_trials"] != valid or summary["planned_trials"] != len(expected):
        raise ValueError("saved validity or planned denominator is inconsistent")
    success = counts["PASS"] / len(expected)
    all_pass = sum(
        all(pairs[(case, trial)] == "PASS" for trial in range(1, repeats + 1))
        for case in planned_ids
    )
    if abs(summary["pass_rate_planned"] - success) > 1e-12:
        raise ValueError("saved pass rate is inconsistent")
    if abs(summary["all_trials_pass_rate"] - all_pass / len(planned_ids)) > 1e-12:
        raise ValueError("saved repeat-success rate is inconsistent")
    for dimension in ("category", "split"):
        groups = defaultdict(list)
        for row in records:
            groups[row[dimension]].append(row)
        for name, rows in groups.items():
            group = summary["by_" + dimension][name]
            group_counts = dict(Counter(row["assessment"]["verdict"] for row in rows))
            if group["trials"] != len(rows) or group["verdicts"] != group_counts:
                raise ValueError(f"saved {dimension} summary is inconsistent: {name}")
            if (
                abs(
                    group["pass_rate_observed"]
                    - group_counts.get("PASS", 0) / len(rows)
                )
                > 1e-12
            ):
                raise ValueError(f"saved {dimension} rate is inconsistent: {name}")
    models = sorted(
        {
            event["response_model"]
            for row in records
            for event in row["observation"].get("events", [])
            if event.get("type") == "generation" and event.get("response_model")
        }
    )
    return {
        "run_id": run["run_id"],
        "identity": run["identity"],
        "identity_hash": run["identity_hash"],
        "summary": summary,
        "config": run["config"],
        "pairs": pairs,
        "all_pass": all_pass,
        "result_sha256": result_hash,
        "models": models,
        "finished_at": run.get("finished_at"),
        "path": path,
    }


STYLE = """
:root{--ink:#172d42;--muted:#647689;--line:#dce5ed;--blue:#2765a1;
--teal:#087c77;--amber:#be7c2d;--red:#b04445;--paper:#f2f6f9}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.topline{height:46px;background:#152d43;color:#d9e8f5;display:flex;align-items:center;
justify-content:space-between;padding:0 max(32px,calc((100% - 1380px)/2));font-size:11px;letter-spacing:.12em}
main{max-width:1444px;margin:auto;padding:27px 32px 40px}
.hero{display:flex;justify-content:space-between;gap:28px;align-items:center;margin-bottom:22px}
.eyebrow{color:var(--teal);font-size:11px;font-weight:750;letter-spacing:.1em}
h1{font-size:33px;line-height:1.35;letter-spacing:-.025em;margin:8px 0 9px;font-weight:750}
.subtitle{margin:0;color:var(--muted);font-size:14px}.chips{display:flex;gap:7px;flex-wrap:wrap;max-width:350px;justify-content:flex-end}
.chip{background:white;border:1px solid var(--line);border-radius:6px;padding:6px 10px;font-size:11px;white-space:nowrap}
.chip.live{color:#08645b;background:#e1f3ec;border-color:#cce7dc;font-weight:650}
.kpis{display:grid;grid-template-columns:1fr 1fr .9fr 1.15fr;gap:15px;margin:0 0 22px}
.card{background:white;border:1px solid var(--line);border-radius:12px;padding:18px 21px;position:relative;overflow:hidden}
.card::before{content:"";height:3px;position:absolute;top:0;left:0;right:0;background:#acbccb}
.card.baseline::before{background:var(--blue)}.card.candidate::before{background:var(--amber)}
.card.change{background:#fff8f6;border-color:#eedbd5}.card.change::before{background:var(--red)}
.card .label{font-size:12px;color:var(--muted);display:flex;justify-content:space-between;gap:8px}
.card .label b{font-size:10px;letter-spacing:.07em;font-weight:600}
.big{font-size:42px;font-weight:750;letter-spacing:-.04em;line-height:1.2;margin:10px 0 7px}
.baseline .big{color:var(--blue)}.candidate .big{color:#a06925}.change .big{color:var(--red)}
.big small{font-size:20px;letter-spacing:0}.card .foot{font-size:12px;color:var(--muted)}
.repeat{font-size:28px;letter-spacing:-.035em;white-space:nowrap}.arrow{font-weight:400;color:#9aa9b6;margin:0 5px}
.body-grid{display:grid;grid-template-columns:1.55fr 1fr;gap:20px}
.panel{background:white;border:1px solid var(--line);border-radius:12px;padding:20px 23px}
.section-title{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:13px}
h2{font-size:17px;letter-spacing:-.01em;margin:0}.hint{font-size:11px;color:var(--muted)}
.legend{display:flex;gap:13px;font-size:11px;color:var(--muted)}.dot{width:7px;height:7px;border-radius:50%;display:inline-block;margin-right:5px}
.dot.blue{background:var(--blue)}.dot.amber{background:var(--amber)}
table{border-collapse:collapse;width:100%;font-size:12px}th,td{text-align:left;padding:11px 8px;border-bottom:1px solid #e8eef4;vertical-align:middle}
th{font-size:11px;color:var(--muted);font-weight:500;padding-top:4px;padding-bottom:10px}td:first-child,th:first-child{padding-left:0}
td:last-child,th:last-child{text-align:right;padding-right:0}tbody tr:last-child td{border-bottom:0}
.category-name{font-weight:600;white-space:nowrap}.instances{display:block;color:var(--muted);font-size:10px;font-weight:400;margin-top:2px}
.rate{font-variant-numeric:tabular-nums;font-weight:650;white-space:nowrap}.rate small{font-size:10px;font-weight:400;color:var(--muted);margin-left:4px}
.bar{height:4px;background:#edf2f6;border-radius:9px;margin-top:7px;min-width:115px;overflow:hidden}.bar i{display:block;height:100%;border-radius:9px}
.bar.blue i{background:var(--blue)}.bar.amber i{background:var(--amber)}
.negative{color:var(--red)}.positive{color:var(--teal)}.neutral{color:var(--muted)}.delta{font-weight:650;white-space:nowrap;font-variant-numeric:tabular-nums}
.split{padding:11px 0 14px;border-bottom:1px solid #e8eef4}.split:last-of-type{border-bottom:0}
.split-top{display:flex;justify-content:space-between;align-items:center}.split-top b{font-size:13px}.split-top span{font-size:11px}
.split-values{display:flex;align-items:baseline;gap:9px;margin-top:8px;font-size:21px;font-weight:650}
.split-values .arrow{font-size:17px}.split-values small{font-size:11px;color:var(--muted);font-weight:400}
.paired{background:#f4f7fa;border-radius:7px;padding:11px 13px;margin-top:9px;display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:11px;color:var(--muted)}
.paired b{font-size:17px;margin-right:3px}.paired small{font-size:10px}
.reading{margin:17px 0 0;padding:15px 19px;background:#eaf1f5;border-left:3px solid #7599b3;border-radius:0 8px 8px 0;color:#405b72;font-size:12px}
.reading strong{display:block;color:#213e56;font-size:13px;margin-bottom:3px}
.bottom{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-top:18px}.links{display:flex;gap:10px;flex-wrap:wrap}
a{color:var(--blue);text-decoration:none}.button{display:inline-block;padding:9px 14px;border-radius:7px;background:white;border:1px solid #c8d7e3;font-size:12px;font-weight:600}
.button.primary{background:#173e5d;color:white;border-color:#173e5d}.audit-label{text-align:right;font-size:10px;color:var(--muted);line-height:1.8}
.more{margin-top:22px;display:grid;grid-template-columns:1fr 1fr;gap:20px}.more h2{font-size:15px}.more p,.more li{font-size:12px;color:var(--muted)}
details{margin:11px 0}summary{cursor:pointer;color:#35536c;font-size:12px;font-weight:600}pre{white-space:pre-wrap;word-break:break-word;font:11px/1.7 ui-monospace,monospace;background:#f4f7fa;border-radius:6px;padding:12px;max-height:380px;overflow:auto}
.hash{font:10px/1.7 ui-monospace,monospace;color:#597286;overflow-wrap:anywhere}.hash b{font-family:inherit;color:#314c63;font-weight:500}
.limits{padding-left:18px;margin-bottom:0}.meta-foot{font-size:10px;color:var(--muted);margin-top:18px}
@media(min-width:1500px){main{padding-top:30px}.panel{padding:20px 25px}.hero{margin-bottom:23px}}
@media(max-width:1100px){.hero{align-items:flex-start}.chips{max-width:280px}.kpis{grid-template-columns:1fr 1fr}.body-grid{grid-template-columns:1fr}h1{font-size:29px}.more{grid-template-columns:1fr}}
@media(max-width:650px){main{padding:20px 16px}.topline{padding:0 16px}.topline span:last-child{display:none}.hero{display:block}.chips{justify-content:flex-start;max-width:none;margin-top:16px}.big{font-size:34px}.repeat{font-size:24px}.card{padding:15px}.panel{padding:17px}.bottom{display:block}.audit-label{text-align:left;margin-top:12px}.bar{min-width:75px}.rate small{display:block;margin-left:0}h1{font-size:26px}}
"""


def build(
    comparison_path: Path,
    baseline_path: Path,
    candidate_path: Path,
    output: Path,
    *,
    public_evidence_dir: Path | None = None,
) -> Path:
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    baseline, candidate = load_run(baseline_path), load_run(candidate_path)
    for side, run in (("baseline", baseline), ("candidate", candidate)):
        if (
            comparison[f"{side}_run_id"] != run["run_id"]
            or comparison[side] != run["summary"]
        ):
            raise ValueError(f"comparison.json does not match {side} results")
    for field in (
        "dataset",
        "scoring_identity",
        "harness_source",
        "case_ids",
        "repeats",
    ):
        if baseline["identity"][field] != candidate["identity"][field]:
            raise ValueError(f"comparison control differs: {field}")
    actual_changes = {
        name: [baseline["config"].get(name), candidate["config"].get(name)]
        for name in baseline["config"].keys() | candidate["config"].keys()
        if baseline["config"].get(name) != candidate["config"].get(name)
    }
    if actual_changes != comparison["configuration_changes"]:
        raise ValueError("comparison configuration changes do not match saved runs")
    if set(actual_changes) - {"instructions", "variant"}:
        raise ValueError("this presentation describes a controlled prompt experiment")
    left, right = baseline["summary"], candidate["summary"]
    change = right["pass_rate_planned"] - left["pass_rate_planned"]
    if abs(change - comparison["pass_rate_delta"]) > 1e-12:
        raise ValueError("comparison delta disagrees with evidence")
    improved = sum(
        value != "PASS" and candidate["pairs"][key] == "PASS"
        for key, value in baseline["pairs"].items()
    )
    regressed = sum(
        value == "PASS" and candidate["pairs"][key] != "PASS"
        for key, value in baseline["pairs"].items()
    )
    left_pass, right_pass = (
        left["verdicts"].get("PASS", 0),
        right["verdicts"].get("PASS", 0),
    )
    dataset, runtime = baseline["identity"]["dataset"], baseline["identity"]["runtime"]
    rows = []
    for category in LABELS:
        a, b = left["by_category"][category], right["by_category"][category]
        difference = b["pass_rate_observed"] - a["pass_rate_observed"]
        cells = []
        for name, color in ((a, "blue"), (b, "amber")):
            rate = name["pass_rate_observed"]
            cells.append(
                f'<td><div class="rate">{percent(rate)}<small>{name["verdicts"].get("PASS", 0)}/{name["trials"]}</small></div>'
                f'<div class="bar {color}"><i style="width:{rate * 100:.4f}%"></i></div></td>'
            )
        rows.append(
            f'<tr><td class="category-name">{LABELS[category]}<span class="instances">{a["unique_tasks"]} 个任务 × {left["trials_per_case"]} 次</span></td>'
            + "".join(cells)
            + f'<td class="delta {tone(difference)}">{delta(difference)}</td></tr>'
        )
    split_cards = []
    for name, label in (("dev", "开发集 / Dev"), ("holdout", "保留集 / Holdout")):
        a, b = left["by_split"][name], right["by_split"][name]
        difference = b["pass_rate_observed"] - a["pass_rate_observed"]
        split_cards.append(
            '<div class="split"><div class="split-top">'
            f'<b>{label}</b><span class="delta {tone(difference)}">{delta(difference)}</span></div>'
            f'<div class="split-values">{percent(a["pass_rate_observed"])}<span class="arrow">→</span>{percent(b["pass_rate_observed"])}</div>'
            f'<div class="hint">{a["verdicts"].get("PASS", 0)}/{a["trials"]} → {b["verdicts"].get("PASS", 0)}/{b["trials"]} · {a["unique_tasks"]} 个任务</div></div>'
        )

    def relative_link(path: Path) -> str:
        return esc(quote(os.path.relpath(path, output.parent)))

    baseline_link = relative_link(baseline_path.with_name("report.html"))
    candidate_link = relative_link(candidate_path.with_name("report.html"))
    comparison_link = relative_link(comparison_path)
    baseline_label, candidate_label = "查看基线逐条报告", "查看候选逐条报告"
    evidence_note = "完整轨迹通过本地相对链接查看。"
    usage_note = "输入 / 输出 Token 和延迟详见逐条报告。"
    if public_evidence_dir is not None:
        # Public evidence is deliberately a smaller export, not a trace archive.
        public_comparison = public_evidence_dir / "comparison.json"
        if json.loads(public_comparison.read_text(encoding="utf-8")) != comparison:
            raise ValueError("public comparison.json differs from source evidence")
        public_links = []
        for run_path, run in ((baseline_path, baseline), (candidate_path, candidate)):
            trial_path = public_evidence_dir / f"{run_path.parent.name}-trials.jsonl"
            pairs = {}
            for line in trial_path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                key = (row["case_id"], row["trial"])
                if key in pairs or row["identity_hash"] != run["identity_hash"]:
                    raise ValueError(
                        "public trial evidence has duplicate or wrong identity"
                    )
                pairs[key] = row["assessment"]["verdict"]
            if pairs != run["pairs"]:
                raise ValueError("public trial verdicts differ from source evidence")
            public_links.append(relative_link(trial_path))
        baseline_link, candidate_link = public_links
        comparison_link = relative_link(public_comparison)
        baseline_label, candidate_label = "基线逐条评分 JSONL", "候选逐条评分 JSONL"
        evidence_note = (
            "此公开证据页链接的 JSONL 只包含逐条评分与运行摘要，不包含完整原始轨迹；"
            "完整模型输入输出、工具调用和文件状态保存在本地运行目录与 Langfuse 中。"
        )
        usage_note = "输入 / 输出 Token 见摘要 JSON，逐条延迟见评分 JSONL。"
    direction = "下降" if change < 0 else "提高" if change > 0 else "持平"
    conclusion = (
        "候选配置没有带来整体提升。保留基线结果，记录局部变化与代价。"
        if change < 0
        else "这只是本次固定任务上的描述性对比，不能据此推断统计显著性。"
    )
    split_deltas = {
        name: right["by_split"][name]["pass_rate_observed"]
        - left["by_split"][name]["pass_rate_observed"]
        for name in ("dev", "holdout")
    }
    reading = (
        "Holdout 的局部提升没有抵消 Dev 的下降；"
        if split_deltas["holdout"] > 0 and split_deltas["dev"] < 0 and change < 0
        else f"Dev 变化 {delta(split_deltas['dev'])}，Holdout 变化 {delta(split_deltas['holdout'])}；"
    )
    source = {
        "dataset_sha256": dataset["tasks_sha256"],
        "scoring_identity": baseline["identity"]["scoring_identity"],
        "harness_source": baseline["identity"]["harness_source"],
        "agent_source_commit": runtime["source_commit"],
        "agent_working_tree_sha256": runtime["working_tree_sha256"],
        "agent_source_dirty": runtime["source_dirty"],
        "baseline_run_id": baseline["run_id"],
        "candidate_run_id": candidate["run_id"],
        "baseline_results_sha256": baseline["result_sha256"],
        "candidate_results_sha256": candidate["result_sha256"],
        "baseline_response_models": baseline["models"],
        "candidate_response_models": candidate["models"],
    }
    total = left["completed_trials"] + right["completed_trials"]
    markdown_prompt = comparison["configuration_changes"].get("instructions", ["", ""])[
        1
    ]
    document = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        f"<title>工具型 Agent 对比实验 · {esc(dataset['dataset_id'])}</title><style>{STYLE}</style></head><body>"
        '<div class="topline"><span>Agent Eval Suite / 评测证据</span><span>Inspect 执行 · DeepEval 评分</span></div>'
        '<main><div class="hero"><div><div class="eyebrow">工具型 AGENT · 真实执行对比</div>'
        f"<h1>工具提示实验：整体通过率{direction} {abs(change) * 100:.2f} 个百分点</h1>"
        f'<p class="subtitle">{left["unique_tasks"]} 条冻结任务 × {left["trials_per_case"]} 次重复 × 2 种配置 · '
        f"{total:,} 次真实执行 · 相同数据集、评分与 Harness 版本</p></div>"
        '<div class="chips"><span class="chip live">真实 Agent 执行</span>'
        f'<span class="chip">nanobot / {esc(runtime["model"])}</span>'
        '<span class="chip">四种文件工具 · 受限 SDK</span>'
        f'<span class="chip">{esc(dataset["dataset_id"])} · {dataset["family_count"]} 个任务族</span></div></div>'
        '<div class="kpis"><div class="card baseline"><div class="label">基线配置<b>基线</b></div>'
        f'<div class="big">{percent(left["pass_rate_planned"])}</div><div class="foot">{left_pass} / {left["planned_trials"]} 次执行通过 · {left["verdicts"].get("FAIL", 0)} 次失败</div></div>'
        '<div class="card candidate"><div class="label">工具范围提示<b>工具范围提示</b></div>'
        f'<div class="big">{percent(right["pass_rate_planned"])}</div><div class="foot">{right_pass} / {right["planned_trials"]} 次执行通过 · {right["verdicts"].get("FAIL", 0)} 次失败</div></div>'
        '<div class="card change"><div class="label">总体变化<b>候选 − 基线</b></div>'
        f'<div class="big">{change * 100:+.2f}<small> pp</small></div>'
        f'<div class="foot">通过次数变化 {right_pass - left_pass:+d} · 不做显著性结论</div></div>'
        f'<div class="card"><div class="label">全部重复均通过的任务<b>{left["trials_per_case"]} 次执行全部通过</b></div>'
        f'<div class="big repeat">{percent(left["all_trials_pass_rate"])}<span class="arrow">→</span>{percent(right["all_trials_pass_rate"])}</div>'
        f'<div class="foot">{baseline["all_pass"]}/{left["unique_tasks"]} → {candidate["all_pass"]}/{right["unique_tasks"]} 个任务 · 不是 pass@k</div></div></div>'
        '<div class="body-grid"><section class="panel"><div class="section-title"><h2>各类任务表现</h2>'
        '<div class="legend"><span><i class="dot blue"></i>基线</span><span><i class="dot amber"></i>工具范围提示</span></div></div>'
        "<table><thead><tr><th>任务类别</th><th>基线通过率</th><th>候选通过率</th><th>变化</th></tr></thead><tbody>"
        + "".join(rows)
        + '</tbody></table></section><section class="panel"><div class="section-title"><h2>数据划分与配对变化</h2>'
        '<span class="hint">按完整任务族划分</span></div>'
        + "".join(split_cards)
        + '<div class="paired"><span>相同用例与执行序号<br><small>仅描述结果转移</small></span>'
        f'<span class="positive"><b>{improved}</b> 次转好</span><span class="negative"><b>{regressed}</b> 次回退</span></div></section></div>'
        f'<div class="reading"><strong>{conclusion}</strong>'
        + reading
        + "任务实例存在族内相关性，重复执行也不能视为完全独立样本。"
        "所有比较均来自保存的正式判定，没有用 Judge 诊断分替代成功率。</div>"
        '<div class="bottom"><div class="links">'
        f'<a class="button primary" href="{baseline_link}">{baseline_label} →</a>'
        f'<a class="button" href="{candidate_link}">{candidate_label} →</a>'
        f'<a class="button" href="{comparison_link}">原始对比 JSON ↗</a></div>'
        f'<div class="audit-label">有效执行 {left["valid_trials"]} + {right["valid_trials"]} · 缺失 {left["missing_trials"] + right["missing_trials"]}<br>'
        "相同任务与评分 Hash · 仅修改候选 instructions / variant</div></div>"
        '<div class="more"><section class="panel"><div class="section-title"><h2>实验控制与证据身份</h2>'
        '<span class="hint">可展开完整摘要</span></div>'
        f'<div class="hash"><b>Dataset</b> {esc(dataset["tasks_sha256"])}<br>'
        f"<b>Scorer</b> {esc(baseline['identity']['scoring_identity']['source_sha256'])}<br>"
        f"<b>Harness</b> {esc(baseline['identity']['harness_source'])}</div>"
        "<details><summary>运行、模型响应与源码完整身份</summary>"
        f"<pre>{esc(json.dumps(source, ensure_ascii=False, indent=2))}</pre></details>"
        "<details><summary>候选新增的工具范围提示原文</summary>"
        f"<pre>{esc(markdown_prompt)}</pre></details>"
        "<p>nanobot 工作树含未提交修改，commit 与工作树摘要同时保留。"
        f"模型费用未验证，记为未知；{usage_note}</p></section>"
        '<section class="panel"><h2>结论适用范围</h2><ul class="limits">'
        "<li>仅四种本地文件工具；是真实 nanobot SDK 的受限配置，不代表原生全工具能力或生产安全性。</li>"
        f"<li>{dataset['case_count']} 条合成实例来自 {dataset['family_count']} 个任务族，未经过用户逐条人工审核；不能称为官方 τ-bench / BFCL / SWE-bench 成绩。</li>"
        "<li>正式评分是 DeepEval 确定性终态、工作区约束与交互证据检查；工具覆盖和 G-Eval 是诊断，不决定正式判定。</li>"
        "<li>这是描述性配对实验，不声称统计显著或跨领域泛化。文件格式误差、被拒绝的工具尝试与真正副作用应分别解释。</li>"
        "</ul></section></div>"
        '<p class="meta-foot">页面根据 comparison.json 与两份真实 results.json 生成，并核对执行次数、分组与汇总一致性。'
        f"页面自包含，无网络资源、外部字体或模型调用；{evidence_note}</p></main></body></html>"
    )
    if len(document.encode("utf-8")) >= 100_000:
        raise ValueError("compact comparison page exceeded 100 KB")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--comparison", type=Path, default=Path("artifacts/benchmark/comparison.json")
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("artifacts/benchmark/baseline300x3/results.json"),
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        default=Path("artifacts/benchmark/tool-aware300x3/results.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="输出 HTML；指定公开证据目录时默认输出到该目录，否则输出到 artifacts/benchmark。",
    )
    parser.add_argument(
        "--public-evidence-dir",
        type=Path,
        help="链接现有公开评分 JSONL 和 comparison.json，不链接本地完整报告；不会发布或上传。",
    )
    args = parser.parse_args()
    output = args.output or (
        (args.public_evidence_dir or Path("artifacts/benchmark")) / "comparison.html"
    )
    path = build(
        args.comparison,
        args.baseline,
        args.candidate,
        output,
        public_evidence_dir=args.public_evidence_dir,
    )
    print(
        json.dumps(
            {"artifact": str(path.resolve()), "bytes": path.stat().st_size},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
