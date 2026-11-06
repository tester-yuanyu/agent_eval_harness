"""Judge 诊断的覆盖率与重复稳定性汇总；不决定正式 verdict。"""

from collections import Counter, defaultdict
from statistics import mean, pstdev


def summarize_judgments(records: list[dict]) -> dict:
    """Coverage denominator excludes N/A; failures and budget skips remain in it."""
    counts = Counter(record.get("status", "MISSING") for record in records)
    applicable = len(records) - counts["NOT_APPLICABLE"]
    scored = [
        record["score"]
        for record in records
        if record.get("status") == "SCORED"
        and isinstance(record.get("score"), (int, float))
    ]
    distribution = {
        "0_to_lt_0.25": 0,
        "0.25_to_lt_0.5": 0,
        "0.5_to_lt_0.75": 0,
        "0.75_to_1": 0,
    }
    bins = list(distribution)
    for score in scored:
        distribution[bins[min(int(score * 4), 3)]] += 1
    summary = {
        "total": len(records),
        "applicable": applicable,
        "scored": len(scored),
        "not_applicable": counts["NOT_APPLICABLE"],
        "errors": counts["ERROR"],
        "missing": counts["MISSING"],
        "coverage": len(scored) / applicable if applicable else None,
        "mean": mean(scored) if scored else None,
        "distribution": distribution,
        "calibration": "not_calibrated",
        "score_interpretation": "rubric quality; not a probability",
    }
    groups = defaultdict(list)
    for record in records:
        groups[record["name"]].append(record)
    summary["by_dimension"] = {}
    for name, group in groups.items():
        if len(group) == len(records):
            summary["by_dimension"][name] = {
                k: v for k, v in summary.items() if k != "by_dimension"
            }
        else:
            summary["by_dimension"][name] = {
                k: v
                for k, v in summarize_judgments(group).items()
                if k != "by_dimension"
            }
    return summary


def summarize_repeated_judgments(repetitions: list[list[dict]]) -> dict:
    """Compare same evidence/metric IDs; incomplete repeats cannot imply stability."""
    grouped = defaultdict(list)
    for records in repetitions:
        seen = set()
        for record in records:
            identity = record["metric_id"]
            if identity in seen:
                raise ValueError("Duplicate metric_id within one Judge repetition")
            seen.add(identity)
            if record.get("status") == "SCORED":
                grouped[identity].append(float(record["score"]))
    items = [
        {
            "metric_id": identity,
            "repetitions": len(scores),
            "mean": mean(scores),
            "stddev": pstdev(scores),
            "range": max(scores) - min(scores),
        }
        for identity, scores in sorted(grouped.items())
        if len(scores) >= 2
    ]
    return {
        "requested_repetitions": len(repetitions),
        "matched_metrics": len(items),
        "fully_scored_metrics": sum(
            item["repetitions"] == len(repetitions) for item in items
        ),
        "mean_range": mean(item["range"] for item in items) if items else None,
        "items": items,
    }
