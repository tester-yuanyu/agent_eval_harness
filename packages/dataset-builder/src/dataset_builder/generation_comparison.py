"""Controlled slot-generation experiments, independent of publication/freeze."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .coverage import _normalized
from .deepeval_generation import DeepEvalGenerationClient, build_slot_task
from .scenario_requirements import (
    candidate_issues,
    check_requirement,
    load_requirements,
)
from .source_pack import sha256_bytes


@dataclass
class GeneratedSample:
    input: str
    expected_output: str | None
    context: list[str]
    additional_metadata: dict[str, Any]


class DirectSlotSynthesizer:
    """One JSON completion per attempt, without SDK synthesis stages."""

    def __init__(self, complete: Callable):
        self.complete = complete

    def generate(self, context: str, slot: dict, schema: str) -> list[GeneratedSample]:
        task = build_slot_task(slot)
        input_only = bool(slot.get("acceptance", {}).get("oracle_gaps"))
        output = (
            "Return ONLY JSON with exactly one field: "
            '{"input": "Chinese user request"}. '
            "Do not return any oracle or expected output."
            if input_only
            else "Return ONLY a complete Candidate JSON matching this schema: "
            + schema
            + ". Generate user_input and independently derive expected fields "
            "from that "
            "input and the supplied contract. Match the planned slot, intent, status, "
            "scenario_type and rule_refs exactly. "
            "Never guess missing contract outcomes."
        )
        prompt = context + "\n\n" + task + "\n\n" + output
        raw, _ = self.complete(prompt, json_mode=True)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("direct response must be a JSON object")
        if input_only:
            if set(payload) != {"input"} or not isinstance(payload["input"], str):
                raise ValueError("input-only response must contain only a string input")
            user_input = payload["input"]
        else:
            user_input = payload.get("user_input")
            if not isinstance(user_input, str):
                raise ValueError("Candidate user_input must be a string")
        return [
            GeneratedSample(
                user_input,
                None if input_only else raw,
                [context, task],
                {"direct_raw_output": raw},
            )
        ]


def _sample_dict(sample) -> dict:
    if isinstance(sample, GeneratedSample):
        return asdict(sample)
    return {
        name: getattr(sample, name)
        for name in ("input", "expected_output", "context", "additional_metadata")
    }


def validate_sample(
    sample: dict, slot: dict, suite, requirements, accepted_inputs
) -> list[str]:
    text = sample.get("input")
    if not isinstance(text, str) or not text.strip():
        return ["input must be a nonempty string"]
    normalized = _normalized(text)
    if normalized in accepted_inputs:
        return [
            "duplicate input after normalization: "
            + json.dumps(text, ensure_ascii=False)
        ]
    requirement = requirements.get(slot["slot_id"])
    if requirement and requirement.oracle_gaps:
        if sample.get("expected_output") is not None:
            return ["contract-gap slot must not have an oracle"]
        return check_requirement(text, None, requirement)
    raw = sample.get("expected_output")
    try:
        if not isinstance(raw, str):
            raise ValueError("expected_output must be explicit Candidate JSON")
        candidate = json.loads(raw)
        errors = list(
            Draft202012Validator(suite.candidate_type.model_json_schema()).iter_errors(
                candidate
            )
        )
        if errors:
            return [errors[0].message]
        if candidate["user_input"] != text:
            return ["Candidate user_input differs from generated input"]
        return candidate_issues(candidate, suite, slot)
    except ValueError as exc:
        return [str(exc)]


def run_arm(
    suite,
    request,
    synthesize: Callable,
    output_dir: Path,
    *,
    max_slot_attempts: int = 3,
    on_attempt: Callable | None = None,
) -> dict:
    """Same loop for both arms; never hide an exhausted slot or fabricate an oracle."""
    if type(max_slot_attempts) is not int or not 1 <= max_slot_attempts <= 10:
        raise ValueError("max_slot_attempts must be an integer in [1,10]")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_path = output_dir / "attempts.jsonl"
    if audit_path.exists() or (output_dir / "arm_result.json").exists():
        raise FileExistsError("comparison arm already has results")
    context = DeepEvalGenerationClient(suite=suite, model="preflight-only")._context(
        request
    )
    requirements = load_requirements(suite)
    slots = suite.coverage_plan["slots"]
    if not slots or len({s["slot_id"] for s in slots}) != len(slots):
        raise ValueError("planned slots must be nonempty and unique")
    schema = json.dumps(suite.candidate_type.model_json_schema(), ensure_ascii=False)
    accepted, failed, attempts = [], [], []
    accepted_inputs = set()
    started = time.monotonic()
    with audit_path.open("x") as stream:
        for slot in slots:
            sid = slot["slot_id"]
            input_only = bool(slot.get("acceptance", {}).get("oracle_gaps"))
            diagnostics = []
            for attempt in range(1, max_slot_attempts + 1):
                attempt_context = context
                if diagnostics:
                    attempt_context += (
                        "\nREJECTED_ATTEMPT_DIAGNOSTICS (validation data):\n"
                        + json.dumps(diagnostics, ensure_ascii=False)
                    )
                    attempt_context += (
                        "\nGenerate a fresh input; preserve the slot constraints. "
                        "Do not copy or patch a prior answer."
                    )
                if on_attempt:
                    on_attempt(sid, attempt)
                record = {
                    "slot_id": sid,
                    "attempt": attempt,
                    "input_only": input_only,
                    "context_sha256": sha256_bytes(attempt_context.encode()),
                    "samples": [],
                    "issues": [],
                    "feedback": list(diagnostics),
                    "failure_stage": None,
                }
                call_start = time.monotonic()
                try:
                    samples = synthesize(attempt_context, slot, schema)
                    record["samples"] = [_sample_dict(s) for s in samples]
                except Exception as exc:
                    record["failure_stage"] = "generation"
                    diagnostics = [f"{type(exc).__name__}: {exc}"]
                else:
                    if len(samples) != 1:
                        diagnostics = ["expected exactly one generated sample"]
                    else:
                        diagnostics = validate_sample(
                            record["samples"][0],
                            slot,
                            suite,
                            requirements,
                            accepted_inputs,
                        )
                    if diagnostics:
                        record["failure_stage"] = "acceptance"
                record["issues"] = list(diagnostics)
                record["elapsed_seconds"] = time.monotonic() - call_start
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                attempts.append(record)
                if not diagnostics:
                    chosen = record["samples"][0]
                    accepted.append(
                        {
                            "slot_id": sid,
                            "input_only": input_only,
                            "sample": chosen,
                            "accepted_attempt": attempt,
                        }
                    )
                    accepted_inputs.add(_normalized(chosen["input"]))
                    break
            else:
                failed.append({"slot_id": sid, "issues": list(diagnostics)})
    result = {
        "planned_slots": len(slots),
        "planned_oracles": sum(
            not s.get("acceptance", {}).get("oracle_gaps") for s in slots
        ),
        "accepted": accepted,
        "failed_slots": failed,
        "attempts": attempts,
        "rejected_attempts": [a for a in attempts if a["issues"]],
        "elapsed_seconds": time.monotonic() - started,
        "bindings": {
            "source_manifest": request.source_manifest,
            "policy_bindings": request.policy_bindings,
            "capability_ir_binding": request.capability_ir_binding,
            "coverage_plan_sha256": request.coverage_plan_sha256,
            "candidate_schema_sha256": sha256_bytes(schema.encode()),
            "context_sha256": sha256_bytes(context.encode()),
        },
        "max_slot_attempts": max_slot_attempts,
        "publication_status": "NOT_APPROVED",
    }
    (output_dir / "arm_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    return result


def summarize_arm(result: dict) -> dict:
    first = [a for a in result["attempts"] if a["attempt"] == 1]
    passed = [a for a in first if not a["issues"]]
    texts = [x["sample"]["input"] for x in result["accepted"]]
    normalized = [_normalized(x) for x in texts]
    return {
        "planned_slots": result["planned_slots"],
        "planned_oracles": result["planned_oracles"],
        "first_pass_count": len(passed),
        "first_pass_rate": len(passed) / result["planned_slots"],
        "first_pass_oracles": sum(not a["input_only"] for a in passed),
        "first_pass_input_only": sum(a["input_only"] for a in passed),
        "attempt_count": len(result["attempts"]),
        "rejected_attempt_count": len(result["rejected_attempts"]),
        "rejected_duplicate_attempt_count": sum(
            any(issue.startswith("duplicate input") for issue in a["issues"])
            for a in result["rejected_attempts"]
        ),
        "accepted_oracles": sum(not x["input_only"] for x in result["accepted"]),
        "accepted_input_only": sum(x["input_only"] for x in result["accepted"]),
        "exhausted_slots": len(result["failed_slots"]),
        "exact_duplicates": len(texts) - len(set(texts)),
        "normalized_duplicates": len(texts) - len(set(normalized)),
        "common_prefix_count": sum(x.startswith("帮我查一下") for x in texts),
        "elapsed_seconds": result["elapsed_seconds"],
    }
