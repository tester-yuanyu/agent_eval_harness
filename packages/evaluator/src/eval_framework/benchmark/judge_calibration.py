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

from .judging import DIMENSIONS, JUDGE_VERSION, RUBRICS

CALIBRATION_VERSION = "judge-calibration-v1"


def _rows(source: dict | list[dict]) -> list[dict]:
    if isinstance(source, list):
        candidates = [dict(record) for record in source]
    elif "trials" in source:
        candidates = []
        for trial in source["trials"]:
            for metric in trial.get("assessment", {}).get("metrics", []):
                if metric.get("name") in DIMENSIONS:
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
            record.get("name") not in DIMENSIONS
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
        "instructions": "An independent human reviewer must inspect source "
        "evidence and rubric before entering a normalized 0..1 "
        "score, reason, annotator identity and "
        "independent=true. Do not copy model predictions. Leave "
        "unavailable evidence unlabelled. A completed worksheet "
        "alone does not validate a threshold.",
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
    human_negative = [pair for pair in pairs if not pair["human_accept"]]
    human_positive = [pair for pair in pairs if pair["human_accept"]]
    false_accept = sum(pair["judge_accept"] for pair in human_negative)
    false_reject = sum(not pair["judge_accept"] for pair in human_positive)
    return {
        "version": CALIBRATION_VERSION,
        "status": "diagnostic_agreement_only"
        if pairs
        else "awaiting_independent_human_labels",
        "threshold": threshold,
        "threshold_version": threshold_version,
        "threshold_status": "requires_independent_validation",
        "total": len(rows),
        "labeled": len(completed),
        "paired": len(pairs),
        "label_coverage": len(completed) / len(rows) if rows else None,
        "paired_coverage": len(pairs) / len(rows) if rows else None,
        "missing_label_ids": sorted(set(lookup) - set(completed)),
        "judge_unscored_ids": sorted(unscored),
        "agreement": mean(
            pair["human_accept"] == pair["judge_accept"] for pair in pairs
        )
        if pairs
        else None,
        "mean_absolute_error": mean(pair["absolute_error"] for pair in pairs)
        if pairs
        else None,
        "false_accept_count": false_accept,
        "false_reject_count": false_reject,
        "false_accept_rate": false_accept / len(human_negative)
        if human_negative
        else None,
        "false_reject_rate": false_reject / len(human_positive)
        if human_positive
        else None,
        "pairs": pairs,
        "by_dimension": {
            name: {
                "paired": len(group),
                "agreement": mean(
                    item["human_accept"] == item["judge_accept"] for item in group
                )
                if group
                else None,
                "mean_absolute_error": mean(item["absolute_error"] for item in group)
                if group
                else None,
            }
            for name in sorted({record["name"] for record in rows})
            for group in [[pair for pair in pairs if pair["name"] == name]]
        },
        "limitations": [
            "Self-declared human provenance requires reviewer audit.",
            "These labels describe agreement; threshold validation "
            "needs a separate held-out human-labeled sample.",
            "Missing Judge scores and missing human labels are not "
            "agreement or disagreement.",
        ],
    }
