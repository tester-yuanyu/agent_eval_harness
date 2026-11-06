"""只聚合可核查的用量；字段缺失、角色和延迟范围分别披露。"""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean

USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cached_tokens",
    "cost_usd",
)
ALIASES = {"input_tokens": "prompt_tokens", "output_tokens": "completion_tokens"}
FIELDS = (
    *USAGE_FIELDS,
    "tool_calls",
    "generation_calls",
    "output_characters",
    "latency_seconds",
)


def _number(value, field):
    if value is None:
        return None
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or value < 0
        or (field not in {"cost_usd", "latency_seconds"} and int(value) != value)
    ):
        raise ValueError(f"invalid nonnegative numeric usage: {field}")
    return value


def _field(usage: dict, field: str):
    alias = ALIASES.get(field, field)
    value = _number(usage.get(field, usage.get(alias)), field)
    if alias != field and alias in usage and field in usage:
        other = _number(usage[alias], field)
        if value != other:
            raise ValueError(f"conflicting usage aliases: {field}")
    return value


def _owner(event):
    if event.get("is_judge") is True:
        return "judge"
    if event.get("is_user_simulator") is True or event.get("owner") == "user_simulator":
        return "user_simulator"
    return "agent"


def _measure(row: dict, owner: str) -> dict:
    record = row["record"]
    empty = dict.fromkeys(FIELDS)
    if record is None:
        return empty
    observation = record["observation"]
    events = observation.get("events")
    complete = observation.get("evidence_complete") is True and isinstance(events, list)
    events = events if isinstance(events, list) else []
    seen = set()
    for event in events:
        if event.get("id") is not None:
            if event["id"] in seen:
                raise ValueError("duplicate event identity in usage evidence")
            seen.add(event["id"])
    calls = [e for e in events if e.get("type") == "generation" and _owner(e) == owner]
    usage = observation.get("usage") or {}
    if not isinstance(usage, dict):
        raise ValueError("usage must be an object")
    foreign = any(
        e.get("type") == "generation" and _owner(e) != "agent" for e in events
    )
    aggregate = owner == "agent" and (
        not foreign or observation.get("usage_scope") == "agent"
    )
    for field in USAGE_FIELDS:
        if aggregate and usage:
            empty[field] = _field(usage, field)
        else:
            values = [_field(e.get("usage") or {}, field) for e in calls]
            # 缺失字段不能由 token 别名之外的字段推导；零调用只由完整事件证明。
            empty[field] = (
                sum(values) if complete and all(v is not None for v in values) else None
            )
    empty["generation_calls"] = len(calls) if complete else None
    empty["tool_calls"] = (
        sum(e.get("type") == "tool" and _owner(e) == owner for e in events)
        if complete
        else None
    )
    if owner == "agent":
        empty["latency_seconds"] = _number(
            record.get("latency_seconds"), "latency_seconds"
        )
        turns = observation.get("turns", [])
        if turns and isinstance(turns[-1].get("output"), str):
            empty["output_characters"] = len(turns[-1]["output"])
    return empty


def _summary(rows, values):
    known = [value for value in values if value is not None]
    successful = [
        v for r, v in zip(rows, values, strict=True) if r["verdict"] == "PASS"
    ]
    success_known = [v for v in successful if v is not None]
    valid_known = [
        v
        for r, v in zip(rows, values, strict=True)
        if r["verdict"] not in {"INVALID", "MISSING"} and v is not None
    ]
    cases = defaultdict(list)
    for row, value in zip(rows, values, strict=True):
        cases[row["case_id"]].append(value)
    complete = len(known) == len(rows) and all(r["verdict"] != "MISSING" for r in rows)
    return {
        "known_subtotal": sum(known) if known else None,
        "total": sum(known) if rows and complete else None,
        "known_count": len(known),
        "planned_count": len(rows),
        "mean_known": mean(known) if known else None,
        "valid_mean_known": mean(valid_known) if valid_known else None,
        "successful_mean": mean(success_known)
        if successful and len(success_known) == len(successful)
        else None,
        "per_success": sum(known) / len(successful)
        if successful and complete
        else None,
        "per_success_status": "available"
        if successful and complete
        else "zero_success"
        if not successful
        else "incomplete_usage_or_population",
        "coverage": {
            "known_trials": len(known),
            "planned_trials": len(rows),
            "complete_tasks": sum(
                all(v is not None for v in group) for group in cases.values()
            ),
            "planned_tasks": len(cases),
        },
    }


def efficiency(population: dict) -> dict:
    by_layer = {}
    judge = {(r["case_id"], r["trial"]): r for r in population.get("judge_trials", [])}
    for layer in sorted({r["layer"] for r in population["trials"]}):
        rows = [r for r in population["trials"] if r["layer"] == layer]
        owners = {
            "agent": rows,
            "judge": [
                {**r, "record": judge[r["case_id"], r["trial"]]}
                for r in rows
                if (r["case_id"], r["trial"]) in judge
            ],
            "user_simulator": [
                r
                for r in rows
                if r["record"]
                and any(
                    _owner(e) == "user_simulator"
                    for e in r["record"]["observation"].get("events", [])
                )
            ],
        }
        result = {}
        for owner, group in owners.items():
            measurements = [_measure(r, owner) for r in group]
            result[owner] = {
                field: _summary(group, [m[field] for m in measurements])
                for field in FIELDS
            }
            latency_scopes = defaultdict(list)
            for r, m in zip(group, measurements, strict=True):
                raw = (r["record"] or {}).get("latency_scope", "legacy_trial_elapsed")
                scope = (
                    raw
                    if raw
                    in {"legacy_trial_elapsed", "trial_elapsed", "agent_execution"}
                    else "unknown"
                )
                latency_scopes[scope].append((r, m["latency_seconds"]))
            result[owner]["latency_by_scope"] = {
                scope: _summary([r for r, _ in pairs], [v for _, v in pairs])
                for scope, pairs in latency_scopes.items()
            }
            if len(latency_scopes) > 1:
                result[owner]["latency_seconds"] = {
                    "status": "mixed_scopes",
                    "by_scope": result[owner]["latency_by_scope"],
                }
        by_layer[layer] = result
    return {
        "by_layer": by_layer,
        "verbosity_definition": "final visible response characters; descriptive only",
    }
