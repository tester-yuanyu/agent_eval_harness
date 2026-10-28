"""Resumable slot attempts and deterministic assembly; no runtime execution."""

from __future__ import annotations

import json
import time
from pathlib import Path

from eval_framework.schemas import EvalCase

from dataset_builder.full_generation.intent_cases import assertions, execution
from dataset_builder.full_generation.models import ContractCase

from .plan import canonical
from .validation import fingerprint, validate_candidate


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def read(path):
    return json.loads(Path(path).read_text())


def run_slot(plan, spec, method, folder, backend, *, max_attempts=3, on_attempt=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    context = plan.context(spec)
    binding = {
        "spec": spec,
        "source": plan.binding,
        "context_sha256": fingerprint(context),
        "method": method,
        "max_attempts": max_attempts,
    }
    request = folder / "request.json"
    if request.exists():
        if read(request) != binding:
            raise ValueError("resume source/spec/settings drift")
    else:
        save(request, binding)
        (folder / "context.txt").write_text(context)
    if (folder / "result.json").exists():
        return read(folder / "result.json")
    attempts = []
    candidate = None
    accepted_attempt = None
    for number in range(1, max_attempts + 1):
        path = folder / f"attempt_{number}.json"
        started = folder / f"attempt_{number}.started.json"
        if path.exists():
            record = read(path)
        elif started.exists():
            record = {
                "attempt": number,
                "issues": [
                    "interrupted attempt; budget consumed, raw API log retained"
                ],
                "candidate": None,
                "raw": None,
                "elapsed_seconds": 0.0,
                "interrupted": True,
                "timing": "unknown duration; excluded, not a zero-cost call",
            }
            save(path, record)
        else:
            feedback = attempts[-1]["issues"] if attempts else []
            current = context
            if feedback:
                current += (
                    "\nPREVIOUS_REJECTION_DIAGNOSTICS (not new source facts): "
                    + canonical(feedback)
                    + "\nGenerate a fresh candidate satisfying the original source constraints."  # noqa: E501
                )
            save(
                started,
                {
                    "attempt": number,
                    "started_unix": time.time(),
                    "context_sha256": fingerprint(current),
                },
            )
            if on_attempt:
                on_attempt(number)
            start = time.monotonic()
            record = {
                "attempt": number,
                "feedback": feedback,
                "candidate": None,
                "raw": None,
                "issues": [],
            }
            try:
                generated = backend.generate(current, spec, plan)
                record.update(generated)
                record["issues"] = validate_candidate(record["candidate"], spec, plan)
                if not record["issues"]:
                    # Compilation is part of the same acceptance gate for both methods.
                    compile_candidate(record["candidate"], spec, plan, method)
            except Exception as exc:
                record["issues"] = [f"{type(exc).__name__}: {exc}"]
            record["elapsed_seconds"] = time.monotonic() - start
            save(path, record)
        attempts.append(record)
        if not record["issues"]:
            candidate = record["candidate"]
            accepted_attempt = number
            break
    result = {
        "slot_id": spec["slot_id"],
        "target_id": spec["target_id"],
        "layer": spec["layer"],
        "method": method,
        "definition_kind": spec["definition_kind"],
        "input_only": spec["input_only"],
        "extra_oracle_gap": spec["extra_oracle_gap"],
        "accepted": candidate is not None,
        "accepted_attempt": accepted_attempt,
        "first_pass": accepted_attempt == 1,
        "attempt_count": len(attempts),
        "rejected_attempt_count": sum(bool(a["issues"]) for a in attempts),
        "elapsed_seconds": sum(a["elapsed_seconds"] for a in attempts),
        "candidate": candidate,
        "final_issues": attempts[-1]["issues"],
        "human_approval": "PENDING",
        "runtime_execution": "NOT_RUN",
    }
    save(folder / "result.json", result)
    return result


def compile_candidate(c, s, plan, method):
    cid = "GEN-" + method + "-" + s["slot_id"]
    blocked = s["input_only"]
    if s["baseline_format"] == "eval_case" and not blocked:
        if s["case_kind"] == "intent_case":
            payload = {
                "schema_version": "1.0",
                "case_id": cid,
                "task_id": s["target_id"],
                "scenario_type": "expression_variant"
                if s["dimension"] == "expression_variant"
                else "normal",
                "test_scope": "module",
                "target": "intent_router",
                "execution": execution(c["input"]["user_input"]),
                "oracle": {
                    "expected_module_output": c["oracle"]["expected_module_output"],
                    "evaluation": assertions(
                        [
                            "intent_parameters_schema_valid",
                            "intent_match",
                            "status_match",
                            "next_action_match",
                            "params_match",
                            "missing_params_match",
                        ]
                    ),
                },
                "labels": [
                    "slot:" + s["slot_id"],
                    "source:" + s["target_id"],
                    "needs_human_review",
                    "test_fixture",
                ],
            }
        else:
            tools = sorted(
                d["tool_name"]
                for d in plan.documents.values()
                if d["snapshot_type"] == "tool"
            )
            status = c["oracle"]["terminal_status"]
            scope = "end_to_end" if s["layer"] == "end_to_end" else "link"
            oracle = {
                "expected_agent_status": status,
                "forbidden_tools": tools,
                "evaluation": assertions(["status_match", "tool_not_called"]),
            }
            if scope == "end_to_end":
                oracle["goal_state"] = {
                    "terminal_status": status,
                    "forbidden_tools": tools,
                }
                oracle["evaluation"] = {
                    "checks": [
                        {
                            "name": "turns_match",
                            "weight": 1,
                            "critical": True,
                            "config": {"turns": [{"status": status, "tool_calls": []}]},
                        }
                    ]
                }
            payload = {
                "schema_version": "1.0",
                "case_id": cid,
                "task_id": s["target_id"] + "." + s["dimension"].split(":")[0],
                "scenario_type": "missing_parameter"
                if status == "NEED_CLARIFICATION"
                else "normal",
                "test_scope": scope,
                "target": s["target_id"].removeprefix("chain."),
                "execution": execution(c["input"]["user_input"]),
                "oracle": oracle,
                "labels": [
                    "slot:" + s["slot_id"],
                    "early_stop",
                    "terminal_goal_only",
                    "needs_runtime_profile_binding",
                    "test_fixture",
                ],
            }
        payload = EvalCase.model_validate(payload).model_dump(mode="json")
        fmt = "eval_case"
    else:
        oracle = {"checks": [], "unresolved": c["gap"]} if blocked else c["oracle"]
        payload = ContractCase(
            case_id=cid,
            slot_id=s["slot_id"],
            target_id=s["target_id"],
            layer=s["layer"],
            preconditions=c["preconditions"],
            input=c["input"],
            oracle=oracle,
            source_refs=s["source_refs"],
            runner_requirements=[
                "Explicit isolated source-bound harness required; no Agent runtime executed."  # noqa: E501
            ],
        ).model_dump(mode="json")
        fmt = "capability_contract_case"
    return {
        "slot_id": s["slot_id"],
        "dataset_format": fmt,
        "payload": payload,
        "validation_status": "valid",
        "execution_readiness": "blocked" if blocked else s["execution_readiness"],
        "coverage_mode": "contract"
        if fmt != "eval_case"
        else "direct"
        if s["case_kind"] == "intent_case"
        else "indirect",
        "blocker_ids": s["blocker_ids"]
        + (["ORACLE-MAPPING-" + s["slot_id"]] if s["extra_oracle_gap"] else []),
    }
