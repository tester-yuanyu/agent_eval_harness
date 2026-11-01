"""根据已保存的分层执行和 Judge 评审记录生成离线作品集。

仅在实验完成后运行；不导入 Agent、不调用模型或网络。
公开产物不复制原始提示词、回复、文件内容、运行配置或凭据。
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, pstdev
from urllib.parse import urlsplit, urlunsplit

POPULATIONS = {
    "program_module": "程序模块 · 直接调用",
    "model_decision": "模型决策模块 · 隔离输入",
    "critical_chain": "关键链路 · 真实 Agent",
    "end_to_end": "端到端 · 文件工具 Agent",
}
VERDICTS = ("PASS", "FAIL", "INVALID", "INCONCLUSIVE")
JUDGE_NAMES = {
    "action_appropriateness",
    "recovery_appropriateness",
    "response_groundedness",
}
DISPLAY_NAMES = {
    "PASS": "通过（PASS）",
    "FAIL": "失败（FAIL）",
    "INVALID": "执行无效（INVALID）",
    "INCONCLUSIVE": "证据不足（INCONCLUSIVE）",
    "SCORED": "已评分",
    "NOT_APPLICABLE": "不适用",
    "ERROR": "评分错误",
    "MISSING": "缺失",
    "UNSCORED": "未评分",
    "VERIFIED": "已验证（VERIFIED）",
    "ACCEPTED": "已接受上传（ACCEPTED）",
    "MISMATCH": "核对不一致（MISMATCH）",
    "not_supplied": "未提供",
    "unknown": "未知",
    "not_exported": "未导出",
    "execution": "原始执行／确定性复评",
    "judge_annotation": "Judge 事后评审",
    "task": "任务",
    "generation": "模型决策",
    "tool": "工具调用",
    "turn": "对话轮次",
    "chain": "关键链路",
    "pilot_executed": "试点已执行",
    "pilot_partial": "试点部分完成",
    "pending_or_unverified": "待执行或待验证",
    **POPULATIONS,
}
METRIC_NAMES = {
    "action_appropriateness": "动作合理性",
    "recovery_appropriateness": "错误恢复合理性",
    "response_groundedness": "回复事实依据",
    "decision_arguments": "决策参数正确性",
    "decision_call_policy": "调用／弃权策略",
    "decision_schema": "决策参数结构",
    "decision_tool_selection": "工具选择",
    "interactive_evidence": "交互证据完整性",
    "task_success": "任务完成",
    "tool_allowed": "工具允许性",
    "tool_correctness": "工具调用正确性",
    "tool_schema": "工具参数结构",
    "workspace_policy": "工作区约束",
}


def _display(value):
    return DISPLAY_NAMES.get(value, value) if isinstance(value, str) else value


def _metric_name(value):
    if value in METRIC_NAMES:
        return f"{METRIC_NAMES[value]}（{value}）"
    return f"检查点（{value}）" if value.startswith("checkpoint:") else value


LIMITATIONS = [
    "程序模块、隔离模型决策、关键链路与端到端分开统计；不把模块通过率当作模型成功率。",
    "任务实例包含同族参数变体；实例数、任务族数与重复执行次数分别报告。",
    "tool_schema 只检查参数结构，不等于参数语义正确；tool_order 只检查顺序，不证明数据流正确。",
    "关键链路使用显式检查点；尚未证明任意工作流每一步都有完整语义评分。",
    "GEval 分数是 0～1 的规则尺度，不是正确概率；缺失、错误与不适用不记为成功。",
    "Judge 重评分复用已有执行证据，不增加 Agent 执行次数；成本与用量单独统计。",
    "事后 Judge 所在 Trace 根 Span 跨度包含执行至评审的间隔，不等于 Agent 耗时；Agent latency 沿用原记录。",
    "独立人工校准与阈值验证尚未完成；Judge 保持诊断用途，不覆盖正式终态判定。",
    "当前主结果仅代表已记录的文件工具任务；不宣称覆盖所有业务领域、插件、MCP 或生产系统。",
]


def _hash(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _read(path: Path):
    path = path / "results.json" if path.is_dir() else path
    raw = path.read_bytes()
    return (
        path,
        json.loads(raw),
        {
            "file": f"{path.parent.name}/{path.name}",
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
    )


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _population(row):
    mode = row.get("execution_mode", "agent")
    if mode == "module":
        return "program_module"
    if mode == "decision":
        return "model_decision"
    if mode != "agent" or row.get("evaluation_level", "e2e") not in ("chain", "e2e"):
        raise ValueError("unknown execution population")
    return "critical_chain" if row.get("evaluation_level") == "chain" else "end_to_end"


def _validate(run, *, judge):
    is_judge = run.get("provenance", {}).get("operation") == "judge_saved_evidence"
    if is_judge != judge:
        raise ValueError("Judge annotation and execution inputs must be separate")
    if run.get("mode") not in (
        "real_agent",
        "real_module",
        "real_model_decision",
        "mixed_real_execution",
    ) or run.get("identity", {}).get("offline"):
        raise ValueError("public results require real saved executions")
    if _hash(run["identity"]) != run["identity_hash"]:
        raise ValueError("source identity hash mismatch")
    planned, repeats = run["planned_case_ids"], run["trials_per_case"]
    if (
        not planned
        or len(planned) != len(set(planned))
        or type(repeats) is not int
        or repeats < 1
    ):
        raise ValueError("invalid planned selection")
    expected = {(case, trial) for case in planned for trial in range(1, repeats + 1)}
    actual = [(row["case_id"], row["trial"]) for row in run["trials"]]
    if len(set(actual)) != len(actual) or set(actual) != expected:
        raise ValueError("complete unique planned execution evidence is required")
    if any(row["assessment"]["verdict"] not in VERDICTS for row in run["trials"]):
        raise ValueError("unsupported saved verdict")
    if "summary" in run:
        counts = dict(Counter(row["assessment"]["verdict"] for row in run["trials"]))
        summary = run["summary"]
        if summary.get("verdicts", counts) != counts or summary.get(
            "completed_trials", len(actual)
        ) != len(actual):
            raise ValueError("saved summary disagrees with execution rows")


def _safe_url(value):
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        return None
    # Query strings may contain authentication tokens; links never publish them.
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _receipt(path, source_hash):
    receipt_path = path.parent / "langfuse_export.json"
    verification_path = path.parent / "langfuse_verification.json"
    if not receipt_path.is_file():
        if verification_path.is_file():
            raise ValueError("Langfuse verification requires its export receipt")
        return (
            {
                "status": "not_supplied",
                "export_status": "not_supplied",
                "verification_status": "not_supplied",
                "counts": {},
            },
            {},
            [],
        )
    _, receipt, identity = _read(receipt_path)
    if receipt.get("source_hash") != source_hash:
        raise ValueError("Langfuse receipt does not match saved results")
    links = {}
    for trace in receipt.get("traces", []):
        link = _safe_url(trace.get("trace_url") or trace.get("url"))
        links[(trace["case_id"], trace["trial"])] = {
            "trace_id": trace.get("trace_id"),
            "url": link,
        }
    sources = [identity]
    result = {
        "status": receipt.get("status", "unknown"),
        "export_status": receipt.get("status", "unknown"),
        "verification_status": "not_supplied",
        "source_hash": source_hash,
        "counts": receipt.get("counts", {}),
    }
    if verification_path.is_file():
        _, verification, verification_source = _read(verification_path)
        if verification.get("source_hash") != source_hash:
            raise ValueError("Langfuse verification does not match saved results")
        result["verification_status"] = verification.get("status", "unknown")
        result["status"] = result["verification_status"]
        sources.append(verification_source)
        supplement = verification.get("supplemental_evidence")
        if supplement is not None:
            if not isinstance(supplement, dict) or not isinstance(
                supplement.get("receipt_path"), str
            ):
                raise ValueError("Langfuse supplemental evidence reference is invalid")
            # Receipt paths may retain an old checkout prefix; bind the sibling
            # file by its exact bytes and source, never by the displayed run ID.
            filename = Path(supplement["receipt_path"]).name
            supplemental_path = path.parent / filename
            if not filename or not supplemental_path.is_file():
                raise ValueError("Langfuse supplemental receipt is missing")
            _, saved, supplemental_source = _read(supplemental_path)
            if (
                supplement.get("source_hash") != source_hash
                or saved.get("source_hash") != source_hash
                or supplement.get("receipt_sha256") != supplemental_source["sha256"]
                or supplement.get("status") != "VERIFIED"
                or saved.get("status") != "VERIFIED"
            ):
                raise ValueError(
                    "Langfuse supplemental receipt is not source-bound and VERIFIED"
                )
            result["supplemental_evidence"] = {
                "status": "VERIFIED",
                "source_hash": source_hash,
                "file": supplemental_source["file"],
                "receipt_sha256": supplemental_source["sha256"],
                "observations": supplement.get("observations"),
            }
            sources.append(supplemental_source)
    return result, links, sources


def _metric(metric):
    result = {
        key: metric.get(key)
        for key in (
            "name",
            "scope",
            "event_id",
            "metric_id",
            "version",
            "score",
            "formal",
            "status",
            "judge_repeat",
            "backend",
            "calibration",
            "rubric_sha256",
            "evidence_ids",
        )
        if key in metric
    }
    result.setdefault("scope", "task")
    result.setdefault(
        "status", "SCORED" if metric.get("score") is not None else "MISSING"
    )
    if result.get("score") is not None and not _number(result["score"]):
        raise ValueError("metric score is not finite")
    return result


def _usage(calls):
    result = {"records": len(calls)}
    for key in ("input_tokens", "output_tokens", "cost_usd"):
        alias = {
            "input_tokens": "prompt_tokens",
            "output_tokens": "completion_tokens",
        }.get(key, key)
        values = [record.get(key, record.get(alias)) for record in calls]
        known = [value for value in values if _number(value)]
        result[key] = sum(known) if known and len(known) == len(values) else None
        result[key + "_known_subtotal"] = sum(known) if known else None
        result[key + "_known_records"] = len(known)
    return result


def _group(rows):
    cases = defaultdict(list)
    for row in rows:
        cases[(row["run_id"], row["case_id"])].append(row)
    repeated = [group for group in cases.values() if group[0]["planned_repeats"] > 1]
    all_pass = sum(all(row["verdict"] == "PASS" for row in group) for group in repeated)
    counts = Counter(row["verdict"] for row in rows)
    return {
        "instances": len({(row["dataset_id"], row["case_id"]) for row in rows}),
        "families": len({(row["dataset_id"], row["family"]) for row in rows}),
        "task_experiments": len(cases),
        "trials": len(rows),
        "verdicts": {name: counts[name] for name in VERDICTS},
        "pass_rate": counts["PASS"] / len(rows) if rows else None,
        "repeated_task_experiments": len(repeated),
        "all_repeats_pass_tasks": all_pass if repeated else None,
        "all_repeats_pass_rate": all_pass / len(repeated) if repeated else None,
    }


def _scope_metrics(rows):
    grouped = defaultdict(list)
    for row in rows:
        for metric in row["metrics"]:
            grouped[(metric["scope"], metric["name"], metric.get("version"))].append(
                metric
            )
    result = []
    for (scope, name, version), metrics in sorted(
        grouped.items(), key=lambda item: str(item[0])
    ):
        scores = [
            metric["score"]
            for metric in metrics
            if metric["status"] == "SCORED" and metric.get("score") is not None
        ]
        statuses = Counter(metric["status"] for metric in metrics)
        result.append(
            {
                "scope": scope,
                "name": name,
                "version": version,
                "count": len(metrics),
                "scored": len(scores),
                "statuses": dict(statuses),
                "mean": mean(scores) if scores else None,
            }
        )
    return result


def _judge_summary(rows, calls, repeat_counts):
    metrics = [metric for row in rows for metric in row["metrics"]]
    statuses = Counter(metric["status"] for metric in metrics)
    applicable = len(metrics) - statuses["NOT_APPLICABLE"]
    scores = [
        metric["score"]
        for metric in metrics
        if metric["status"] == "SCORED" and metric.get("score") is not None
    ]
    groups = defaultdict(list)
    for row in rows:
        for metric in row["metrics"]:
            if metric["status"] == "SCORED":
                key = (
                    row["run_id"],
                    row["case_id"],
                    row["trial"],
                    metric.get("metric_id") or (metric["name"], metric.get("event_id")),
                )
                groups[key].append((metric.get("judge_repeat", 1), metric["score"]))
    stability = []
    for key, repeated in groups.items():
        if len({repeat for repeat, _ in repeated}) != len(repeated):
            raise ValueError("duplicate Judge repetition identity")
        if len(repeated) > 1:
            values = [score for _, score in repeated]
            stability.append(
                {
                    "run_id": key[0],
                    "case_id": key[1],
                    "trial": key[2],
                    "metric_id": str(key[3]),
                    "repetitions": len(values),
                    "mean": mean(values),
                    "range": max(values) - min(values),
                    "stddev": pstdev(values),
                    "complete_repetitions": len(values) == repeat_counts[key[0]],
                }
            )
    by_run = []
    for run_id in sorted({row["run_id"] for row in rows}):
        members = [
            metric
            for row in rows
            if row["run_id"] == run_id
            for metric in row["metrics"]
        ]
        counts = Counter(metric["status"] for metric in members)
        by_run.append(
            {
                "run_id": run_id,
                "configured_repeats": repeat_counts[run_id],
                "applicable": len(members) - counts["NOT_APPLICABLE"],
                "scored": counts["SCORED"],
                "errors": counts["ERROR"],
                "missing": counts["MISSING"],
                "not_applicable": counts["NOT_APPLICABLE"],
            }
        )
    return {
        "annotation_trials": len(rows),
        "by_run": by_run,
        "new_agent_executions": 0,
        "total": len(metrics),
        "applicable": applicable,
        "scored": len(scores),
        "not_applicable": statuses["NOT_APPLICABLE"],
        "missing": statuses["MISSING"],
        "errors": statuses["ERROR"],
        "coverage": len(scores) / applicable if applicable else None,
        "by_scope_and_metric": _scope_metrics(rows),
        "stability": {
            "matched_metrics": len(stability),
            "mean_range": mean(item["range"] for item in stability)
            if stability
            else None,
            "max_range": max((item["range"] for item in stability), default=None),
            "items": stability,
        },
        "usage": _usage(calls),
        "human_calibration": "pending_independent_labels",
        "threshold_validation": "pending_independent_holdout",
        "formal": False,
    }


def _tau_langfuse(path, summary_hash):
    """Join official reward evidence to the normalized run and hosted receipt."""
    unavailable = {"status": "not_supplied", "verification_status": "not_supplied"}
    if path.parent.name != "official":
        return unavailable, []
    root = path.parent.parent
    results_path = root / "results.json"
    verification_path = root / "langfuse_verification.json"
    receipt_path = root / "langfuse_export.json"
    if not results_path.is_file():
        if receipt_path.is_file() or verification_path.is_file():
            raise ValueError("τ Langfuse receipt requires its saved results source")
        return unavailable, []
    _, result, result_source = _read(results_path)
    if (
        result.get("mode") != "real_agent_official_tau"
        or result.get("identity", {}).get("official_summary_sha256") != summary_hash
    ):
        raise ValueError("τ normalized results do not match the official summary")
    source_hash = result_source["sha256"]
    receipt, links, receipt_sources = _receipt(results_path, source_hash)
    sources = [result_source, *receipt_sources]
    receipt.update(
        source_hash=source_hash,
        official_summary_sha256=summary_hash,
        traces=[
            {"case_id": case, "trial": trial, **link}
            for (case, trial), link in links.items()
        ],
    )
    return receipt, sources


def _tau(path):
    if path is None:
        return {
            "status": "not_supplied",
            "official_leaderboard_result": False,
            "remaining": "τ 系列领域任务未提供可验证运行结果。",
            "langfuse": {"status": "not_supplied"},
        }, []
    path = Path(path)
    if path.is_dir():
        path = path / "summary.json"
    _, data, source = _read(path)
    langfuse, hosted_sources = _tau_langfuse(path, source["sha256"])
    trials = data.get("results", data.get("trials", []))
    if not isinstance(trials, list):
        trials = []
    rewards = [
        row.get("official_reward", row.get("reward"))
        for row in trials
        if isinstance(row, dict)
        and _number(row.get("official_reward", row.get("reward")))
    ]
    repeat_count = data.get("num_trials")
    task_ids = data.get("task_ids", [])
    planned = (
        len(task_ids) * repeat_count
        if isinstance(task_ids, list) and type(repeat_count) is int and repeat_count > 0
        else None
    )
    completed = (
        data.get("status") == "COMPLETED"
        and bool(rewards)
        and len(rewards) == len(trials) == planned
    )
    status = (
        "pilot_executed"
        if completed
        else "pilot_partial"
        if rewards
        else "pending_or_unverified"
    )
    pinned = data.get("source_identity", {})
    return {
        "status": status,
        "attempted_trials": len(trials),
        "planned_trials": planned,
        "valid_reward_trials": len(rewards),
        "missing_or_invalid_rewards": len(trials) - len(rewards),
        "mean_official_reward": mean(rewards) if rewards else None,
        "source": {
            "repository": _safe_url(pinned.get("repository")),
            "commit": pinned.get("commit"),
        },
        "official_leaderboard_result": False,
        "langfuse": langfuse,
        "remaining": "领域试点不等于完整官方基准或排行榜成绩；仍需扩大覆盖并固定官方运行条件。"
        if rewards
        else "缺少完整任务奖励证据，暂不认定 τ 集成已完成。",
    }, [source, *hosted_sources]


def _questions(summary):
    pops, judge, tau = summary["populations"], summary["judge"], summary["tau"]
    scopes = {metric["scope"] for metric in summary["execution_metrics"]}
    layered = all(pops.get(name, {}).get("trials", 0) for name in POPULATIONS)
    return [
        {
            "id": 1,
            "question": "模块、关键链路、端到端覆盖",
            "status": "已执行三层" if layered else "部分覆盖",
            "evidence": "；".join(
                f"{POPULATIONS[key]}：{value['instances']} 实例 / {value['trials']} 次执行"
                for key, value in pops.items()
            ),
            "remaining": "限定已声明任务族；业务域、复杂动态交互与更多模块仍需扩展。",
        },
        {
            "id": 2,
            "question": "GEval 是否为 LLM Judge",
            "status": "已运行" if judge["scored"] else "尚无已评分证据",
            "evidence": f"GEval 使用评审模型；本报告 {judge['scored']} 条有效诊断分。",
            "remaining": "评分不是概率，不替代确定性终态与硬约束。",
        },
        {
            "id": 3,
            "question": "Inspect 是否支持逐步评分",
            "status": "已接入" if scopes - {"task"} else "待接入",
            "evidence": "Inspect 组织执行，自研采证/检查点通过 DeepEval 评分；已记录范围："
            + "、".join(_display(scope) for scope in sorted(scopes)),
            "remaining": "并非所有步骤均有完整语义判分；顺序检查不证明数据流正确。",
        },
        {
            "id": 4,
            "question": "是否接入 τ-bench",
            "status": _display(tau["status"]),
            "evidence": (
                f"已记录奖励 {tau.get('valid_reward_trials', 0)} / "
                f"计划 {tau.get('planned_trials', '未提供')} 次执行；"
                f"有效奖励均值 {tau.get('mean_official_reward', '未提供')}。"
                f"Langfuse {_display(tau['langfuse']['status'])}；"
                + (
                    "展示状态绑定官方摘要与标准化结果的来源 Hash。"
                    if tau["langfuse"].get("source_hash")
                    else "未提供可校验的展示记录。"
                )
                + "不是官方排行榜成绩。"
            ),
            "remaining": tau["remaining"],
        },
        {
            "id": 5,
            "question": "框架分为哪些部分",
            "status": "职责明确",
            "evidence": "专用任务生成/冻结 → Inspect → 自研环境与适配/Oracle/轨迹检查点 → DeepEval/GEval → 报告与 Langfuse。",
            "remaining": "原通用 dataset-builder、能力协议与旧兼容代码仍为保留能力；并非此次主链路每步都调用。",
        },
        {
            "id": 6,
            "question": "Trace 轨迹打分",
            "status": "有节点级分数" if scopes - {"task"} else "未证明",
            "evidence": f"执行指标 {sum(item['count'] for item in summary['execution_metrics'])} 条；Judge 指标 {judge['total']} 条，节点 ID 随摘要保存。",
            "remaining": "Langfuse 上传与读回状态逐运行列出；缺证据节点不能补造分数。",
        },
        {
            "id": 7,
            "question": "LLM Judge 与指标量化",
            "status": "已量化、未人工校准" if judge["scored"] else "待真实评分",
            "evidence": f"适用 {judge['applicable']} 条、已评分 {judge['scored']} 条、错误 {judge['errors']} 条、缺失 {judge['missing']} 条；另有重复波动和用量。",
            "remaining": "独立人工标签、一致性验收、误放/误杀评估及阈值留出验证仍未完成。",
        },
    ]


def _escape(value):
    return html.escape("未提供" if value is None else str(value), quote=True)


def _percent(value):
    return "—" if value is None else f"{value * 100:.2f}%"


def _table(headers, rows):
    return (
        '<div class="table"><table><thead><tr>'
        + "".join(f"<th>{_escape(header)}</th>" for header in headers)
        + "</tr></thead><tbody>"
        + "".join(
            "<tr>" + "".join(f"<td>{_escape(cell)}</td>" for cell in row) + "</tr>"
            for row in rows
        )
        + "</tbody></table></div>"
    )


STYLE = """
:root{--ink:#172a3b;--muted:#637587;--line:#dce5ed;--paper:#f1f5f8;--accent:#16686c}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.65 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}header,main{max-width:1240px;margin:auto;padding:30px}header{padding-bottom:10px}h1{font-size:34px;line-height:1.25;margin:8px 0}h2{font-size:22px;margin:26px 0 12px}.eyebrow{letter-spacing:.14em;color:var(--accent);font-size:12px;font-weight:700}.lead{max-width:900px;color:var(--muted)}section,.card{background:white;border:1px solid var(--line);border-radius:14px;padding:22px;margin-bottom:18px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card strong{font-size:30px;display:block}.card span,.muted{color:var(--muted)}.table{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:11px;text-align:left;vertical-align:top}th{background:#f4f7fa;white-space:nowrap}a{color:var(--accent)}code{font-size:12px;overflow-wrap:anywhere}details{margin:14px 0}summary{cursor:pointer;font-weight:600}.badge{display:inline-block;color:var(--accent);background:#e1f1ef;border-radius:20px;padding:3px 12px;font-size:12px}li{margin:6px 0}@media(max-width:760px){header,main{padding:18px}.cards{grid-template-columns:repeat(2,1fr)}h1{font-size:28px}section{padding:15px}}@media print{body{background:white}section{break-inside:avoid}header,main{padding:12px}.table{overflow:visible}}
"""


def _html(summary, rows):
    populations = [
        [
            POPULATIONS[key],
            value["instances"],
            value["families"],
            value["trials"],
            *[value["verdicts"][verdict] for verdict in VERDICTS],
            _percent(value["pass_rate"]),
            _percent(value["all_repeats_pass_rate"]),
        ]
        for key, value in summary["populations"].items()
    ]
    cards = "".join(
        f'<div class="card"><span>{_escape(label)}</span><strong>{_escape(value)}</strong></div>'
        for label, value in [
            ("任务实例", summary["executions"]["instances"]),
            ("真实执行次数（分层）", summary["executions"]["trials"]),
            ("Judge 有效分数（含重复评审）", summary["judge"]["scored"]),
            ("Judge 适用项覆盖率", _percent(summary["judge"]["coverage"])),
        ]
    )
    metrics = summary["execution_metrics"] + summary["judge"]["by_scope_and_metric"]
    metric_table = [
        [
            _display(item["scope"]),
            _metric_name(item["name"]),
            item["version"],
            item["count"],
            item["scored"],
            "—" if item["mean"] is None else f"{item['mean']:.3f}",
            "、".join(
                f"{_display(key)}：{value}" for key, value in item["statuses"].items()
            ),
        ]
        for item in metrics
    ]
    questions = [
        [
            item["id"],
            item["question"],
            item["status"],
            item["evidence"],
            item["remaining"],
        ]
        for item in summary["questions"]
    ]
    run_links = "".join(
        f"<li>{_escape(run['run_id'])}：{_escape(_display(run['kind']))} · Langfuse {_escape(_display(run['langfuse']['status']))}"
        + (
            f' · <a href="{_escape(run["local_report"])}">本地完整报告</a>'
            if run.get("local_report")
            else ""
        )
        + "</li>"
        for run in summary["runs"]
    )
    trace_rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{_escape(_display(row.get(key, '')))}</td>"
            for key in ("kind", "run_id", "case_id", "trial", "population", "verdict")
        )
        + "<td>"
        + (
            f'<a href="{_escape(row["trace_link"])}">Trace</a>'
            if row.get("trace_link")
            else _escape(row.get("trace_id") or "未提供")
        )
        + "</td></tr>"
        for row in rows
    )
    judge = summary["judge"]
    calibration_link = (
        '<p><a href="calibration-sample.json">下载独立人工标注起点</a>：'
        "标注材料不代表已经完成人工校准。</p>"
        if summary.get("calibration_starter")
        else ""
    )
    screenshot = (
        "<section><h2>Langfuse 节点评分示例</h2><p>已保存的界面抽查展示模型决策节点上的结构、参数、工具选择与 GEval 分数，以及对应 Judge 子节点。界面抽查与服务端回读分别说明各自覆盖范围；服务端状态以各运行的来源绑定记录为准。</p>"
        '<figure style="margin:0"><a href="langfuse-step-scores.png"><img src="langfuse-step-scores.png" alt="Langfuse 模型决策节点分数与 Judge 子节点示例" style="display:block;width:100%;height:auto" loading="lazy"></a>'
        '<figcaption class="muted">原始截图；点击查看完整图片。</figcaption></figure></section>'
        if summary.get("langfuse_screenshot")
        else ""
    )
    judge_runs = _table(
        ["Judge 运行", "每份证据评审次数", "适用", "已评分", "错误", "缺失", "不适用"],
        [
            [
                item["run_id"],
                item["configured_repeats"],
                item["applicable"],
                item["scored"],
                item["errors"],
                item["missing"],
                item["not_applicable"],
            ]
            for item in judge["by_run"]
        ],
    )
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent Eval Suite · 三层评测作品集</title><style>'
        + STYLE
        + '</style></head><body><header><div class="eyebrow">Agent Eval Suite / 评测证据作品集</div><h1>工具型 Agent 三层评测</h1><span class="badge">Inspect · DeepEval / GEval · Langfuse</span><p><a href="../../docs/dataset-reading.html">数据集中文逐条阅读</a> · <a href="../../docs/dataset-language.md">语言与冻结规则</a></p><p class="lead">从模块边界、关键链路到端到端交付。此页只展示已保存的真实运行证据；Judge 重评分单独统计。文件工具任务的结果不外推为通用 Agent 能力。</p></header><main><div class="cards">'
        + cards
        + '</div><section><h2>三层覆盖，四类执行方式</h2><p class="muted">程序模块与模型决策模块分开；重复全通过率仅统计计划重复 ≥ 2 次的任务实验。</p>'
        + _table(
            [
                "范围",
                "实例",
                "任务族",
                "执行次数",
                *[_display(verdict) for verdict in VERDICTS],
                "本组通过率",
                "重复全通过率",
            ],
            populations,
        )
        + "</section><section><h2>七个问题：完成证据与未解决部分</h2>"
        + _table(["#", "问题", "当前状态", "实际证据", "尚未解决 / 边界"], questions)
        + "</section><section><h2>轨迹与评分指标</h2><p>tool_schema 是结构检查，tool_order 是顺序检查；不能据此宣称参数语义与数据流全部正确。</p>"
        + _table(
            ["评分范围", "指标", "版本", "记录数", "已评分", "均分", "状态计数"],
            metric_table,
        )
        + "</section><section><h2>Judge 的量化与限制</h2><p>适用 "
        + str(judge["applicable"])
        + " 条，已评分 "
        + str(judge["scored"])
        + " 条；不适用 "
        + str(judge["not_applicable"])
        + " 条，错误 "
        + str(judge["errors"])
        + " 条，缺失 "
        + str(judge["missing"])
        + " 条。上述合计含主评审与重复评审；逐运行分母如下。没有独立人工标签时不报告人工一致率。</p>"
        + judge_runs
        + calibration_link
        + _table(
            [
                "重复匹配指标",
                "平均极差",
                "最大极差",
                "Judge 请求",
                "输入 Token",
                "输出 Token",
                "费用 USD",
            ],
            [
                [
                    judge["stability"]["matched_metrics"],
                    judge["stability"]["mean_range"],
                    judge["stability"]["max_range"],
                    judge["usage"]["records"],
                    judge["usage"]["input_tokens"],
                    judge["usage"]["output_tokens"],
                    judge["usage"]["cost_usd"],
                ]
            ],
        )
        + '<p class="muted">空值表示未知；费用未知不按 0 计算。分数是规则尺度，不是概率。人工校准与阈值留出验证待完成。</p></section><section><h2>架构与作品集边界</h2><p>任务生成与冻结 → Inspect 调度 → 自研隔离环境、适配器、Oracle 和检查点 → DeepEval / GEval → 报告与 Langfuse。</p><ul>'
        + "".join("<li>" + _escape(item) + "</li>" for item in LIMITATIONS)
        + "</ul></section>"
        + screenshot
        + "<section><h2>运行与原始证据入口</h2><ul>"
        + run_links
        + '</ul><p>本页表格离线可读；本地完整报告链接依赖仓库目录。<a href="summary.json">汇总 JSON</a> · <a href="results.jsonl">公开逐次执行摘要</a></p><details><summary>所有执行与事后评审摘要</summary><div class="table"><table><thead><tr><th>类型</th><th>运行</th><th>用例</th><th>执行序号</th><th>范围</th><th>判定</th><th>Trace</th></tr></thead><tbody>'
        + trace_rows
        + "</tbody></table></div></details><details><summary>来源文件校验值</summary>"
        + _table(
            ["文件", "SHA256"],
            [[source["file"], source["sha256"]] for source in summary["sources"]],
        )
        + "</details></section></main></body></html>"
    )


def build_report(
    runs: list[Path],
    judge_runs: list[Path],
    output: Path,
    *,
    tau_run: Path | None = None,
):
    if not runs:
        raise ValueError("at least one real execution run is required")
    output = Path(output).resolve()
    public, sources, run_infos, usages, judge_calls = [], [], [], [], []
    seen_paths, seen_runs, repeat_counts = set(), set(), {}
    execution_origins = set()
    for kind, paths in (("execution", runs), ("judge_annotation", judge_runs)):
        for raw_path in paths:
            path = Path(raw_path).resolve()
            path = path / "results.json" if path.is_dir() else path
            if path in seen_paths:
                raise ValueError("duplicate source input")
            seen_paths.add(path)
            path, run, source = _read(path)
            _validate(run, judge=kind == "judge_annotation")
            if run["run_id"] in seen_runs:
                raise ValueError("duplicate run identity")
            seen_runs.add(run["run_id"])
            if kind == "execution":
                origin = (
                    run.get("execution_run_id")
                    or run.get("regrade", {}).get("source_run_id")
                    or run["run_id"]
                )
                if origin in execution_origins:
                    raise ValueError(
                        "duplicate execution origin: select one grading version per run"
                    )
                execution_origins.add(origin)
            sources.append(source)
            receipt, links, receipt_sources = _receipt(path, source["sha256"])
            sources.extend(receipt_sources)
            info = {
                "run_id": run["run_id"],
                "kind": kind,
                "source_sha256": source["sha256"],
                "langfuse": receipt,
            }
            local_report = path.parent / "report.html"
            if local_report.is_file():
                info["local_report"] = os.path.relpath(local_report, output)
            run_infos.append(info)
            repeat_counts[run["run_id"]] = run.get("provenance", {}).get(
                "judge_repeats", 1
            )
            for row in run["trials"]:
                metrics = [
                    metric
                    for metric in row["assessment"]["metrics"]
                    if kind == "execution" or "judge_repeat" in metric
                ]
                link = links.get((row["case_id"], row["trial"]), {})
                public.append(
                    {
                        "kind": kind,
                        "run_id": run["run_id"],
                        "source_sha256": source["sha256"],
                        "dataset_id": run["identity"]["dataset"].get(
                            "dataset_id", "unknown"
                        ),
                        "case_id": row["case_id"],
                        "family": row["family"],
                        "trial": row["trial"],
                        "planned_repeats": run["trials_per_case"],
                        "population": _population(row),
                        "evaluation_level": row.get("evaluation_level", "e2e"),
                        "execution_mode": row.get("execution_mode", "agent"),
                        "split": row.get("split"),
                        "verdict": row["assessment"]["verdict"],
                        "validity": row["assessment"].get("validity"),
                        "metrics": [_metric(metric) for metric in metrics],
                        "trace_id": link.get("trace_id"),
                        "trace_link": link.get("url"),
                    }
                )
                if kind == "execution":
                    usages.append(row.get("observation", {}).get("usage", {}))
                else:
                    judge_calls.extend(
                        call.get("usage", {})
                        for metric in metrics
                        for call in metric.get("events", [])
                    )
    executions = [row for row in public if row["kind"] == "execution"]
    annotations = [row for row in public if row["kind"] == "judge_annotation"]
    populations = {}
    for key in POPULATIONS:
        rows = [row for row in executions if row["population"] == key]
        if rows:
            populations[key] = _group(rows)
            populations[key]["model_success_rate"] = (
                None if key == "program_module" else populations[key]["pass_rate"]
            )
    tau, tau_sources = _tau(tau_run)
    sources.extend(tau_sources)
    totals = _group(executions)
    totals.pop("pass_rate")  # No misleading blended module/model success metric.
    totals.pop("all_repeats_pass_rate")
    summary = {
        "version": "layered-portfolio-v1",
        "sources": sources,
        "runs": run_infos,
        "executions": totals,
        "populations": populations,
        "execution_metrics": _scope_metrics(executions),
        "agent_and_module_usage": _usage(usages),
        "judge": _judge_summary(annotations, judge_calls, repeat_counts),
        "tau": tau,
        "limitations": LIMITATIONS,
    }
    starter = output / "calibration-sample.json"
    if starter.is_file():
        starter_hash = hashlib.sha256(starter.read_bytes()).hexdigest()
        summary["calibration_starter"] = {"file": starter.name, "sha256": starter_hash}
        sources.append(
            {"file": f"{output.name}/{starter.name}", "sha256": starter_hash}
        )
    screenshot = output / "langfuse-step-scores.png"
    if screenshot.is_file():
        screenshot_hash = hashlib.sha256(screenshot.read_bytes()).hexdigest()
        summary["langfuse_screenshot"] = {
            "file": screenshot.name,
            "sha256": screenshot_hash,
            "scope": "single_ui_example",
        }
        sources.append(
            {"file": f"{output.name}/{screenshot.name}", "sha256": screenshot_hash}
        )
    summary["questions"] = _questions(summary)
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in public),
        encoding="utf-8",
    )
    (output / "index.html").write_text(_html(summary, public), encoding="utf-8")
    markdown = [
        "# 工具型 Agent 三层评测作品集",
        "",
        "[打开离线报告](index.html) · [汇总数据](summary.json) · [逐次执行摘要](results.jsonl)",
        "",
        f"真实执行：{totals['instances']} 个任务实例、{totals['families']} 个任务族、{totals['trials']} 次执行。Judge 重评分另计，不构成新 Agent 执行。",
        "",
        "| 范围 | 实例 | 任务族 | 执行次数 | 通过（PASS） | 失败（FAIL） | 执行无效（INVALID） | 证据不足（INCONCLUSIVE） |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, value in populations.items():
        markdown.append(
            "| "
            + " | ".join(
                str(item)
                for item in [
                    POPULATIONS[key],
                    value["instances"],
                    value["families"],
                    value["trials"],
                    *[value["verdicts"][verdict] for verdict in VERDICTS],
                ]
            )
            + " |"
        )
    if summary.get("calibration_starter"):
        markdown += [
            "",
            "[独立人工标注起点](calibration-sample.json)：材料准备不代表人工校准完成。",
        ]
    if summary.get("langfuse_screenshot"):
        markdown += [
            "",
            "![Langfuse 节点评分与 Judge 子节点示例](langfuse-step-scores.png)",
            "",
            "界面抽查与服务端回读分别说明各自覆盖范围；服务端状态以各运行的来源绑定记录为准。",
        ]
    markdown += ["", "## 七个问题与未解决部分", ""]
    for question in summary["questions"]:
        markdown += [
            f"{question['id']}. **{question['question']}：{question['status']}**。{question['evidence']} 尚未解决 / 边界：{question['remaining']}",
            "",
        ]
    markdown += [
        "## 口径",
        "",
        *["- " + item for item in LIMITATIONS],
        "",
        "来源文件 SHA256 见 summary.json；公开摘要不含模型提示词、工具结果、文件内容或运行凭据。",
    ]
    (output / "README.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", type=Path, required=True)
    parser.add_argument("--judge-runs", nargs="*", type=Path, default=[])
    parser.add_argument("--output", type=Path, default=Path("reports/file-tools-v2"))
    parser.add_argument("--tau-run", type=Path)
    args = parser.parse_args()
    result = build_report(args.runs, args.judge_runs, args.output, tau_run=args.tau_run)
    print(
        json.dumps(
            {
                "execution_trials": result["executions"]["trials"],
                "judge_scored": result["judge"]["scored"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
