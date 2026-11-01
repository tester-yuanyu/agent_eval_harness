"""Independent human-label worksheets and honest Judge agreement diagnostics.

Blank labels are never populated by an LLM or copied from Judge predictions.
A threshold fitted or inspected on these labels still needs independent validation.
"""

from __future__ import annotations

import hashlib
import json
import math
from statistics import mean
from typing import Any

from .judging import GEVAL_DIMENSIONS, JUDGE_VERSION, RUBRICS

CALIBRATION_VERSION = "judge-calibration-v1"
RUBRIC_READING_ZH = {
    "action_appropriateness": {
        "criteria": (
            "仅依据动作发生前已有的证据，评价该可观察动作与当前请求的相关性、工具及参数选择的依据，"
            "以及是否遵守已知约束。允许等价的有效路径；不推测隐藏推理，也不因决策时尚不可知的后续结果扣分。"
        ),
        "anchors": [
            [0, 2, "动作违背请求或明确约束；选择缺乏依据或会造成损害。"],
            [3, 5, "部分相关，但忽略了重要的已有证据或前置条件。"],
            [6, 8, "动作合理，但存在有限且可避免的不足或低效。"],
            [9, 10, "依据充分，在已知约束内推进请求或准确结束任务。"],
        ],
    },
    "recovery_appropriateness": {
        "criteria": (
            "结合记录中的工具或 Provider 失败及随后可观察的动作或回复，"
            "评价 Agent 是否依据错误证据修正方案、请求必要澄清或如实报告阻碍。"
            "未经合理调整而重复失败动作不属于成功恢复；评价恢复决策，不评价尚未观察到的后续结果。"
        ),
        "anchors": [
            [0, 2, "忽略失败、虚假宣称成功，或无正当理由重复同一失败动作。"],
            [3, 5, "承认失败，但下一动作没有处理已说明的原因。"],
            [6, 8, "修正动作合理或如实停止，但仍有有限遗漏。"],
            [9, 10, "处理可观察到的原因，或清楚说明必要阻碍，且没有无依据的断言。"],
        ],
    },
    "response_groundedness": {
        "criteria": (
            "将本轮公开回复与本轮工具结果及轮次结束时的工作区快照比较，评价检索、修改和完成声明是否有事实支持，"
            "以及是否如实说明限制。不使用未来轮次证据，也不要求特定写作风格；"
            "即使任务失败，如实报告失败仍可具有充分事实依据。"
        ),
        "anchors": [
            [0, 2, "核心事实或完成声明与记录证据冲突，或完全缺乏依据。"],
            [3, 5, "部分声明有依据，但重要声明缺乏支持，或隐瞒失败。"],
            [6, 8, "主要声明有依据，但仍有有限的不精确表述或未说明的限制。"],
            [9, 10, "所有重要声明均有依据，并准确说明失败或限制。"],
        ],
    },
}


def _rows(source: dict | list[dict]) -> list[dict]:
    if isinstance(source, list):
        candidates = [dict(record) for record in source]
    elif "trials" in source:
        candidates = []
        for trial in source["trials"]:
            for metric in trial.get("assessment", {}).get("metrics", []):
                if metric.get("name") in GEVAL_DIMENSIONS:
                    candidates.append(
                        {
                            **metric,
                            "run_id": source.get("run_id"),
                            "case_id": trial["case_id"],
                            "trial": trial["trial"],
                        }
                    )
    else:
        raise ValueError("Expected a benchmark run or a list of saved Judge metrics")
    result, seen = [], set()
    for record in candidates:
        # Repeated judgments share evidence; annotate it independently once.
        # Stability compares all repeats separately without duplicate human rows.
        if record.get("judge_repeat", 1) != 1:
            continue
        if (
            record.get("name") not in GEVAL_DIMENSIONS
            or record.get("status") == "NOT_APPLICABLE"
        ):
            continue
        if not record.get("metric_id"):
            raise ValueError("Judge calibration requires stable metric_id")
        identity = (
            record.get("record_id")
            or hashlib.sha256(
                json.dumps(
                    [
                        record.get("run_id"),
                        record.get("case_id"),
                        record.get("trial"),
                        record["metric_id"],
                    ]
                ).encode()
            ).hexdigest()[:32]
        )
        if identity in seen:
            raise ValueError("Duplicate Judge calibration record identity")
        seen.add(identity)
        result.append({**record, "record_id": identity})
    return result


def create_calibration_worksheet(source: dict | list[dict]) -> dict[str, Any]:
    """Produce blank annotation rows, omitting Judge scores/reasons to limit anchoring.

    Evidence prompts contain the scored observation and rubric, but no completed
    Judge output. Original traces remain the authoritative review material.
    """
    rows = []
    for record in _rows(source):
        rows.append(
            {
                **{
                    key: record.get(key)
                    for key in (
                        "record_id",
                        "metric_id",
                        "name",
                        "version",
                        "run_id",
                        "case_id",
                        "trial",
                        "scope",
                        "event_id",
                        "evidence_ids",
                    )
                },
                "rubric": RUBRICS[record["name"]],
                "rubric_zh": RUBRIC_READING_ZH[record["name"]],
                "evidence_prompts": [
                    event["input"]
                    for event in record.get("events", [])
                    if event.get("input")
                ],
                "human_score": None,
                "human_reason": None,
                "annotator": None,
                "annotation_source": "human",
                "independent": None,
            }
        )
    return {
        "version": CALIBRATION_VERSION,
        "judge_version": JUDGE_VERSION,
        "status": "awaiting_independent_human_labels",
        "instructions": "请由独立人工评审先阅读原始证据和评分规则，再填写 0～1 分数、"
        "评分理由、标注者身份，并将 independent 设为 true。不要抄录模型预测；"
        "证据不足时保留空白。完成标注表本身不代表通过阈值已验证。"
        "原始评分规则与证据保留评测时的语言，中文对照仅辅助阅读。",
        "rubric_reading_note": (
            "rubric_zh 为原始 rubric 的中文阅读对照，不进入 Judge 调用。"
            "锚点使用 0～10 描述，人工分数填写为对应的 0～1 尺度。"
        ),
        "rows": rows,
    }


def _score(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def compare_human_labels(
    source: dict | list[dict],
    labels: list[dict] | dict,
    *,
    threshold: float,
    threshold_version: str,
) -> dict[str, Any]:
    """Strictly join independent annotations; report missing/unscored rows explicitly.

    ``threshold`` is an explicitly named candidate used to describe agreement,
    never an automatic promotion to formal grading or calibrated=true.
    """
    if (
        not _score(threshold)
        or not isinstance(threshold_version, str)
        or not threshold_version.strip()
    ):
        raise ValueError(
            "A normalized threshold and nonempty threshold_version are required"
        )
    rows = _rows(source)
    lookup = {row["record_id"]: row for row in rows}
    annotations = labels["rows"] if isinstance(labels, dict) else labels
    completed, seen = {}, set()
    for annotation in annotations:
        identity = annotation.get("record_id")
        if identity not in lookup or identity in seen:
            raise ValueError("Unknown or duplicate human-label record_id")
        seen.add(identity)
        score = annotation.get("human_score")
        if score is None:
            continue
        if (
            not _score(score)
            or annotation.get("annotation_source") != "human"
            or annotation.get("independent") is not True
            or not isinstance(annotation.get("annotator"), str)
            or not annotation["annotator"].strip()
        ):
            raise ValueError(
                "Completed labels need normalized scores and "
                "independent human provenance"
            )
        completed[identity] = annotation
    pairs, unscored = [], []
    for identity, annotation in completed.items():
        record = lookup[identity]
        if record.get("status") != "SCORED" or not _score(record.get("score")):
            unscored.append(identity)
            continue
        human = annotation["human_score"]
        judge = record["score"]
        pairs.append(
            {
                "record_id": identity,
                "name": record["name"],
                "human_score": human,
                "judge_score": judge,
                "human_accept": human >= threshold,
                "judge_accept": judge >= threshold,
                "absolute_error": abs(human - judge),
            }
        )

    def statistics(group_rows: list[dict], group_pairs: list[dict]) -> dict:
        identities = {row["record_id"] for row in group_rows}
        labeled = identities & completed.keys()
        negative = [pair for pair in group_pairs if not pair["human_accept"]]
        positive = [pair for pair in group_pairs if pair["human_accept"]]
        false_accept = sum(pair["judge_accept"] for pair in negative)
        false_reject = sum(not pair["judge_accept"] for pair in positive)
        return {
            "total": len(group_rows),
            "labeled": len(labeled),
            "paired": len(group_pairs),
            "label_coverage": len(labeled) / len(group_rows) if group_rows else None,
            "paired_coverage": len(group_pairs) / len(group_rows)
            if group_rows
            else None,
            "missing_label_ids": sorted(identities - completed.keys()),
            "judge_unscored_ids": sorted(identities & set(unscored)),
            "human_negative": len(negative),
            "human_positive": len(positive),
            "agreement": mean(
                pair["human_accept"] == pair["judge_accept"] for pair in group_pairs
            )
            if group_pairs
            else None,
            "mean_absolute_error": mean(pair["absolute_error"] for pair in group_pairs)
            if group_pairs
            else None,
            "false_accept_count": false_accept,
            "false_reject_count": false_reject,
            "false_accept_rate": false_accept / len(negative) if negative else None,
            "false_reject_rate": false_reject / len(positive) if positive else None,
            "confusion_matrix": {
                "true_accept": len(positive) - false_reject,
                "false_accept": false_accept,
                "true_reject": len(negative) - false_accept,
                "false_reject": false_reject,
            },
        }

    def digest(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                # Preserve legacy unscored handling for nonfinite Judge values.
                allow_nan=True,
            ).encode("utf-8")
        ).hexdigest()

    disagreements = []
    for pair in pairs:
        if pair["human_accept"] == pair["judge_accept"]:
            continue
        record = lookup[pair["record_id"]]
        disagreements.append(
            {
                **pair,
                "classification": "false_accept"
                if pair["judge_accept"]
                else "false_reject",
                **{
                    key: record.get(key)
                    for key in (
                        "metric_id",
                        "run_id",
                        "case_id",
                        "trial",
                        "event_id",
                        "evidence_ids",
                    )
                },
                "human_reason": completed[pair["record_id"]].get("human_reason"),
                "judge_reason": record.get("reason"),
            }
        )
    return {
        "version": CALIBRATION_VERSION,
        "status": "diagnostic_agreement_only"
        if completed
        else "awaiting_independent_human_labels",
        "threshold": threshold,
        "threshold_version": threshold_version,
        "threshold_status": "requires_independent_validation",
        **statistics(rows, pairs),
        "pairs": pairs,
        "by_dimension": {
            name: statistics(
                [record for record in rows if record["name"] == name],
                [pair for pair in pairs if pair["name"] == name],
            )
            for name in sorted({record["name"] for record in rows})
        },
        "disagreements": disagreements,
        "source_summary": {
            "sha256": digest(source),
            "hash_encoding": (
                "utf-8 Python JSON; ensure_ascii=false; sort_keys=true; "
                "compact; allow_nan=true"
            ),
            "population_count": len(rows),
            "record_ids": sorted(lookup),
            "run_id": source.get("run_id") if isinstance(source, dict) else None,
        },
        "labels_summary": {
            "sha256": digest(labels),
            "hash_encoding": (
                "utf-8 Python JSON; ensure_ascii=false; sort_keys=true; "
                "compact; allow_nan=true"
            ),
            "submitted_count": len(annotations),
            "completed_count": len(completed),
            "completed_record_ids": sorted(completed),
            "annotators": sorted({row["annotator"] for row in completed.values()}),
            "provenance_status": "self_declared_requires_review",
        },
        "limitations": [
            "人工标注来源由填写者声明，仍需审核标注者身份与独立性。",
            "这些标签用于描述一致性；阈值验证还需另设独立留出的人工标注样本。",
            "缺失的 Judge 分数或人工标签均不计为一致或不一致。",
        ],
    }
