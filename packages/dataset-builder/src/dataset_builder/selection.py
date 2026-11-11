"""Offline sidecar selection over existing generation plans; never execute cases."""

from __future__ import annotations

import hashlib
import json
from itertools import combinations
from pathlib import Path

from .full_generation.models import GenerationResult

FACTORS = {"target", "layer", "dimension", "execution_category"}


def _pairs(factors):
    return {tuple(pair) for pair in combinations(sorted(factors.items()), 2)}


def _encode(pairs):
    return [[list(item) for item in pair] for pair in sorted(pairs)]


def _case(case, slot):
    payload = case.payload
    operation = payload.get("input", {}).get("operation")
    if case.execution_readiness == "blocked":
        category = "blocked_obligation"
    elif operation == "inspect_declared_constraint":
        category = "static_contract"
    elif payload.get("test_scope") in {"module", "link", "end_to_end"}:
        category = "agent_behavior"
    elif operation == "agent_run":
        category = "agent_behavior"
    elif operation in {"invoke_tool", "idempotency_sequence", "authorization_sequence"}:
        category = "tool_behavior"
    elif operation in {"validate_arguments", "validate_selection_modes"}:
        category = "schema_validation"
    else:
        category = "unknown"
    # Invoking an Agent/tool does not prove that its bound provider uses a model.
    uses_model = (
        False if category in {"static_contract", "schema_validation"} else "unknown"
    )
    fault = payload.get("input", {}).get(
        "controlled_fault",
        payload.get("execution", {}).get("fault_injection", "unknown"),
    )
    return {
        "case_id": payload["case_id"],
        "obligation_ids": [case.slot_id],
        "execution_category": category,
        "uses_model": uses_model,
        "public_fault": fault,
        "execution_readiness": case.execution_readiness,
        "coverage_mode": case.coverage_mode,
        "blocker_ids": case.blocker_ids,
        "factors": {
            "target": slot.target_id,
            "layer": slot.layer,
            "dimension": slot.dimension,
            "execution_category": category,
        },
    }


def select_cases(
    generation: GenerationResult,
    *,
    mode="quick",
    max_cases=None,
    max_model_cases=None,
    forbidden=None,
    evidence=None,
) -> dict:
    """Select feasible existing rows; top-up excludes all valid saved results.

    Pair denominator is the union present in nonblocked, constraint-legal existing
    candidates, not a Cartesian product or a claim of global capability coverage.
    Evidence reports coverage explicitly; success/failure alone earns no coverage.
    """
    if mode not in {"quick", "full"}:
        raise ValueError("mode must be quick or full")
    for value in (max_cases, max_model_cases):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("budgets must be nonnegative integers")
    forbidden = forbidden or []
    for clause in forbidden:
        if not isinstance(clause, dict) or not clause or not set(clause) <= FACTORS:
            raise ValueError("forbidden constraints require known factor names")
        if any(not isinstance(v, str) for v in clause.values()):
            raise ValueError("factor values must be strings")
    source_hash = hashlib.sha256(
        json.dumps(
            generation.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    slots = {slot.slot_id: slot for slot in generation.slots}
    if len(slots) != len(generation.slots):
        raise ValueError("duplicate obligation ids")
    rows = []
    for case in generation.cases:
        if case.slot_id not in slots:
            raise ValueError("case references unknown obligation")
        rows.append(_case(case, slots[case.slot_id]))
    rows.sort(key=lambda c: c["case_id"])
    index = {row["case_id"]: row for row in rows}
    if len(index) != len(rows):
        raise ValueError("duplicate case ids")
    eligible = {}
    for row in rows:
        reasons = []
        if row["execution_readiness"] == "blocked":
            reasons.append("blocked_obligation")
        if any(
            all(row["factors"][k] == v for k, v in clause.items())
            for clause in forbidden
        ):
            reasons.append("forbidden_combination")
        row["exclusion_reasons"] = reasons
        if not reasons:
            eligible[row["case_id"]] = _pairs(row["factors"])
    universe = set().union(*eligible.values()) if eligible else set()
    measured_pairs, measured_slots, completed = set(), set(), set()
    if evidence is not None:
        if evidence.get("source_sha256") != source_hash:
            raise ValueError("evidence source hash mismatch")
        seen = set()
        for observed in evidence.get("observations", []):
            ident = observed["case_id"]
            if ident not in index or ident in seen:
                raise ValueError("unknown or duplicate observed case")
            seen.add(ident)
            row = index[ident]
            factors = observed.get("observed_factors", {})
            if any(
                k not in row["factors"] or row["factors"][k] != v
                for k, v in factors.items()
            ):
                raise ValueError("observed factors disagree with candidate")
            covered = set(observed.get("covered_obligation_ids", []))
            if not covered <= set(row["obligation_ids"]):
                raise ValueError("observed coverage exceeds candidate obligations")
            valid = observed.get("valid_result")
            if type(valid) is not bool:
                raise ValueError("valid_result must be boolean")
            if valid:
                completed.add(ident)
                if ident in eligible:
                    measured_pairs |= _pairs(factors)
                    measured_slots |= covered
    limit = (
        max_cases if max_cases is not None else (20 if mode == "quick" else len(rows))
    )
    remaining = set(eligible) - completed
    selected, selected_pairs, selected_slots = [], set(), set()
    model_count = 0
    while remaining and len(selected) < limit:
        allowed = [
            ident
            for ident in remaining
            if max_model_cases is None
            or model_count + (index[ident]["uses_model"] is not False)
            <= max_model_cases
        ]
        if not allowed:
            break
        ident = min(
            allowed,
            key=lambda key: (
                -len(eligible[key] - measured_pairs - selected_pairs),
                -len(
                    set(index[key]["obligation_ids"]) - measured_slots - selected_slots
                ),
                key,
            ),
        )
        if (
            evidence is not None
            and not (eligible[ident] - measured_pairs - selected_pairs)
            and not (
                set(index[ident]["obligation_ids"]) - measured_slots - selected_slots
            )
        ):
            break
        selected.append(ident)
        selected_pairs |= eligible[ident]
        selected_slots.update(index[ident]["obligation_ids"])
        model_count += index[ident]["uses_model"] is not False
        remaining.remove(ident)
    available_pairs = set().union(*(eligible[k] for k in set(eligible) - completed))
    return {
        "selection_version": "1.0",
        "source_sha256": source_hash,
        "mode": mode,
        "scope": "existing_generation_candidates_only",
        "execution_performed": False,
        "budget": {
            "max_cases": limit,
            "max_model_cases": max_model_cases,
            "unknown_model_charged": True,
        },
        "forbidden": forbidden,
        "obligation_count": len(slots),
        "obligations": [s.model_dump(mode="json") for s in generation.slots],
        "cases": rows,
        "selected_case_ids": selected,
        "preserved_valid_case_ids": sorted(completed),
        "selected_model_or_unknown_count": model_count,
        "unselected_obligation_ids": sorted(set(slots) - selected_slots),
        "measured_obligation_ids": sorted(measured_slots),
        "measured_obligation_gaps": sorted(set(slots) - measured_slots),
        "candidate_pair_count": len(universe),
        "candidate_pairs": _encode(universe),
        "selected_pair_count": len(selected_pairs),
        "measured_pair_count": len(measured_pairs),
        "measured_pairs": _encode(measured_pairs),
        "measured_pair_gaps": _encode(universe - measured_pairs),
        "planned_pair_gaps": _encode(universe - measured_pairs - selected_pairs),
        "unfillable_pair_gaps": _encode(universe - measured_pairs - available_pairs),
        "coverage_note": (
            "Selection is planned coverage, never execution or PASS evidence."
        ),
    }


def write_selection(source: Path, output: Path, **kwargs) -> dict:
    """Read a generation plan and create a new, non-overwriting sidecar."""
    raw = source.read_bytes()
    result = select_cases(GenerationResult.model_validate_json(raw), **kwargs)
    result["source_file_sha256"] = hashlib.sha256(raw).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result
