"""已有运行与报表汇总的兼容实现；不重评分，不补造未知用量。

两个入口保留各自历史字段、缺省分组及 alias 取值规则，避免迁移改写
冻结结果和调用方期待的 JSON 结构。
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict


def summarize(records: list[dict], case_ids: list[str], repeats: int) -> dict:
    counts = Counter(r["assessment"]["verdict"] for r in records)
    valid = sum(r["assessment"]["validity"] == "VALID" for r in records)
    planned = len(case_ids) * repeats
    by_case = defaultdict(list)
    for record in records:
        by_case[record["case_id"]].append(record)
    all_pass = sum(
        len(by_case[c]) == repeats
        and all(r["assessment"]["verdict"] == "PASS" for r in by_case[c])
        for c in case_ids
    )
    latencies = sorted(r["latency_seconds"] for r in records)
    usage_records = [r["observation"].get("usage", {}) for r in records]
    usage = {}
    for key in ("input_tokens", "output_tokens", "total_tokens", "cost_usd"):
        alias = {
            "input_tokens": "prompt_tokens",
            "output_tokens": "completion_tokens",
        }.get(key, key)
        values = [u.get(key, u.get(alias)) for u in usage_records]
        known = [v for v in values if isinstance(v, (int, float))]
        usage[key] = sum(known) if known and len(known) == len(values) else None
        usage[key + "_known_subtotal"] = sum(known) if known else None
        usage[key + "_known_trials"] = len(known)
    result = {
        "unique_tasks": len(case_ids),
        "trials_per_case": repeats,
        "planned_trials": planned,
        "completed_trials": len(records),
        "missing_trials": planned - len(records),
        "valid_trials": valid,
        "verdicts": dict(counts),
        "pass_rate_planned": counts["PASS"] / planned if planned else None,
        "pass_rate_valid": counts["PASS"] / valid if valid else None,
        "all_trials_pass_rate": all_pass / len(case_ids) if case_ids else None,
        "all_trials_pass_definition": (
            "All k planned real trials passed; missing and invalid trials "
            "cannot prove success."
        ),
        "latency_seconds_median": statistics.median(latencies) if latencies else None,
        "latency_seconds_p95": latencies[
            min(len(latencies) - 1, int(0.95 * len(latencies)))
        ]
        if latencies
        else None,
        "usage": usage,
    }
    result["mixed_execution_populations"] = (
        len({r.get("execution_mode", "agent") for r in records}) > 1
    )
    for dimension in ("split", "category", "evaluation_level", "execution_mode"):
        groups = defaultdict(list)
        for record in records:
            fallback = "e2e" if dimension == "evaluation_level" else "agent"
            groups[record.get(dimension, fallback)].append(record)
        result["by_" + dimension] = {
            name: {
                "trials": len(rows),
                "unique_tasks": len({r["case_id"] for r in rows}),
                "verdicts": dict(Counter(r["assessment"]["verdict"] for r in rows)),
                "pass_rate_observed": sum(
                    r["assessment"]["verdict"] == "PASS" for r in rows
                )
                / len(rows),
            }
            for name, rows in sorted(groups.items())
        }
    return result


def _usage_total(rows: list[dict], aliases: tuple[str, ...]) -> dict:
    values = []
    for row in rows:
        usage = row.get("observation", {}).get("usage", {})
        value = next(
            (usage[key] for key in aliases if isinstance(usage.get(key), (int, float))),
            None,
        )
        values.append(value)
    known = [value for value in values if value is not None]
    return {
        "total": sum(known) if known and len(known) == len(rows) else None,
        "known_subtotal": sum(known) if known else None,
        "known_trials": len(known),
    }


def evidence_summary(run: dict) -> dict:
    """Aggregate saved verdicts, without rerunning a metric or an Agent."""
    rows = run["trials"]
    planned_ids = run["planned_case_ids"]
    repeats = run["trials_per_case"]
    if len(planned_ids) != len(set(planned_ids)) or repeats < 1:
        raise ValueError("invalid planned case selection")
    observed_keys = [(row["case_id"], row["trial"]) for row in rows]
    if len(observed_keys) != len(set(observed_keys)):
        raise ValueError("duplicate saved case/trial evidence")
    expected_keys = {
        (case_id, trial) for case_id in planned_ids for trial in range(1, repeats + 1)
    }
    if not set(observed_keys) <= expected_keys:
        raise ValueError("saved trial is outside the planned selection")
    counts = Counter(row["assessment"]["verdict"] for row in rows)
    valid = sum(row["assessment"].get("validity") == "VALID" for row in rows)
    planned = len(expected_keys)
    cases: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        cases[row["case_id"]].append(row)
    all_pass = sum(
        len(cases[case_id]) == repeats
        and all(row["assessment"]["verdict"] == "PASS" for row in cases[case_id])
        for case_id in planned_ids
    )
    latency = sorted(
        row["latency_seconds"]
        for row in rows
        if isinstance(row.get("latency_seconds"), (float, int))
    )
    summary = {
        "unique_tasks": len(planned_ids),
        "observed_unique_tasks": len(cases),
        "trials_per_case": repeats,
        "planned_trials": planned,
        "completed_trials": len(rows),
        "missing_trials": planned - len(rows),
        "valid_trials": valid,
        "verdicts": dict(counts),
        "all_trials_pass_tasks": all_pass,
        "latency_median": statistics.median(latency) if latency else None,
        "latency_p95": (
            latency[min(len(latency) - 1, int(0.95 * len(latency)))]
            if latency
            else None
        ),
        "usage": {
            "input_tokens": _usage_total(rows, ("input_tokens", "prompt_tokens")),
            "output_tokens": _usage_total(rows, ("output_tokens", "completion_tokens")),
            "total_tokens": _usage_total(rows, ("total_tokens",)),
            "cached_tokens": _usage_total(rows, ("cached_tokens",)),
            "cost_usd": _usage_total(rows, ("cost_usd",)),
        },
    }
    recorded_summary = run.get("summary", {})
    for field in (
        "unique_tasks",
        "trials_per_case",
        "planned_trials",
        "completed_trials",
        "missing_trials",
        "valid_trials",
        "verdicts",
    ):
        if field in recorded_summary and recorded_summary[field] != summary[field]:
            raise ValueError(f"saved summary disagrees with trial evidence: {field}")
    for dimension in ("split", "category", "evaluation_level", "execution_mode"):
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            groups[str(row.get(dimension, "unknown"))].append(row)
        summary["by_" + dimension] = {
            name: {
                "unique_tasks": len({row["case_id"] for row in group}),
                "trials": len(group),
                "verdicts": dict(
                    Counter(row["assessment"]["verdict"] for row in group)
                ),
            }
            for name, group in sorted(groups.items())
        }
    return summary
