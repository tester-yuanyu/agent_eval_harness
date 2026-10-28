"""Human-readable and machine-readable evaluation reporting."""

from __future__ import annotations

import json
import platform
from collections import Counter
from pathlib import Path
from typing import Any

from .capabilities import CapabilityBundle, CapabilityRegistry
from .dataset_loader import load_dataset
from .provider import EvaluationPreflightError
from .runner import CORE_BEHAVIOR_POLICY_VERSION
from .schemas import (
    CaseResult,
    EvaluationRunResult,
    InvalidRunPaths,
    InvalidRunRecord,
    ReportPaths,
)

ASSERTION_LABELS = {
    "output_schema_valid": "输出结构不符合协议",
    "intent_envelope_schema_valid": "意图输出结构不符合协议",
    "intent_parameters_schema_valid": "意图参数不符合协议",
    "intent_match": "意图不匹配",
    "status_match": "决策状态不匹配",
    "next_action_match": "下一步动作不匹配",
    "params_match": "参数不匹配",
    "missing_params_match": "缺失参数判断不匹配",
    "tool_called": "必要工具未调用",
    "tool_not_called": "调用了禁止工具",
    "tool_call_count": "工具调用次数不匹配",
    "tool_args_match": "工具参数不匹配",
    "tool_result_consistent": "工具结果不一致",
    "no_state_change": "只读任务产生了状态变化",
    "final_state_match": "系统终态不匹配",
    "no_duplicate_side_effect": "出现重复副作用",
    "confirmation_requested": "未正确请求确认",
    "confirmation_accepted": "未正确处理确认",
    "no_write_before_confirmation": "确认前发生写入",
    "response_consistent": "最终回复与执行结果不一致",
}

INVESTIGATION_AREAS = {
    "parameters": "参数解析与类型规范化",
    "decision": "意图决策与澄清策略",
    "tool": "工具选择与调用链路",
    "state": "状态写入与终态校验",
    "safety": "确认与安全策略",
    "response": "最终回复生成",
    "output": "结构化输出协议",
    "protocol": "评测集与 Agent 协议命名",
    "other": "相关断言实现",
}

SCENARIO_TYPE_LABELS = {
    "normal": "正常指令",
    "valid_boundary": "合法边界",
    "invalid_parameter": "非法参数",
    "missing_parameter": "缺少参数",
    "ambiguous_expression": "表达歧义",
    "multi_condition": "多条件指令",
    "expression_variant": "表达变体",
    "correction_conflict": "更正／参数冲突",
    "unsupported_batch": "不支持批量",
}

EXECUTION_TYPE_LABELS = {
    "full": "完整评测",
    "targeted_smoke": "定向冒烟",
    "filtered_subset": "筛选子集",
    "auto": "自动判断",
}


def write_report(
    result: EvaluationRunResult,
    output_dir: str | Path,
    capabilities: CapabilityRegistry | None = None,
) -> ReportPaths:
    if capabilities is None:
        capabilities = _resolve_capabilities(result)
    root = Path(output_dir).resolve() / result.evaluator_run_id
    cases_dir = root / "cases"
    evidence_dir = root / "evidence"
    cases_dir.mkdir(parents=True, exist_ok=False)
    evidence_dir.mkdir(exist_ok=True)
    if result.run_directory is not None:
        import shutil

        source = Path(result.run_directory).resolve()
        if source != root:
            shutil.copytree(source / "evidence", evidence_dir, dirs_exist_ok=True)
            shutil.copy2(source / "execution.json", root / "execution.json")
            for relative in result.native_artifacts.values():
                artifact = Path(relative)
                origin = (source / artifact).resolve()
                if artifact.is_absolute() or not origin.is_relative_to(source):
                    raise ValueError(
                        "native artifact must stay within the run directory"
                    )
                destination = root / artifact
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, destination)
        result = result.model_copy(update={"run_directory": str(root)})
    results_path = root / "results.json"
    results_jsonl_path = root / "results.jsonl"
    manifest_path = root / "run_manifest.json"
    report_path = root / "report.md"
    summary_json_path = root / "summary.json"
    failures_path = root / "failures.json"

    results_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    results_jsonl_path.write_text(
        "".join(
            json.dumps(case.model_dump(mode="json"), ensure_ascii=False) + "\n"
            for case in result.cases
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(_manifest(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    case_files = []
    evidence_files = [
        str(path) for path in sorted(evidence_dir.glob("*/*.json*")) if path.is_file()
    ]
    for case in result.cases:
        case_dir = cases_dir / case.case_id
        case_dir.mkdir(exist_ok=True)
        path = case_dir / f"{case.trial_id}.json"
        path.write_text(case.model_dump_json(indent=2), encoding="utf-8")
        case_files.append(str(path))
        case_evidence = evidence_dir / case.case_id / case.trial_id
        case_evidence.mkdir(parents=True)
        actual_path = case_evidence / "actual.json"
        actual_path.write_text(
            json.dumps(
                {
                    "module_output": case.module_output,
                    "turn_results": case.turn_results,
                    "tool_calls": case.tool_calls,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        evidence_files.append(str(actual_path))
        assertions_path = case_evidence / "assertions.json"
        assertions_path.write_text(
            json.dumps(
                [item.model_dump(mode="json") for item in case.assertion_results],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        evidence_files.append(str(assertions_path))
        if case.trace_events and case.trace_id is None:
            trace_path = case_evidence / "trace.jsonl"
            trace_path.write_text(
                "".join(
                    json.dumps(item, ensure_ascii=False) + "\n"
                    for item in case.trace_events
                ),
                encoding="utf-8",
            )
            evidence_files.append(str(trace_path))
        if case.judge_result is not None:
            judge_dir = root / "judge" / case.case_id
            judge_dir.mkdir(parents=True, exist_ok=True)
            judge_path = judge_dir / f"{case.trial_id}.json"
            judge_path.write_text(
                case.judge_result.model_dump_json(indent=2), encoding="utf-8"
            )
            evidence_files.append(str(judge_path))
        if case.diagnostic_metrics:
            diagnostic_path = (
                root / "diagnostics" / case.case_id / f"{case.trial_id}.json"
            )
            diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
            diagnostic_path.write_text(json.dumps({
                name: metric.model_dump(mode="json")
                for name, metric in case.diagnostic_metrics.items()
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            evidence_files.append(str(diagnostic_path))
        if case.trace_analysis is not None:
            analysis_dir = root / "trace_analysis" / case.case_id
            analysis_dir.mkdir(parents=True, exist_ok=True)
            analysis_path = analysis_dir / f"{case.trial_id}.json"
            analysis_path.write_text(
                case.trace_analysis.model_dump_json(indent=2), encoding="utf-8"
            )
            evidence_files.append(str(analysis_path))
        if case.exception and case.exception.get("diagnostic"):
            model_error_path = case_evidence / "model_error.json"
            model_error_path.write_text(
                json.dumps(case.exception, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            evidence_files.append(str(model_error_path))
        if case.system_snapshot is not None:
            state_path = case_evidence / "state.json"
            state_path.write_text(
                json.dumps(case.system_snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            evidence_files.append(str(state_path))

    if result.stability is not None:
        stability_path = root / "stability.json"
        stability_path.write_text(
            result.stability.model_dump_json(indent=2), encoding="utf-8"
        )
        evidence_files.append(str(stability_path))

    summary_json_path.write_text(
        json.dumps(_summary_payload(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    failures_path.write_text(
        json.dumps(_failures_payload(result), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    evidence_summary = [
        "",
        "## 独立证据采集",
        "",
        "| Case / Trial | Trace | 采集状态 | 评测有效性 | 问题 |",
        "|---|---|---|---|---|",
    ]
    for case in result.cases:
        trace = (
            f"[{case.trace_id}](evidence/{case.trace_id}/{_trace_filename(case)})"
            if case.trace_id
            else "legacy"
        )
        evidence_summary.append(
            f"| {case.case_id} / {case.trial_id} | {trace} "
            f"| {case.evidence_status} | {case.evaluation_validity} "
            f"| {', '.join(i.get('code', '') for i in case.evaluation_issues)} |"
        )
    report_path.write_text(
        _markdown(result, capabilities) + "\n".join(evidence_summary) + "\n",
        encoding="utf-8",
    )
    return ReportPaths(
        output_dir=str(root),
        manifest=str(manifest_path),
        results=str(results_path),
        summary=str(report_path),
        report=str(report_path),
        summary_json=str(summary_json_path),
        results_jsonl=str(results_jsonl_path),
        failures=str(failures_path),
        case_files=case_files,
        evidence_files=evidence_files,
    )


def write_invalid_run(
    error: EvaluationPreflightError,
    record: InvalidRunRecord,
    output_dir: str | Path,
) -> InvalidRunPaths:
    root = Path(output_dir).resolve() / record.run_id
    root.mkdir(parents=True, exist_ok=False)
    record_path = root / "invalid_run.json"
    report_path = root / "report.md"
    record_path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    evidence = "、".join(error.evidence_refs) if error.evidence_refs else "无"
    report_path.write_text(
        "\n".join(
            [
                "# Agent 自动化评测报告",
                "",
                "> **评测结论：INVALID_RUN**",
                ">",
                "> 评测在执行 Agent 前未通过预检，因此不产生质量通过率。",
                "",
                "## 预检错误",
                "",
                f"- 错误代码：`{record.error_code}`",
                f"- 错误信息：{record.message}",
                f"- Provider：`{record.provider_id}`",
                f"- 数据集：`{record.dataset_path}`",
                f"- 证据：{evidence}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return InvalidRunPaths(
        output_dir=str(root),
        record=str(record_path),
        report=str(report_path),
    )


def _manifest(result: EvaluationRunResult) -> dict[str, Any]:
    return {
        "evaluator_version": "0.1.0",
        "compiled_suite_sha256": result.compiled_suite_sha256,
        "compiled_suite_snapshot": result.compiled_suite_snapshot,
        "plugin_fingerprints": result.plugin_fingerprints,
        "contract_fingerprints": result.contract_fingerprints,
        "agent_version": result.agent_version,
        "provider_id": result.provider_id,
        "provider_version": result.provider_version,
        "capability_bundle_sha256": result.capability_bundle_sha256,
        "run_mode": result.run_config.run_mode,
        "model": result.model_metadata,
        "tools": [
            {
                "case_id": case.case_id,
                "profile": case.tool_profile,
                "version": case.tool_version,
            }
            for case in result.cases
        ],
        "dataset": {
            "path": result.dataset_path,
            "version": result.dataset_version,
            "sha256": result.dataset_hash,
            "state": result.dataset_lifecycle_state,
            "manifest_path": result.dataset_manifest_path,
            "sample_count": result.summary.total_cases,
            "total_case_count": result.dataset_total_cases,
            "executed_case_count": result.summary.total_cases,
            "total_trial_count": result.summary.total_trials,
        },
        "execution_type": result.run_config.execution_type,
        "trials_per_case": result.trials_per_case,
        "judge": result.judge_metadata,
        "diagnostic_metadata": result.diagnostic_metadata,
        "evaluation_backend": result.evaluation_backend,
        "native_artifacts": result.native_artifacts,
        "stability_version": (
            result.stability.stability_version if result.stability else None
        ),
        "assertion_registry_version": result.assertion_registry_version,
        "core_behavior_policy_version": CORE_BEHAVIOR_POLICY_VERSION,
        "pass_threshold": result.run_config.pass_threshold,
        "execution_limits": [
            {
                "case_id": case.case_id,
                "max_steps": case.max_steps,
                "timeout_seconds": case.timeout_seconds,
            }
            for case in result.cases
        ],
        "filters": (
            result.run_config.filters.model_dump(mode="json")
            if result.run_config.filters
            else None
        ),
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "python_version": platform.python_version(),
    }


def _run_verdict(result: EvaluationRunResult) -> str:
    if any(case.evaluation_validity == "INVALID" for case in result.cases):
        return "INVALID_RUN"
    if any(case.execution_status != "COMPLETED" for case in result.cases):
        return "INVALID_RUN"
    if any(case.quality_conclusion == "INCONCLUSIVE" for case in result.cases):
        return "MANUAL_REVIEW_REQUIRED"
    if any(case.quality_conclusion == "FAIL" for case in result.cases):
        return "FAILED"
    return "PASSED"


def _summary_payload(result: EvaluationRunResult) -> dict[str, Any]:
    summary = result.summary
    judge_results = [
        case.judge_result for case in result.cases if case.judge_result is not None
    ]
    trace_analyses = [
        case.trace_analysis for case in result.cases if case.trace_analysis is not None
    ]
    return {
        "run_id": result.evaluator_run_id,
        "diagnostic_metadata": result.diagnostic_metadata,
        "diagnostic_metrics": {
            name: metric.model_dump(mode="json")
            for name, metric in summary.diagnostic_metrics.items()
        },
        "run_verdict": _run_verdict(result),
        "provisional": result.dataset_lifecycle_state != "FROZEN",
        "core_behavior_policy_version": CORE_BEHAVIOR_POLICY_VERSION,
        "framework": {
            "completion_rate": summary.framework_completion_rate,
            "execution_status_counts": summary.execution_status_counts,
        },
        "agent_quality": {
            "deterministic_score_average": summary.average_score,
            "strict_assertion_pass_rate": summary.strict_assertion_pass_rate,
            "core_behavior_match_rate": summary.core_behavior_match_rate,
            "average_score": summary.average_score,
            "quality_counts": summary.quality_counts,
        },
        "judge": {
            "metadata": result.judge_metadata,
            "applicable_trials": len(judge_results),
            "status_counts": dict(Counter(item.status for item in judge_results)),
        },
        "trace": {
            "collection_status_counts": dict(
                Counter(case.evidence_status for case in result.cases)
            ),
            "evaluation_validity_counts": dict(
                Counter(case.evaluation_validity for case in result.cases)
            ),
            "analyzed_trials": len(trace_analyses),
            "observation_count": sum(len(item.issues) for item in trace_analyses),
        },
        "stability": (
            result.stability.model_dump(mode="json")
            if result.stability is not None
            else None
        ),
        "performance": {
            "average_latency_ms": summary.average_latency_ms,
            "median_latency_ms": summary.median_latency_ms,
            "max_latency_ms": summary.max_latency_ms,
            "total_duration_ms": result.total_duration_ms,
            "metrics": (
                summary.performance.model_dump(mode="json")
                if summary.performance is not None else None
            ),
        },
        "groups": {
            "by_scope": summary.by_scope,
            "by_intent": summary.by_intent,
            "by_expected_intent": summary.by_expected_intent,
            "by_actual_intent": summary.by_actual_intent,
            "by_task_id": summary.by_task_id,
        },
        "failed_assertions": summary.failed_assertions,
    }


def _failures_payload(result: EvaluationRunResult) -> dict[str, Any]:
    execution_errors = [
        {
            "case_id": case.case_id,
            "execution_status": case.execution_status,
            "exception": case.exception,
        }
        for case in result.cases
        if case.execution_status != "COMPLETED"
    ]
    quality_failures = [
        {
            "case_id": case.case_id,
            "score": case.score,
            "first_failed_assertion": (
                case.first_failed_assertion.name
                if case.first_failed_assertion
                else None
            ),
            "failed_assertions": [
                assertion.name
                for assertion in case.assertion_results
                if assertion.passed is False
            ],
            "diagnoses": [
                diagnosis.model_dump(mode="json") for diagnosis in case.diagnoses
            ],
        }
        for case in result.cases
        if case.quality_conclusion == "FAIL"
    ]
    return {
        "execution_errors": execution_errors,
        "quality_failures": quality_failures,
    }


def _markdown(
    result: EvaluationRunResult,
    capabilities: CapabilityRegistry | None = None,
) -> str:
    summary = result.summary
    verdict = _run_verdict(result)
    completed = summary.execution_status_counts.get("COMPLETED", 0)
    passed = summary.quality_counts.get("PASS", 0)
    failed = summary.quality_counts.get("FAIL", 0)
    inconclusive = summary.quality_counts.get("INCONCLUSIVE", 0)
    errors = summary.total_trials - completed
    lines = [
        "# Agent 自动化评测报告",
        "",
        f"> **评测结论：{verdict}**",
        ">",
        f"> {_verdict_sentence(result, verdict)}",
        "",
    ]
    if result.dataset_lifecycle_state != "FROZEN":
        lines.extend(
            [
                "> **临时质量观察：当前数据集未冻结；这是临时评测结果，"
                "不可作为基线、发布门禁或正式 Agent 质量结论。**",
                "",
            ]
        )
    lines.extend(
        [
            "## 执行摘要",
            "",
            "| 指标 | 结果 |",
            "|---|---:|",
            f"| 总 Case 数 | {summary.total_cases} |",
            f"| 总 Trial 数 | {summary.total_trials} |",
            f"| 数据集状态 | {result.dataset_lifecycle_state} |",
            f"| 执行案例 | {summary.total_cases}/{result.dataset_total_cases} |",
            f"| 执行类型 | {EXECUTION_TYPE_LABELS[result.run_config.execution_type]} |",
            f"| 每 Case Trial 数 | {result.trials_per_case} |",
            f"| 执行完成 | {completed}/{summary.total_trials} |",
            f"| PASS | {passed} |",
            f"| FAIL | {failed} |",
            f"| ERROR | {errors} |",
            f"| INCONCLUSIVE | {inconclusive} |",
            f"| 严格断言通过率 | {_rate(summary.strict_assertion_pass_rate)} |",
            f"| 确定性断言平均分 | {_display(summary.average_score)}/100 |",
            f"| 核心行为匹配率 | {_rate(summary.core_behavior_match_rate)} |",
            f"| 模型输出错误 | {_status_count(summary, 'MODEL_OUTPUT_ERROR')} |",
            f"| 模型调用错误 | {_status_count(summary, 'MODEL_INVOCATION_ERROR')} |",
            f"| 模型超时 | {_status_count(summary, 'MODEL_TIMEOUT')} |",
            f"| Agent 异常 | {_status_count(summary, 'AGENT_EXCEPTION')} |",
            f"| 初始化错误 | {_status_count(summary, 'INITIALIZATION_ERROR')} |",
            f"| Evaluator 错误 | {_status_count(summary, 'EVALUATOR_ERROR')} |",
            f"| 外层超时 | {_status_count(summary, 'OUTER_TIMEOUT')} |",
            f"| 平均断言得分 | {_display(summary.average_score)}/100（辅助诊断） |",
            "| 单 Case 通过条件 | "
            f"{result.run_config.pass_threshold} 分且关键断言通过 |",
            f"| 中位延迟 | {summary.median_latency_ms} ms |",
            f"| 平均延迟 | {summary.average_latency_ms} ms |",
            f"| 最大延迟 | {summary.max_latency_ms} ms |",
            f"| 评测范围 | {_scope_summary(summary)} |",
            "",
            "## 主要问题",
            "",
        ]
    )
    lines.extend(_issue_summary(result))
    lines.extend(_phase_two_sections(result))
    lines.extend(["", "## Case 结果", ""])
    lines.extend(
        [
            "| Case | 场景 | 场景类型 | 预期行为 | 实际行为 | 结论 | 首个偏差 | 延迟 |",
            "|---|---|---|---|---|---|---|---:|",
        ]
    )
    for case in result.cases:
        actual = _escape(_actual_behavior(case, capabilities))
        lines.append(
            f"| [{_escape(case.case_id)} / {case.trial_id}]"
            f"(cases/{case.case_id}/{case.trial_id}.json) "
            f"| {_escape(case.user_input)} "
            f"| {SCENARIO_TYPE_LABELS[case.scenario_type]} "
            f"| {_escape(_expected_behavior(case, capabilities))} "
            f"| {actual} | {case.quality_conclusion} "
            f"| {_escape(_first_failed_check(case))} "
            f"| {case.latency_ms} ms |"
        )

    failures = [
        case
        for case in result.cases
        if case.execution_status != "COMPLETED"
        or case.quality_conclusion in {"FAIL", "INCONCLUSIVE"}
    ]
    lines.extend(["", "## 失败与异常详情", ""])
    if not failures:
        lines.append("无。")
    for case in failures:
        lines.extend(_case_detail(case))

    group_sections = _group_sections(result)
    if group_sections:
        lines.extend(["", "## 分组指标", ""])
        lines.extend(group_sections)
    lines.extend(
        [
            "",
            "## 运行与复现信息",
            "",
            "| 项目 | 内容 |",
            "|---|---|",
            f"| Run ID | `{result.evaluator_run_id}` |",
            f"| 运行模式 | `{result.run_config.run_mode}` |",
            f"| 模型 | `{result.model_metadata.get('model', 'unknown')}` |",
            f"| 数据集 | `{Path(result.dataset_path).name}` |",
            f"| 数据集版本 | `{result.dataset_version}` |",
            f"| 数据集状态 | `{result.dataset_lifecycle_state}` |",
            f"| Agent 版本 | `{result.agent_version}` |",
            f"| Provider | `{result.provider_id}` |",
            f"| Provider 版本 | `{result.provider_version}` |",
            f"| 能力 Bundle SHA-256 | `{result.capability_bundle_sha256}` |",
            f"| 断言版本 | `{result.assertion_registry_version}` |",
            f"| 通过阈值 | `{result.run_config.pass_threshold}` |",
            f"| 开始时间 | `{result.started_at}` |",
            f"| 结束时间 | `{result.finished_at}` |",
            "",
            "完整路径、SHA-256、模型客户端和执行限制请查看 "
            "[查看完整运行配置](run_manifest.json)。",
        ]
    )
    if result.evaluation_backend:
        backend = result.evaluation_backend
        lines.extend(
            [
                "",
                f"评测引擎：{backend['name']} {backend['version']} "
                f"（{backend['adapter_version']}）。",
            ]
        )
        if path := result.native_artifacts.get("test_run"):
            lines.append(f"[查看评测引擎原生运行记录]({path})。")
    return "\n".join(lines) + "\n"


def _phase_two_sections(result: EvaluationRunResult) -> list[str]:
    lines = ["", "## DeepSeek Judge", ""]
    if result.summary.diagnostic_metrics:
        lines.extend([
            "## Conversation Completeness（诊断）", "",
            "分数范围 0–1；仅展示成功判分的均值，错误保留在状态计数中。",
            "尚未校准，不参与 PASS/FAIL 或发布 Gate。", "",
        ])
        for name, metric in result.summary.diagnostic_metrics.items():
            lines.append(
                f"- {name}：均值 {_display(metric.mean_score)}；"
                f"成功判分 {metric.scored_trials}；状态 {metric.status_counts}"
            )
        for case in result.cases:
            if case.diagnostic_metrics:
                lines.append(f"- [{case.case_id}/{case.trial_id} 诊断证据]"
                             f"(diagnostics/{case.case_id}/{case.trial_id}.json)")
        lines.extend(["", "## 语义 Judge", ""])
    judged = [case for case in result.cases if case.judge_result is not None]
    if not judged:
        lines.append("本次没有配置适用的 Judge Trial。")
    else:
        metadata = result.judge_metadata or {}
        lines.extend(
            [
                "Judge 仅评价声明的语义质量维度；Judge 分数不能替代确定性断言结论。",
                "",
                f"- 适用 Trial：{len(judged)}/{result.summary.total_trials}",
                f"- 模型：`{metadata.get('model', 'unknown')}`",
                f"- Prompt 版本：`{metadata.get('prompt_version', 'unknown')}`",
                f"- Rubric：`{metadata.get('rubric_id', 'unknown')}` / "
                f"`{metadata.get('rubric_version', 'unknown')}`",
            ]
        )
        lines.extend(
            f"- [{case.case_id}/{case.trial_id} Judge 证据]"
            f"(judge/{case.case_id}/{case.trial_id}.json)："
            f"{case.judge_result.status}，score="
            f"{_display(case.judge_result.score)}"
            for case in judged
        )

    analyzed = [case for case in result.cases if case.trace_analysis is not None]
    issue_count = sum(len(case.trace_analysis.issues) for case in analyzed)
    lines.extend(["", "## Trace 观察", ""])
    if not analyzed:
        lines.append("本次没有可用的 Trace 分析。")
    else:
        lines.append(
            f"共分析 {len(analyzed)} 个 Trial，记录 {issue_count} 条可观察现象或建议；"
            "这些记录用于定位，不直接宣称最终原因。"
        )
        lines.extend(
            f"- [{case.case_id}/{case.trial_id} Trace 分析]"
            f"(trace_analysis/{case.case_id}/{case.trial_id}.json)："
            f"{len(case.trace_analysis.issues)} 条"
            for case in analyzed
        )

    lines.extend(["", "## Trial 稳定性", ""])
    stability = result.stability
    if stability is None:
        lines.append("本次没有稳定性聚合。")
    else:
        volatile = sum(item.quality_volatile for item in stability.cases)
        output_volatile = sum(item.output_volatile for item in stability.cases)
        lines.extend(
            [
                "[查看稳定性机器结果](stability.json)",
                "",
                f"- pass@k：{_rate(stability.pass_at_k_rate)}",
                f"- pass^k：{_rate(stability.pass_power_k_rate)}",
                f"- Trial 通过率：{_rate(stability.trial_pass_rate)}",
                f"- 质量波动 Case：{volatile}/{len(stability.cases)}",
                f"- 输出波动 Case：{output_volatile}/{len(stability.cases)}",
                f"- P50 延迟：{_display(stability.latency_p50_ms)} ms",
                f"- P95 延迟（{result.summary.total_trials} 个样本的观察值）："
                f"{_display(stability.latency_p95_ms)} ms",
            ]
        )
    return lines


def _expected_behavior(
    case: CaseResult, capabilities: CapabilityRegistry | None = None
) -> str:
    if case.test_scope == "module":
        field_assertions = {
            "intent_match": "intent",
            "status_match": "status",
            "next_action_match": "next_action",
            "params_match": "parameters",
            "missing_params_match": "missing_parameters",
        }
        expected = {
            field: assertion.expected
            for assertion in case.assertion_results
            if (field := field_assertions.get(assertion.name)) is not None
        }
        return _module_behavior_summary(expected, capabilities)
    tool = next(
        (
            assertion.expected
            for assertion in case.assertion_results
            if assertion.name == "tool_called"
        ),
        None,
    )
    arguments = next(
        (
            assertion.expected
            for assertion in case.assertion_results
            if assertion.name == "tool_args_match"
        ),
        None,
    )
    if tool:
        return _tool_behavior_summary(str(tool), arguments, prefix="调用工具")
    if any(
        assertion.name == "confirmation_requested"
        for assertion in case.assertion_results
    ):
        return "请求用户确认"
    return "按预期完成任务"


def _actual_behavior(
    case: CaseResult, capabilities: CapabilityRegistry | None = None
) -> str:
    if case.execution_status != "COMPLETED":
        return _execution_status_label(case.execution_status)
    if case.test_scope == "module":
        return _module_behavior_summary(case.module_output or {}, capabilities)
    if case.tool_calls:
        call = case.tool_calls[0]
        summary = _tool_behavior_summary(
            str(call.get("name", "unknown")),
            call.get("arguments"),
            prefix="调用工具",
        )
        if len(case.tool_calls) > 1:
            summary += f"；共 {len(case.tool_calls)} 次调用"
        return summary
    if case.turn_results:
        turn = case.turn_results[-1]
        if turn.get("status") == "NEED_CONFIRMATION":
            return "请求用户确认"
        response = str(turn.get("final_response") or "").strip()
        if response:
            return f"回复：{_truncate(response)}"
    return "未产生可观察行为"


def _module_behavior_summary(
    output: dict[str, Any],
    capabilities: CapabilityRegistry | None = None,
) -> str:
    action = output.get("next_action")
    intent = str(output.get("intent") or "unknown")
    field_labels, missing_labels = _display_labels(capabilities, intent)
    if action == "CALL_TOOL":
        return _tool_behavior_summary(
            intent,
            output.get("parameters"),
            prefix="准备调用工具",
            field_labels=field_labels,
        )
    if action == "ASK_USER":
        missing = output.get("missing_parameters") or []
        labels = [missing_labels.get(str(item), str(item)) for item in missing]
        return f"追问：请提供{'、'.join(labels)}" if labels else "追问用户补充信息"
    if action == "ASK_CONFIRMATION":
        return "请求用户确认"
    if action == "REJECT":
        return "拒绝请求"
    if action in {"RESPOND", "RETURN_RESPONSE"}:
        return "直接回复用户"
    return str(action or output.get("status") or "无可观察行为")


def _tool_behavior_summary(
    name: str,
    arguments: Any,
    *,
    prefix: str,
    field_labels: dict[str, str] | None = None,
) -> str:
    params = _format_behavior_arguments(arguments, field_labels or {})
    return f"{prefix}：`{name}`{f'（{params}）' if params else ''}"


def _format_behavior_arguments(arguments: Any, field_labels: dict[str, str]) -> str:
    if not isinstance(arguments, dict) or not arguments:
        return ""
    return "，".join(
        f"`{field_labels.get(name, name)}={_behavior_value(value)}`"
        for name, value in arguments.items()
    )


def _display_labels(
    capabilities: CapabilityRegistry | None, intent: str
) -> tuple[dict[str, str], dict[str, str]]:
    if capabilities is None:
        return {}, {}
    try:
        display = capabilities.display_metadata(intent)
    except KeyError:
        return {}, {}
    fields = display.get("field_labels", {})
    missing = display.get("missing_parameter_labels", {})
    return (
        fields if isinstance(fields, dict) else {},
        missing if isinstance(missing, dict) else {},
    )


def _resolve_capabilities(
    result: EvaluationRunResult,
) -> CapabilityRegistry | None:
    try:
        dataset = load_dataset(result.dataset_path)
        if dataset.capability_bundle_path is None:
            return None
        return CapabilityRegistry(
            CapabilityBundle.load(Path(dataset.capability_bundle_path))
        )
    except (OSError, ValueError):
        return None


def _behavior_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _truncate(value: str, limit: int = 60) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _execution_status_label(status: str) -> str:
    return {
        "MODEL_OUTPUT_ERROR": "模型输出错误",
        "MODEL_INVOCATION_ERROR": "模型调用错误",
        "MODEL_TIMEOUT": "模型超时",
        "AGENT_EXCEPTION": "Agent 异常",
        "INITIALIZATION_ERROR": "初始化错误",
        "EVALUATOR_ERROR": "Evaluator 错误",
        "OUTER_TIMEOUT": "外层超时",
    }.get(status, status)


def _verdict_sentence(result: EvaluationRunResult, verdict: str) -> str:
    summary = result.summary
    passed = summary.quality_counts.get("PASS", 0)
    failed = summary.quality_counts.get("FAIL", 0)
    completed = summary.execution_status_counts.get("COMPLETED", 0)
    errors = summary.total_trials - completed
    issue_titles = []
    for case in result.cases:
        for diagnosis in case.diagnoses:
            if diagnosis.title not in issue_titles:
                issue_titles.append(diagnosis.title)
    issue_text = "、".join(issue_titles[:3])
    if verdict == "PASSED":
        return f"{completed} 条全部执行完成，Agent 通过 {passed} 条，达到本次评测条件。"
    if verdict == "FAILED":
        suffix = f"主要问题为{issue_text}。" if issue_text else ""
        return (
            f"{completed} 条全部执行完成；严格断言通过 {passed} 条、"
            f"失败 {failed} 条，未达到本次评测通过条件。{suffix}"
        )
    if verdict == "MANUAL_REVIEW_REQUIRED":
        return "执行正常，但存在无法判定的 Case，需要人工复核。"
    return f"本次评测存在 {errors} 条执行异常，结果不能完整代表 Agent 质量。"


def _issue_summary(result: EvaluationRunResult) -> list[str]:
    issues: Counter[str] = Counter()
    metadata: dict[str, dict[str, str]] = {}
    failed_case_count = sum(case.quality_conclusion == "FAIL" for case in result.cases)
    for case in result.cases:
        if case.execution_status != "COMPLETED":
            code = f"EXECUTION_{case.execution_status}"
            issues[code] += 1
            metadata.setdefault(
                code,
                {
                    "title": f"执行异常：{case.execution_status}",
                    "representative": case.case_id,
                    "area": "模型调用与评测基础设施",
                },
            )
        for diagnosis in case.diagnoses:
            issues[diagnosis.code] += 1
            metadata.setdefault(
                diagnosis.code,
                {
                    "title": diagnosis.title,
                    "representative": case.case_id,
                    "area": INVESTIGATION_AREAS.get(diagnosis.category, "相关断言实现"),
                },
            )
    if not issues:
        return ["未发现质量失败或执行异常。"]
    lines = [
        "| 问题类型 | 影响 Case 数 | 失败 Case 占比 | 代表 Case | 建议排查环节 |",
        "|---|---:|---:|---|---|",
    ]
    for code, count in issues.most_common():
        item = metadata[code]
        rate = round(100 * count / failed_case_count, 1) if failed_case_count else 0
        lines.append(
            f"| {_escape(item['title'])} | {count} | {rate}% | "
            f"{_escape(item['representative'])} | {_escape(item['area'])} |"
        )
    return lines


def _case_detail(case: CaseResult) -> list[str]:
    title = case.diagnoses[0].title if case.diagnoses else _primary_issue(case)
    lines = [
        f"### {case.case_id}：{title}",
        "",
        f"> {_escape(case.user_input)}",
        "",
    ]
    if case.execution_status != "COMPLETED":
        exception = case.exception or {}
        lines.extend(
            [
                "| 异常类型 | 信息 |",
                "|---|---|",
                f"| {_escape(exception.get('type', 'unknown'))} "
                f"| {_escape(exception.get('message', ''))} |",
                "",
            ]
        )
    failed = [item for item in case.assertion_results if item.passed is False]
    if failed:
        lines.extend(
            [
                "**失败断言**",
                "",
                "| 检查项 | 预期 | 实际 |",
                "|---|---|---|",
            ]
        )
        for assertion in failed:
            lines.append(
                f"| {_escape(_assertion_label(assertion.name))} "
                f"| {_escape(_compact(assertion.expected))} "
                f"| {_escape(_compact(assertion.actual))} |"
            )
        lines.append("")
    lines.extend(
        [
            f"第一处失败检查：{_first_failed_check(case)}",
            "",
            "证据：" + " / ".join(_evidence_links(case)),
            "",
        ]
    )
    return lines


def _primary_issue(case: CaseResult) -> str:
    if case.execution_status != "COMPLETED":
        exception = case.exception or {}
        message = exception.get("message")
        return f"{case.execution_status}{f'：{message}' if message else ''}"
    if case.diagnoses:
        return case.diagnoses[0].title
    if case.quality_conclusion == "INCONCLUSIVE":
        return "证据不足，无法判定"
    return "—"


def _first_failed_check(case: CaseResult) -> str:
    if case.execution_status != "COMPLETED":
        return case.execution_status
    if case.first_failed_assertion:
        return _assertion_label(case.first_failed_assertion.name)
    return "—"


def _evidence_links(case: CaseResult) -> list[str]:
    base = f"evidence/{case.case_id}/{case.trial_id}"
    links = [
        f"[完整 Case JSON](cases/{case.case_id}/{case.trial_id}.json)",
        f"[原始输出]({base}/actual.json)",
        f"[断言结果]({base}/assertions.json)",
    ]
    if case.trace_id:
        trace_base = f"evidence/{case.trace_id}"
        links.extend(
            [
                f"[Trace 原始事件]({trace_base}/{_trace_filename(case)})",
                f"[采集状态]({trace_base}/"
                + (
                    "trace.inspect.json)"
                    if _trace_filename(case) == "trace.inspect.json"
                    else "collection.json)"
                ),
                f"[案例关联]({trace_base}/association.json)",
            ]
        )
    elif case.trace_events:
        links.append(f"[Trace]({base}/trace.jsonl)")
    if case.exception and case.exception.get("diagnostic"):
        links.append(f"[模型错误证据]({base}/model_error.json)")
    if case.system_snapshot is not None:
        links.append(f"[系统终态]({base}/state.json)")
    return links


def _trace_filename(case: CaseResult) -> str:
    return (
        "trace.inspect.json"
        if case.evidence_manifest.get("storage_backend") == "inspect-eval-log"
        else "events.jsonl"
    )


def _assertion_label(name: str) -> str:
    return ASSERTION_LABELS.get(name, name)


def _group_sections(result: EvaluationRunResult) -> list[str]:
    summary = result.summary
    sections = []
    for title, groups in (
        ("按评测范围", summary.by_scope),
        ("按意图", summary.by_intent),
        ("按任务", summary.by_task_id),
    ):
        if len(groups) < 2:
            continue
        sections.extend([f"### {title}", ""])
        for name, value in groups.items():
            denominator = value.get("applicable_count", value["count"])
            rate = value["pass_rate"]
            fraction = (
                f"{value['pass_count']}/{denominator} PASS "
                if rate is not None else ""
            )
            sections.append(
                f"- `{name}`：{fraction}({_rate(rate)}；共 {value['count']} Trial)"
            )
        sections.append("")
    return sections


def _scope_summary(summary: Any) -> str:
    parts = [
        ", ".join(summary.by_scope) or "—",
        ", ".join(summary.by_intent) or "—",
        ", ".join(summary.by_task_id) or "—",
    ]
    return " / ".join(parts)


def _compact(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _display(value: Any) -> str:
    return "—" if value is None else str(value)


def _rate(value: float | None) -> str:
    return "不适用" if value is None else f"{value}%"


def _status_count(summary: Any, status: str) -> int:
    return summary.execution_status_counts.get(status, 0)
