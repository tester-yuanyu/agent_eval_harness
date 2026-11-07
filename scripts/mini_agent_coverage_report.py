#!/usr/bin/env python3
"""从冻结覆盖清单与保存结果生成离线覆盖报告，不执行模型。"""

import argparse
import html
import json
from collections import Counter
from pathlib import Path


def write_coverage_report(dataset: Path, run_dir: Path) -> Path:
    from eval_framework.benchmark.provider_tasks import provider_dataset_identity

    identity = provider_dataset_identity(dataset)
    run = json.loads((run_dir / "results.json").read_text())
    if run["identity"]["dataset"] != identity:
        raise ValueError("coverage report dataset identity mismatch")
    catalog = json.loads((dataset / "coverage.json").read_text())
    rows = run["trials"]
    by_case = {r["case_id"]: r for r in rows}
    if len(by_case) != len(rows):
        raise ValueError("this representative report requires one trial per case")
    events = [e for r in rows for e in r["observation"].get("events", [])]
    scenarios = {}
    for name, group in catalog["scenarios"].items():
        observed = [by_case[c] for c in group["case_ids"] if c in by_case]
        scenarios[name] = {
            "constructed": len(group["case_ids"]),
            "selected": sum(c in run["planned_case_ids"] for c in group["case_ids"]),
            "executed": len(observed),
            "evidence_complete": sum(
                r["observation"].get("evidence_complete") is True for r in observed
            ),
            "verdicts": dict(Counter(r["assessment"]["verdict"] for r in observed)),
            "case_ids": group["case_ids"],
        }
    raw = [
        e
        for r in rows
        for e in r["observation"].get("adapter_output", {}).get("trace_events", [])
    ]
    actual = {
        "model_generations": sum(e["type"] == "generation" for e in events),
        "tool_calls": sum(e["type"] == "tool" for e in events),
        "tool_timeouts": sum(e["event_type"] == "tool_timeout" for e in raw),
        "tool_failures": sum(e["event_type"] == "tool_failed" for e in raw),
        "confirmation_requests": sum(
            e["event_type"] in {"confirmation_requested", "confirmation_required"}
            for e in raw
        ),
        "confirmations_accepted": sum(
            e["event_type"] == "confirmation_accepted" for e in raw
        ),
        "trials_with_writes": sum(
            (r["observation"].get("adapter_output", {}).get("snapshot") or {}).get(
                "grant_count", 0
            )
            > 0
            for r in rows
        ),
    }
    report = {
        "run_id": run["run_id"],
        "dataset_manifest_sha256": identity["manifest_sha256"],
        "constructed": identity["task_count"],
        "executed": len(rows),
        "verdicts": dict(Counter(r["assessment"]["verdict"] for r in rows)),
        "actual_reached": actual,
        "scenarios": scenarios,
        "unsupported": catalog["unsupported"],
    }
    (run_dir / "coverage-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )

    def esc(value):
        return html.escape(str(value))

    summary = " · ".join(f"{esc(k)} {v}" for k, v in report["verdicts"].items())
    table = "".join(
        f"<tr><td>{esc(name)}</td><td>{v['constructed']}</td><td>{v['selected']}</td><td>{v['executed']}</td><td>{v['evidence_complete']}</td><td>{esc(v['verdicts'])}</td></tr>"
        for name, v in scenarios.items()
    )
    trials = "".join(
        f"<tr><td>{esc(r['case_id'])}</td><td>{esc(r['evaluation_level']) if 'evaluation_level' in r else esc(r.get('category', ''))}</td><td>{esc(r['assessment']['verdict'])}</td><td>{esc(r['observation'].get('evidence_complete'))}</td></tr>"
        for r in rows
    )
    unsupported = "".join(
        f"<li><b>{esc(x['id'])}</b>：{esc(x['reason'])}</li>"
        for x in catalog["unsupported"]
    )
    page = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>mini_agent 场景覆盖验收</title><style>body{{font:16px/1.7 system-ui,sans-serif;background:#f5f7fb;color:#172134;max-width:1180px;margin:40px auto;padding:0 24px}}section{{background:white;padding:24px;border-radius:12px;margin:20px 0}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;padding:9px;border-bottom:1px solid #e5e9f0}}a{{color:#235fce}}code{{overflow-wrap:anywhere}}.notice{{border-left:4px solid #de9b25;padding-left:16px}}</style><h1>mini_agent 场景覆盖与链路验收</h1><p>冻结版本 {esc(identity["version"])} · <code>{esc(run["run_id"])}</code></p><section><h2>{identity["task_count"]} 条已构造 · {len(rows)} 条已执行</h2><p>{summary}</p><p><a href="report.html">打开详细报告：逐项评分、失败原因、完整 Trace</a> · <a href="coverage-results.json">覆盖数据 JSON</a></p><p class="notice">执行覆盖与通过率分别统计；用例已执行不代表其后续工具或写入步骤已经到达。Agent FAIL 可以是框架正确捕获的行为问题。以下多标签统计有交叉，不可相加作为总用例数。</p><p>实际到达证据：{esc(actual)}</p></section><section><h2>场景覆盖矩阵</h2><table><tr><th>场景</th><th>已构造</th><th>代表集</th><th>已执行</th><th>证据完整</th><th>判定</th></tr>{table}</table></section><section><h2>逐项执行记录</h2><table><tr><th>用例</th><th>层级／类别</th><th>判定</th><th>证据完整</th></tr>{trials}</table></section><section><h2>范围与限制</h2><ul>{unsupported}</ul><p>数据来自冻结覆盖清单与本次原始结果。新增用例为合成、尚未人工复核；评分使用确定性规则，不调用 LLM Judge。工具错误为受控 fixture 注入。</p></section></html>"""
    target = run_dir / "coverage.html"
    target.write_text(page)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    print(write_coverage_report(args.dataset, args.run))
