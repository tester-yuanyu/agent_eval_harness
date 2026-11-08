"""离线报告的范围与口径；只描述保存证据，不推测能力或重评分。"""
from __future__ import annotations

from collections import defaultdict
from html import escape


def scope_evidence(run: dict, tasks: dict) -> dict:
    selected = set(run.get("planned_case_ids", []))
    executed = {r["case_id"] for r in run["trials"]}
    tags = defaultdict(lambda: {"planned": 0, "executed": 0})
    for case in sorted(selected):
        for tag in set(tasks.get(case, {}).get("coverage_tags", [])):
            tags[tag]["planned"] += 1
            tags[tag]["executed"] += int(case in executed)
    metrics = defaultdict(lambda: {"recorded": set(), "scored": set()})
    unmarked = 0
    for row in run["trials"]:
        key = (row["case_id"], row["trial"])
        for metric in row["assessment"].get("metrics", []):
            if "formal" not in metric:
                unmarked += 1
            if metric.get("formal") is not True:
                continue
            item = metrics[str(metric.get("name", "未命名"))]
            item["recorded"].add(key)
            if metric.get("status") == "SCORED":
                item["scored"].add(key)
    return {
        "tags": dict(sorted(tags.items())),
        "metrics": {k: {n: len(v) for n, v in counts.items()} for k, counts in sorted(metrics.items())},
        "unmarked_metrics": unmarked,
        "bound_tasks": len(selected & tasks.keys()),
    }


def scope_html(run: dict, tasks: dict) -> str:
    evidence = scope_evidence(run, tasks)
    tag_rows = "".join(
        f"<tr><td>{escape(tag)}</td><td>{c['planned']}</td><td>{c['executed']}</td></tr>"
        for tag, c in evidence["tags"].items()
    )
    metric_rows = "".join(
        f"<tr><td>{escape(name)}</td><td>{c['recorded']}</td><td>{c['scored']}</td></tr>"
        for name, c in evidence["metrics"].items()
    )
    levels = defaultdict(int)
    for row in run["trials"]:
        levels[str(row.get("evaluation_level", "未标注"))] += 1
    level_text = "、".join(f"{escape(k)} {v} 次" for k, v in sorted(levels.items())) or "无保存执行"
    return (
        '<section id="scope" class="report-scope"><h2>评测范围与比较状态</h2>'
        f'<p>本页是选定任务的单轮冻结快照：{level_text}。结论限于本批用例与实际评分约束，不代表 Agent 全部能力。</p>'
        '<p><strong>比较状态：</strong>本页未载入并验证对照运行，不能判断改善或回退；不凭运行先后或补跑记录推断“基线版本”或“修复后版本”。</p>'
        '<p class="muted">安全标签只表示相应用例被选入，不构成安全认证；本页也不提供生产负载、长期稳定性或完整攻击覆盖的结论。</p>'
        '<details><summary>范围证据：任务标签与正式评分项</summary>'
        f'<p>已绑定冻结任务 {evidence["bound_tasks"]}/{len(set(run.get("planned_case_ids", [])))}；只统计本次选定任务。标签可重叠，计数不可相加，未列出的维度不宣称覆盖；任务缺少标签时不能据此断言没有覆盖。</p>'
        '<div class="table-wrap"><table><thead><tr><th>冻结 coverage_tag</th><th>选定任务数</th><th>已执行任务数（去重）</th></tr></thead><tbody>'
        + (tag_rows or '<tr><td colspan="3">无可用冻结标签，覆盖范围待核实。</td></tr>')
        + '</tbody></table></div><p>以下按 case_id + trial 去重，只纳入明确 formal=true 的记录；SCORED 不等于通过。评分项与任务标签没有自动一一对应关系。</p>'
        '<div class="table-wrap"><table><thead><tr><th>正式评分项</th><th>有评分记录的执行数</th><th>状态为 SCORED 的执行数</th></tr></thead><tbody>'
        + (metric_rows or '<tr><td colspan="3">无明确标注的正式评分记录；不能据此宣称能力已验证。</td></tr>')
        + f'</tbody></table></div><p>未标注 formal 的历史 metric 记录：{evidence["unmarked_metrics"]} 条，未用于推定正式评分覆盖；原判定保持不变。</p></details></section>'
    )


METHODOLOGY_HTML = """
<dl class="methodology">
<dt>判定与分母</dt><dd>PASS / FAIL / INVALID / INCONCLUSIVE 原样取自保存的 assessment，不因报告诊断改判。计划通过率 = PASS / 计划执行数，缺失与 INVALID 不计为通过；有效执行通过率分母为 validity=VALID 的执行数。读写与任务族通过率使用该组已保存执行数，不能混作计划覆盖率。</dd>
<dt>场景分组与覆盖</dt><dd>优先使用冻结任务目标；缺失时回退到观察意图，无法确定则标记目标待确认。多轮中的意图偏移不改变已绑定的任务目标。模块、工具链和端到端分别统计；保护路径通过不能视为成功写入。任务标签按任务去重，评分与问题计数按执行去重；一个执行可涉及多个问题或字段映射。</dd>
<dt>延迟</dt><dd>使用保存的 trial latency_seconds。总体 P50 为中位数，P95 沿用历史排序索引 min(n−1, floor(0.95×n))（零起始）；耗时解释中的分层 P95 使用最近秩法 ceil(0.95×n)−1，两者在部分样本量下可能不同。缺失耗时不作零值；总体包含不同层级，不能当作单次模型延迟。未应用性能验收阈值，不作性能达标判定。</dd>
<dt>Token 与费用</dt><dd>优先读取保存的模型用量；input/prompt、output/completion 是字段别名，不重复累加。缓存与输入的包含关系以“用量与身份”中的来源说明为准，不能直接相加。缺失用量或实际成本不当作零；价格估算与实际扣费分开，价格来源和适用条件见审计区。</dd>
<dt>归因与比较</dt><dd>诊断是证据解释，不是第二套评分或已证实的修复收益。潜在业务风险不能仅由失败计数确定。比较必须固定任务、参考契约与控制项，并核验运行身份兼容性；证据可复核，不保证再次调用模型得到相同输出。</dd>
</dl>
"""
