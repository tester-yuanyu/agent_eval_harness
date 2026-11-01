"""Offline, source-bound diagnostics; never rewrite or rerun saved executions."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .regrade import _validate_source
from .repetition import REPETITION_VERSION, score_repetition
from .report import evidence_summary
from .runner import compare_runs, digest, save_json
from .tasks import dataset_identity, load_tasks

AUDIT_VERSION = "benchmark-quality-audit-v1"


def _load(path: Path) -> tuple[dict, dict, bytes]:
    path = Path(path)
    path = path / "results.json" if path.is_dir() else path
    raw = path.read_bytes()
    value = json.loads(raw)
    return (
        value,
        {
            "file": f"{path.parent.name}/{path.name}",
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        raw,
    )


def _summary(records: list[dict]) -> dict:
    statuses = Counter(record["status"] for record in records)
    scored = [record for record in records if record["status"] == "SCORED"]
    applicable = len(records) - statuses["NOT_APPLICABLE"]
    candidates = sum(record["score"] == 0 for record in scored)
    return {
        "total": len(records),
        "applicable": applicable,
        "scored": len(scored),
        "missing": statuses["MISSING"],
        "unscorable_traces": sum(
            r.get("scope") == "task" and r["status"] == "MISSING" for r in records
        ),
        "not_applicable": statuses["NOT_APPLICABLE"],
        "coverage": len(scored) / applicable if applicable else None,
        "candidates": candidates,
        "candidate_rate_scored": candidates / len(scored) if scored else None,
        "classifications": dict(Counter(r["classification"] for r in records)),
    }


def _comparison(baseline: Path, candidate: Path) -> tuple[dict, list[dict]]:
    left, left_source, _ = _load(baseline)
    right, right_source, _ = _load(candidate)
    for run in (left, right):
        if digest(run["identity"]) != run["identity_hash"]:
            raise ValueError("comparison source identity hash is inconsistent")
        evidence_summary(run)  # Reject duplicate or unplanned saved trials.
        if run.get("mode") != "real_agent":
            raise ValueError("configuration comparison requires real Agent evidence")
        if (
            "config" in run["identity"]
            and run.get("config") != run["identity"]["config"]
        ):
            raise ValueError("comparison config does not match its bound identity")
        if any(
            row.get("identity_hash") != run["identity_hash"]
            or not isinstance(row.get("observation"), dict)
            or row["observation"].get("execution_kind") != "real_agent"
            for row in run["trials"]
        ):
            raise ValueError("comparison trials lack matching real Agent identity")
    changed = {
        key
        for key in set(left.get("config", {})) | set(right.get("config", {}))
        if left.get("config", {}).get(key) != right.get("config", {}).get(key)
    }
    runtime = [
        {k: v for k, v in run["identity"].get("runtime", {}).items() if k != "variant"}
        for run in (left, right)
    ]
    if changed - {"instructions", "variant"} or runtime[0] != runtime[1]:
        raise ValueError(
            "comparison control variables changed; only prompt variants allowed"
        )
    result = compare_runs(left, right)
    transitions = result["changed_trials"]
    lookup = {(r["case_id"], r["trial"]): r for r in right["trials"]}
    failure_examples = []
    for row in right["trials"]:
        if row["assessment"]["verdict"] != "FAIL":
            continue
        failure_examples.append(
            {
                "case_id": row["case_id"],
                "trial": row["trial"],
                "failed_metrics": [
                    m["name"]
                    for m in row["assessment"].get("metrics", [])
                    if m.get("formal") and m.get("success") is False
                ],
            }
        )
        if len(failure_examples) == 8:
            break
    return {
        "status": "saved_same_policy_comparison",
        "dataset_id": result["dataset"].get("dataset_id"),
        "scoring_version": left["identity"]["scoring_version"],
        "baseline_run_id": left["run_id"],
        "candidate_run_id": right["run_id"],
        "baseline": result["baseline"],
        "candidate": result["candidate"],
        "pass_rate_delta": result["pass_rate_delta"],
        "changed_configuration_fields": sorted(changed),
        "improvements": sum(
            r["baseline"] == "FAIL" and r["candidate"] == "PASS" for r in transitions
        ),
        "regressions": sum(
            r["baseline"] == "PASS" and r["candidate"] == "FAIL" for r in transitions
        ),
        "changed_trials": [
            {
                **r,
                "candidate_failed_metrics": [
                    m["name"]
                    for m in lookup[r["case_id"], r["trial"]]["assessment"].get(
                        "metrics", []
                    )
                    if m.get("formal") and m.get("success") is False
                ],
            }
            for r in transitions
        ],
        "failure_examples": failure_examples,
        "interpretation": (
            "历史同口径配置对比；非 v1/v2 能力提升，非新增执行或显著性结论。"
        ),
    }, [left_source, right_source]


def _markdown(result: dict) -> str:
    lines = [
        "# 评测质量离线检查",
        "",
        "本报告读取保存的真实执行，附加重复调用候选诊断；没有新 Agent 执行或模型请求。",
        "原始正式判定保持原口径。重复候选可能是合法验证性读取，不代表无必要或任务失败。",
        "",
        "| 运行 | 原始 Trials | 已评分 / 适用 | 重复候选 | 缺证据 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for run in result["runs"]:
        metric = run["repetition"]
        lines.append(
            f"| {run['run_id']} | {run['saved_trials']} | "
            f"{metric['scored']} / {metric['applicable']} | "
            f"{metric['candidates']} | {metric['missing']} |"
        )
    lines.extend(
        [
            "",
            "候选率 = 重复候选数 / 已评分工具记录数；覆盖率 = 已评分数 / 适用数。"
            "缺证据保留在适用分母，无工具的完整轨迹不适用。"
            "全轨迹证据无效时使用一条任务级缺失记录，另计 unscorable_traces；"
            "此时适用分母是诊断记录数，不能称作完整工具调用数。",
            "",
            "[逐节点诊断](repetition-records.jsonl) · "
            "[完整统计及来源 Hash](summary.json)",
            "",
        ]
    )
    comparison = result["comparison"]
    if comparison["status"] == "not_supplied":
        lines.append("未提供同口径对比；本次诊断不能被称作版本提升。")
    else:
        left, right = comparison["baseline"], comparison["candidate"]
        lines.extend(
            [
                "## 保存结果的同口径配置对比",
                "",
                f"数据集：{comparison['dataset_id']}；评分版本：{comparison['scoring_version']}。",
                f"基线通过率 {left['pass_rate_planned']:.2%}，"
                f"候选 {right['pass_rate_planned']:.2%}；"
                f"差值 {100 * comparison['pass_rate_delta']:.2f} 个百分点。",
                "按 case_id × trial 对齐："
                f"{comparison['improvements']} 次 FAIL → PASS，"
                f"{comparison['regressions']} 次 PASS → FAIL。",
                "",
                comparison["interpretation"],
                "",
                "逐条改善、退化与代表失败的指标标识保存在 summary.json。",
            ]
        )
    lines.extend(
        [
            "",
            "## 尚需独立证据",
            "",
            "- Judge 人工标签、分档示例审定和独立留出阈值验收未完成。",
            "- 当前 v2 未新增配置 A/B；已有 v1 对比不能证明 v2 提升。",
            "- 货币成本缺少可靠来源时保留未知，Token 与覆盖率单列。",
            "",
        ]
    )
    return "\n".join(lines)


def build_quality_audit(
    run_paths: list[Path],
    dataset_path: Path,
    output_dir: Path,
    *,
    baseline: Path | None = None,
    candidate: Path | None = None,
) -> dict[str, Any]:
    """Diagnose saved file-tool evidence and optionally verify a prompt-only A/B."""
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise ValueError("audit output already exists; use a new directory")
    if not run_paths or (baseline is None) != (candidate is None):
        raise ValueError("provide runs and both comparison inputs or neither")
    tasks = {t["id"]: t for t in load_tasks(Path(dataset_path))}
    dataset = dataset_identity(Path(dataset_path))
    sources, runs, records, seen, originals = [], [], [], set(), []
    for path in run_paths:
        run, source, raw = _load(path)
        if run["identity"]["dataset"] != dataset:
            raise ValueError("audit dataset does not match the saved run")
        _validate_source(run, tasks)
        if run.get("provenance", {}).get("operation") == "judge_saved_evidence":
            raise ValueError("use execution runs, not Judge annotations")
        if run.get("mode") not in {"real_agent", "real_module", "real_model_decision"}:
            raise ValueError("audit requires real saved execution evidence")
        identity = run.get("execution_run_id", run["run_id"])
        if identity in seen:
            raise ValueError("duplicate execution input")
        seen.add(identity)
        current = []
        for row in run["trials"]:
            for metric in score_repetition(tasks[row["case_id"]], row["observation"]):
                current.append(
                    {
                        "run_id": run["run_id"],
                        "case_id": row["case_id"],
                        "trial": row["trial"],
                        **{
                            k: metric.get(k)
                            for k in (
                                "name",
                                "version",
                                "scope",
                                "event_id",
                                "evidence_ids",
                                "score",
                                "status",
                                "formal",
                                "classification",
                                "current_is_error",
                                "reason",
                                "semantics",
                                "backend",
                                "implementation",
                                "library_version",
                            )
                        },
                    }
                )
        sources.append(source)
        originals.append((Path(path), raw))
        runs.append(
            {
                "run_id": run["run_id"],
                "execution_run_id": identity,
                "saved_trials": len(run["trials"]),
                "saved_verdicts": dict(
                    Counter(r["assessment"]["verdict"] for r in run["trials"])
                ),
                "saved_assessments_sha256": digest(
                    [r["assessment"] for r in run["trials"]]
                ),
                "repetition": _summary(current),
            }
        )
        records.extend(current)
    comparison = {"status": "not_supplied"}
    if baseline is not None:
        comparison, comparison_sources = _comparison(baseline, candidate)
        sources.extend(comparison_sources)
    result = {
        "version": AUDIT_VERSION,
        "diagnostic_version": REPETITION_VERSION,
        "diagnostic_source_sha256": hashlib.sha256(
            Path(__file__).with_name("repetition.py").read_bytes()
        ).hexdigest(),
        "new_agent_executions": 0,
        "new_model_requests": 0,
        "sources": sources,
        "runs": runs,
        "repetition": _summary(records),
        "comparison": comparison,
        "human_calibration": "pending_independent_labels",
    }
    if any(_load(path)[2] != raw for path, raw in originals):
        raise ValueError("source changed while auditing")
    output_dir.mkdir(parents=True, exist_ok=False)
    save_json(output_dir / "summary.json", result)
    (output_dir / "repetition-records.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    )
    (output_dir / "README.md").write_text(_markdown(result))
    return result
