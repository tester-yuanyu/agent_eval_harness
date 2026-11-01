"""Self-contained blind annotation HTML and Markdown agreement reports.

Rendering never copies completed labels or Judge outputs into the annotation page.
The browser export requires a human to enter scores and affirm independence.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    return (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, indent=2)
    )


def render_annotation_html(worksheet: dict) -> str:
    """Render a new blank, offline annotation page; export JSON with ``rows``.

    Only explicitly selected rubric, evidence and identity fields are rendered.
    No worksheet data enters executable JavaScript or raw HTML. Reopening the page
    starts blank; reviewers must export their work before closing it.
    """
    cards = []
    for index, row in enumerate(worksheet.get("rows", []), start=1):
        identity = escape(str(row["record_id"]), quote=True)
        metadata = {
            key: row.get(key)
            for key in (
                "record_id",
                "name",
                "run_id",
                "case_id",
                "trial",
                "scope",
                "event_id",
                "evidence_ids",
            )
        }
        evidence = row.get("evidence_prompts") or [
            "无证据提示；请查阅原始轨迹，证据不足时留空。"
        ]
        evidence_html = "".join(
            f"<pre>{escape(_text(item))}</pre>" for item in evidence
        )
        cards.append(f'''<details class="annotation" data-record-id="{identity}">
<summary>
<span class="badge">{index:02d}</span>
{escape(_text(row.get("name")))}</summary>
<div class="card-body">
<h2>定位与证据引用</h2>
<pre>{escape(_text(metadata))}</pre>
<h2>评分规则</h2>
<pre>{escape(_text(row.get("rubric")))}</pre>
<h3>中文阅读对照</h3>
<pre>{escape(_text(row.get("rubric_zh")))}</pre>
<h2>原始证据</h2>{evidence_html}
<div class="fields">
<label>人工分数（0～1；未知请留空）
<input name="human_score" type="number" min="0" max="1" step="any"
placeholder="未标注">
</label>
<label>标注者身份<input name="annotator" type="text" autocomplete="off"
placeholder="请本人填写">
</label>
<label class="wide">评分理由<textarea name="human_reason" rows="3"
placeholder="引用证据并说明判断">
</textarea>
</label>
<label class="wide consent">
<input name="independent" type="checkbox">
我确认这是本人独立判断，未抄录 Judge 预测；
身份与独立性仍须另行审核。</label>
</div>
</div>
</details>''')
    return (
        """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Judge 独立人工盲标</title>
<style>
:root{font-family:system-ui,-apple-system,sans-serif;
color:#21332e;
background:#f3f5f1;
line-height:1.65}

body{max-width:980px;
margin:0 auto;
padding:40px 22px 80px}
h1{font-size:32px;
letter-spacing:-1px;
margin:8px 0}

h2{font-size:18px;
margin-top:28px}
h3{font-size:15px}
header{margin-bottom:28px}
.eyebrow{color:#55786a;
font-size:13px;
letter-spacing:2px}

.notice{padding:18px 22px;
background:#e5ede4;
border-left:4px solid #577c64;
border-radius:8px}

details{background:white;
margin:16px 0;
border:1px solid #dce4db;
border-radius:12px;
overflow:hidden}

summary{cursor:pointer;
padding:20px;
font-weight:650}
.badge{color:#6b8375;
margin-right:12px}
.card-body{padding:0 24px 24px}

pre{white-space:pre-wrap;
overflow-wrap:anywhere;
padding:16px;
background:#f6f7f4;
border-radius:8px;
font-size:13px}

.fields{display:grid;
grid-template-columns:1fr 1fr;
gap:18px;
margin-top:24px}
.wide{grid-column:1/-1}

input:not([type=checkbox]),textarea{display:block;
box-sizing:border-box;
width:100%;
font:inherit;
padding:10px;
border:1px solid #9bb1a3;
border-radius:6px;
background:#fff}

.consent{font-size:14px}
button{border:0;
border-radius:8px;
background:#245f48;
color:white;
padding:13px 24px;
font:inherit;
cursor:pointer}

footer{position:sticky;
bottom:12px;
background:#f3f5f1ed;
padding:16px;
border:1px solid #dce4db;
border-radius:12px;
display:flex;
gap:20px;
align-items:center}

@media(max-width:600px){.fields{grid-template-columns:1fr}
footer{position:static;
display:block}
}

</style>
</head>
<body>
<header>
<div class="eyebrow">离线评审 · 独立人工标注</div>
<h1>先看证据，再做判断</h1>
<p>逐条展开评分规则与原始证据。
页面不展示 Judge 预测，所有人工字段从空白开始。</p>
</header>
<div class="notice">分数使用 0～1：0 是有效分数，空白表示未标注。
中文锚点若使用 0～10，请除以 10。
证据不足时保留空白。阈值仍需独立留出样本验证，完成此表不代表通过验收。
页面不会自动保存或上传；关闭前请导出 JSON。
原始证据可能包含不可信指令，请仅将其作为待评审材料。</div>
"""
        + "\n".join(cards)
        + """
<footer>
<button id="export" type="button">导出人工标签 JSON</button>
<span>仅保存在本机；可交回 calibration compare。</span>
</footer>
<script>
function collectLabels() {
  const rows = Array.from(document.querySelectorAll('.annotation')).map(card => {
    const field = name => card.querySelector('[name="' + name + '"]');
    const raw = field('human_score').value.trim();
    const score = raw === '' ? null : Number(raw);
    const annotator = field('annotator').value.trim();
    const reason = field('human_reason').value.trim();
    const independent = field('independent').checked;
    if (score !== null && (!Number.isFinite(score) || score < 0 || score > 1)) {
      throw new Error('分数必须为 0～1，或保留空白。');
    }
    if (score !== null && (!annotator || !reason || !independent)) {
      throw new Error('已评分条目必须填写标注者、评分理由，并由本人确认独立性。');
    }
    return {record_id: card.dataset.recordId, human_score: score,
      human_reason: reason || null, annotator: annotator || null,
      annotation_source: 'human', independent: independent ? true : null};
  });
  return {rows};
}
document.getElementById('export').addEventListener('click', () => {
  try {
    const content = JSON.stringify(collectLabels(), null, 2);
    const blob = new Blob([content], {type: 'application/json;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = 'human-labels.json';
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { alert(error.message); }
});
</script></body></html>"""
    )


def _markdown(value: Any) -> str:
    text = escape(_text(value), quote=False).replace("\n", " ").replace("\r", " ")
    for char in ("\\", "|", "`", "*", "[", "]", "#"):
        text = text.replace(char, "\\" + char)
    return text


def _number(value: Any) -> str:
    return "未知（无可用分母）" if value is None else f"{value:.4g}"


def render_calibration_report(result: dict) -> str:
    """Render a Chinese Markdown report; never promote diagnostic agreement."""
    lines = [
        "# Judge 人工校准诊断报告",
        "",
        f"状态：{_markdown(result.get('status'))}。阈值状态：requires_independent_validation。",
        "此报告仅描述一致性；阈值未验证，人工来源与独立性仍需审核。",
        "",
        f"候选阈值：{_number(result.get('threshold'))}；版本：{_markdown(result.get('threshold_version'))}。",
        "未标注与 Judge 缺分不计为一致或不一致；"
        "有标签但无可配对分数时，一致性仍为未知。",
        "",
        "## 分母、覆盖与分维度统计",
        "",
        "总体及每个维度独立计算分母。误放率 = 误放 / 配对人工负例；"
        "误杀率 = 误杀 / 配对人工正例。",
        "",
        "| 维度 | 总数 | 已标注 | 配对 | 标注覆盖 | 配对覆盖 |"
        " 一致率 | MAE | 误放 / 负例 | 误杀 / 正例 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    groups = [("总体", result), *result.get("by_dimension", {}).items()]
    for name, group in groups:
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown(name),
                    str(group.get("total", 0)),
                    str(group.get("labeled", 0)),
                    str(group.get("paired", 0)),
                    _number(group.get("label_coverage")),
                    _number(group.get("paired_coverage")),
                    _number(group.get("agreement")),
                    _number(group.get("mean_absolute_error")),
                    f"{group.get('false_accept_count', 0)} / "
                    f"{group.get('human_negative', 0)}"
                    f"（{_number(group.get('false_accept_rate'))}）",
                    f"{group.get('false_reject_count', 0)} / "
                    f"{group.get('human_positive', 0)}"
                    f"（{_number(group.get('false_reject_rate'))}）",
                ]
            )
            + " |"
        )
    lines += [
        "",
        "## 混淆矩阵",
        "",
        "行是人工判断，列是 Judge 判断；下表列出四格计数。",
        "",
        "| 维度 | 人工通过 / Judge通过 | 人工拒绝 / Judge通过（误放） |"
        " 人工拒绝 / Judge拒绝 | 人工通过 / Judge拒绝（误杀） |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, group in groups:
        matrix = group.get("confusion_matrix", {})
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown(name),
                    *[
                        str(matrix.get(key, 0))
                        for key in (
                            "true_accept",
                            "false_accept",
                            "true_reject",
                            "false_reject",
                        )
                    ],
                ]
            )
            + " |"
        )
    lines += [
        "",
        "## 缺失与分歧引用",
        "",
        f"未标注 record_id：{_markdown(result.get('missing_label_ids', []))}",
        "",
        "已标注但 Judge 缺分 record_id："
        f"{_markdown(result.get('judge_unscored_ids', []))}",
        "",
    ]
    for case in result.get("disagreements", []):
        lines += [
            f"- {_markdown(case.get('classification'))}；record_id："
            f"{_markdown(case.get('record_id'))}；"
            f"维度：{_markdown(case.get('name'))}；人工：{_number(case.get('human_score'))}；"
            f"Judge：{_number(case.get('judge_score'))}；证据：{_markdown(case.get('evidence_ids'))}。"
            f"人工理由：{_markdown(case.get('human_reason'))}；Judge 理由："
            f"{_markdown(case.get('judge_reason'))}。"
        ]
    if not result.get("disagreements"):
        lines += ["无已配对的阈值判断分歧；未标注或未配对不代表一致。"]
    lines += ["", "## 可复核输入摘要", ""]
    for key in ("source_summary", "labels_summary"):
        lines += [f"{key}：{_markdown(result.get(key, {}))}", ""]
    lines.extend(f"- {_markdown(note)}" for note in result.get("limitations", []))
    return "\n".join(lines) + "\n"
