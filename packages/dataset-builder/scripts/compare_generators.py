"""Run an authorized Direct/DeepEval AB-BA comparison in a new workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path

os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
os.environ["DEEPEVAL_UPDATE_WARNING_OPT_IN"] = "0"

import httpx
from deepeval.models import DeepSeekModel
from dotenv import dotenv_values
from jsonschema import Draft202012Validator

from dataset_builder.comparison_provider import ControlledProvider, usage_summary
from dataset_builder.coverage import duplicate_gate
from dataset_builder.deepeval_generation import DeepEvalGenerationClient
from dataset_builder.generation_comparison import (
    DirectSlotSynthesizer,
    run_arm,
    summarize_arm,
)
from dataset_builder.intent_compiler import compile_intent_candidates
from dataset_builder.intent_validation import validate_module_intent_contract
from dataset_builder.leakage import leakage_gate
from dataset_builder.pipeline import prepare_generation
from dataset_builder.scenario_requirements import scenario_issues
from dataset_builder.source_pack import sha256_file
from dataset_builder.suite_definition import load_suite
from dataset_builder.validation import quality_gate, write_jsonl

ROOT = Path(__file__).resolve().parents[1]


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def strict_sdk_value(raw, schema):
    """Validate before Pydantic can discard unknown fields, including nested ones."""
    contract = schema.model_json_schema()

    def forbid_extras(node):
        if isinstance(node, dict):
            if "properties" in node:
                node["additionalProperties"] = False
            for value in node.values():
                forbid_extras(value)
        elif isinstance(node, list):
            for value in node:
                forbid_extras(value)

    forbid_extras(contract)
    errors = list(Draft202012Validator(contract).iter_errors(json.loads(raw)))
    if errors:
        raise ValueError(errors[0].message)
    return schema.model_validate_json(raw, strict=True)


class ControlledDeepSeek(DeepSeekModel):
    """Keep Synthesizer's native model path, control every underlying API call."""

    def __init__(self, provider, key):
        self.provider = provider
        super().__init__(
            model=provider.model,
            api_key=key,
            temperature=0.4,
            cost_per_input_token=0.3 / 1e6,
            cost_per_output_token=1.2 / 1e6,
        )

    def generate(self, prompt, schema=None, audio=None):
        if audio:
            raise ValueError("text-only comparison")
        raw, cost = self.provider.complete(prompt, json_mode=schema is not None)
        return (strict_sdk_value(raw, schema) if schema else raw), cost

    async def a_generate(self, *args, **kwargs):
        raise RuntimeError("comparison must remain synchronous")


def persist_subset(suite, result, arm):
    candidates = [
        json.loads(x["sample"]["expected_output"])
        for x in result["accepted"]
        if not x["input_only"]
    ]
    blocked = [
        {
            "slot_id": x["slot_id"],
            "user_input": x["sample"]["input"],
            "oracle_status": "ABSENT_CONTRACT_GAP",
        }
        for x in result["accepted"]
        if x["input_only"]
    ]
    save(arm / "supported_candidates.json", {"candidates": candidates})
    save(arm / "blocked_inputs.json", {"slots": blocked})
    batch = suite.batch_type.model_validate({"candidates": candidates})
    cases = compile_intent_candidates(batch.candidates, suite, allow_partial=True)
    write_jsonl(cases, arm / "diagnostic_supported_cases.jsonl")
    issues = validate_module_intent_contract(
        cases, suite, require_all_slots=False
    ) + scenario_issues(cases, suite)
    gates = [duplicate_gate(cases), quality_gate(cases, suite), leakage_gate(cases)]
    report = {
        "scope": "accepted subset only; not full publication validation",
        "issues": issues,
        "gates": [g.model_dump(mode="json") for g in gates],
        "subset_passed": not issues and all(g.passed for g in gates),
        "full_plan_publishable": False,
        "human_approval": "PENDING",
    }
    save(arm / "subset_validation.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    workspace = args.workspace or ROOT / "workspaces" / (
        "generator_comparison_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    workspace = workspace.resolve()
    if workspace.exists():
        raise FileExistsError("comparison requires a new workspace")
    history = {}
    for folder in ("suites", "workspaces"):
        for p in (ROOT / folder).rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                history[str(p.relative_to(ROOT))] = sha256_file(p)
    config = dotenv_values(ROOT / ".env")
    key = config["DEEPSEEK_API_KEY"]
    model = config["DATASET_GENERATOR_MODEL"]
    if not key or not model:
        raise ValueError("local DeepSeek credentials and model are required")
    workspace.mkdir(parents=True)
    save(workspace / "history_hashes.json", history)
    spec = ROOT / "docs/GENERATOR_COMPARISON.md"
    suite = load_suite("mini_agent_query_user_intent_v3")
    schedule = [(1, "direct"), (1, "deepeval"), (2, "deepeval"), (2, "direct")]
    protocol = {
        "suite_id": suite.suite_id,
        "model": model,
        "temperature": 0.4,
        "thinking": "disabled",
        "max_tokens": 4096,
        "max_slot_attempts": 3,
        "network_retries": 0,
        "schedule": schedule,
        "spec_sha256": sha256_file(spec),
        "model_adapter": "ControlledDeepSeek native wrapper; identical wire settings",
        "deepeval_version": "4.3.2",
        "deepeval_configuration": {
            "async_mode": False,
            "synthetic_input_quality_threshold": 0.0,
            "max_quality_retries": 1,
            "num_evolutions": 0,
            "max_goldens_per_context": 1,
            "reason": "Preserve intentional invalid/ambiguous negative scenarios",
        },
        "sdk_cost_note": "authoritative usage is captured by the shared provider",
        "human_approval": "PENDING",
        "freeze": "NOT_RUN",
    }
    save(workspace / "protocol.json", protocol)
    files = [
        ROOT / "src/dataset_builder" / n
        for n in (
            "generation_comparison.py",
            "comparison_provider.py",
            "deepeval_generation.py",
            "scenario_requirements.py",
        )
    ] + [Path(__file__).resolve()]
    save(
        workspace / "implementation_hashes.json",
        {str(p.relative_to(ROOT)): sha256_file(p) for p in files},
    )
    summaries = []
    review_packet = []
    review_key = {}
    bindings = None
    start = time.monotonic()
    print(str(workspace), flush=True)
    for round_number, method in schedule:
        arm_name = f"round_{round_number}_{method}"
        arm = workspace / arm_name
        request = prepare_generation(suite, arm)
        with httpx.Client(transport=httpx.HTTPTransport(retries=0), timeout=90) as http:
            provider = ControlledProvider(http, model, key, arm / "model_calls.jsonl")
            if method == "direct":
                synthesize = DirectSlotSynthesizer(provider.complete).generate
            else:
                generator = DeepEvalGenerationClient(
                    suite=suite, model=ControlledDeepSeek(provider, key)
                )
                generator._sdk_version()
                synthesize = generator._synthesize

            def begin(slot_id, attempt, provider=provider, arm_name=arm_name):
                provider.slot_id = slot_id
                provider.attempt = attempt
                print(f"{arm_name} {slot_id} attempt={attempt}", flush=True)

            result = run_arm(
                suite, request, synthesize, arm, max_slot_attempts=3, on_attempt=begin
            )
        if bindings is None:
            bindings = result["bindings"]
        if result["bindings"] != bindings:
            raise ValueError("comparison source bindings drifted between arms")
        subset = persist_subset(suite, result, arm)
        stats = {
            **summarize_arm(result),
            **usage_summary(provider.calls),
            "arm": arm_name,
            "round": round_number,
            "method": method,
            "subset_passed": subset["subset_passed"],
        }
        summaries.append(stats)
        save(arm / "metrics.json", stats)
        save(workspace / "summary.json", {"status": "RUNNING", "arms": summaries})
        for accepted in result["accepted"]:
            rid = hashlib.sha256(
                (arm_name + ":" + accepted["slot_id"]).encode()
            ).hexdigest()[:14]
            sample = accepted["sample"]
            oracle = (
                json.loads(sample["expected_output"])
                if sample["expected_output"]
                else None
            )
            review_packet.append(
                {
                    "review_id": rid,
                    "slot_id": accepted["slot_id"],
                    "input_only": accepted["input_only"],
                    "user_input": sample["input"],
                    "expected_parameters": json.loads(
                        oracle["expected_parameters_json"]
                    )
                    if oracle
                    else None,
                    "expected_status": oracle["expected_status"] if oracle else None,
                    "expected_next_action": oracle["expected_next_action"]
                    if oracle
                    else None,
                    "missing_parameters": oracle["missing_parameters"]
                    if oracle
                    else None,
                }
            )
            review_key[rid] = {"arm": arm_name, "slot_id": accepted["slot_id"]}
        print(
            f"Completed {arm_name}: {stats['first_pass_count']}/"
            f"{stats['planned_slots']} first pass; {stats['api_calls']} API calls",
            flush=True,
        )
    random.Random(20261028).shuffle(review_packet)
    save(
        workspace / "blind_review_packet.json",
        {"records": review_packet, "review_type": "AI_ONLY_NOT_HUMAN"},
    )
    save(workspace / "blind_review_key.json", review_key)
    changed = [
        p
        for p, h in history.items()
        if not (ROOT / p).is_file() or sha256_file(ROOT / p) != h
    ]
    leaks = [
        str(p.relative_to(workspace))
        for p in workspace.rglob("*")
        if p.is_file() and key.encode() in p.read_bytes()
    ]
    save(
        workspace / "integrity_report.json",
        {
            "checked_history_files": len(history),
            "changed_history_files": changed,
            "credential_leaks": leaks,
        },
    )
    save(
        workspace / "summary.json",
        {
            "status": "FAILED_INTEGRITY" if changed or leaks else "COMPLETED",
            "arms": summaries,
            "elapsed_seconds": time.monotonic() - start,
            "source_bindings_equal": True,
            "human_approval": "PENDING",
            "freeze": "NOT_RUN",
            "integrity_passed": not changed and not leaks,
        },
    )
    if changed or leaks:
        raise RuntimeError("integrity verification failed")
    print("Comparison completed; no approval or freeze.", flush=True)


if __name__ == "__main__":
    main()
