"""Strict parsing with no repair or prose extraction."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from .schemas import RawGeneration
from .suite_definition import SuiteDefinition


def _payload(raw: Any) -> Any:
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def parse_candidates(
    suite: SuiteDefinition, raw: RawGeneration
) -> BaseModel:
    if raw.prompt_version != suite.prompt_version:
        raise ValueError("raw generation prompt version does not match suite")
    batch = suite.batch_type.model_validate(_payload(raw.response))
    slots = [item.slot_id for item in batch.candidates]
    expected = [item["slot_id"] for item in suite.coverage_plan["slots"]]
    if len(slots) != len(set(slots)):
        raise ValueError("candidate slot_id values must be unique")
    if set(slots) != set(expected):
        missing = sorted(set(expected) - set(slots))
        extra = sorted(set(slots) - set(expected))
        raise ValueError(f"slot mismatch: missing={missing}, extra={extra}")
    planned_by_slot = {
        item["slot_id"]: item for item in suite.coverage_plan["slots"]
    }
    for item in batch.candidates:
        planned = planned_by_slot[item.slot_id]
        if item.expected_intent != planned["intent"]:
            raise ValueError(
                f"slot {item.slot_id} intent must be {planned['intent']}"
            )
        if item.expected_status != planned["status"]:
            raise ValueError(
                f"slot {item.slot_id} status must be {planned['status']}"
            )
        planned_rule_refs = planned.get("rule_refs")
        if planned_rule_refs is not None and (
            getattr(item, "rule_refs", None) != planned_rule_refs
        ):
            raise ValueError(
                f"slot {item.slot_id} rule_refs must match coverage plan"
            )
        value = json.loads(item.expected_parameters_json)
        if not isinstance(value, dict):
            raise ValueError(f"{item.slot_id}: parameters JSON must be an object")
    return batch
