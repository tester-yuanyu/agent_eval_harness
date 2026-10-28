"""Run or resume all source-bound mini_agent slots with both real backends."""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
os.environ["DEEPEVAL_UPDATE_WARNING_OPT_IN"] = "0"

import httpx
from dotenv import dotenv_values

from dataset_builder.comparison_provider import ControlledProvider
from dataset_builder.full_comparison.backend import DeepEvalBackend, DirectBackend
from dataset_builder.full_comparison.plan import load_plan, sha
from dataset_builder.full_comparison.report import summarize
from dataset_builder.full_comparison.runner import read, run_slot, save

ROOT = Path(__file__).resolve().parents[1]


def select_pilot(specs):
    selected = {}
    for s in specs:
        if s["input_only"]:
            key = (s["target_id"], "input_only", s["extra_oracle_gap"])
        elif s["case_kind"] in {
            "tool_result",
            "module_event",
            "tool_rule",
            "intent_case",
        }:
            key = (s["target_id"], s["case_kind"], s["dimension"])
        elif s["case_kind"] == "chain_case":
            key = (s["target_id"], s["dimension"])
        elif s["case_kind"] == "parameter":
            key = ("parameter", s["dimension"])
        else:
            key = ("static", s["target_id"])
        selected.setdefault(key, s)
    return list(selected.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        raise ValueError("workers must be1..16")
    plan = load_plan(ROOT / "tests/fixtures/full_tools_fixture_v1_full_eval_20261020")
    if args.pilot:
        plan.specs = select_pilot(plan.specs)
    workspace = (
        args.workspace
        or ROOT
        / "workspaces"
        / (
            "full_generator_"
            + ("pilot_" if args.pilot else "comparison_")
            + datetime.now().strftime("%Y%m%d_%H%M%S")
        )
    ).resolve()
    config = dotenv_values(ROOT / ".env")
    key = config["DEEPSEEK_API_KEY"]
    model = config["DATASET_GENERATOR_MODEL"]
    if not key or not model:
        raise ValueError("local provider configuration missing")
    source_files = (
        sorted((ROOT / "src/dataset_builder/full_comparison").glob("*.py"))
        + [
            Path(__file__).resolve(),
            ROOT / "src/dataset_builder/comparison_provider.py",
        ]
        + sorted((ROOT / "src/dataset_builder/full_generation").glob("*.py"))
    )
    protocol = {
        "source_binding": plan.binding,
        "model": model,
        "temperature": 0.4,
        "thinking": "disabled",
        "max_tokens": 4096,
        "network_retries": 0,
        "max_slot_attempts": 3,
        "workers": args.workers,
        "pilot": args.pilot,
        "planned_slots": [s["slot_id"] for s in plan.specs],
        "ordering": "alternating direct/deepeval within each slot pair;8 workers by default",  # noqa: E501
        "sdk_version": "4.3.2",
        "quality_threshold": 0,
        "num_evolutions": 0,
        "dedup_policy": "post-hoc exact structured behavior diagnostic; retain semantic symbols",  # noqa: E501
        "implementation_hashes": {
            str(p.relative_to(ROOT)): sha(p) for p in source_files
        },
        "human_approval": "PENDING",
        "freeze": "NOT_RUN",
    }
    if args.resume:
        if not workspace.exists() or read(workspace / "protocol.json") != protocol:
            raise ValueError("resume requires matching protocol, source and code")
    else:
        if workspace.exists():
            raise FileExistsError("new experiment requires a new workspace")
        history = {
            str(p.relative_to(ROOT)): sha(p)
            for name in ["workspaces", "suites"]
            for p in (ROOT / name).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        }
        workspace.mkdir(parents=True)
        save(workspace / "history_hashes.json", history)
        save(workspace / "protocol.json", protocol)
        save(workspace / "generation_plan.json", {"slots": plan.specs})
        save(workspace / "source_documents.json", plan.documents)
    previous = (
        read(workspace / "run_sessions.json")
        if (workspace / "run_sessions.json").exists()
        else []
    )
    for session in previous:
        if session.get("state") == "RUNNING":
            session["state"] = "INTERRUPTED"
            session["timing"] = "last persisted progress; lower bound"
    start = time.monotonic()
    previous.append(
        {"state": "RUNNING", "started_unix": time.time(), "elapsed_seconds": 0.0}
    )
    save(workspace / "run_sessions.json", previous)
    print(str(workspace), flush=True)

    def pair(item):
        index, spec = item
        methods = ["direct", "deepeval"] if index % 2 == 0 else ["deepeval", "direct"]
        output = []
        for method in methods:
            folder = workspace / method / spec["slot_id"]
            folder.mkdir(parents=True, exist_ok=True)
            with httpx.Client(
                transport=httpx.HTTPTransport(retries=0), timeout=90
            ) as http:
                provider = ControlledProvider(
                    http, model, key, folder / "model_calls.jsonl"
                )
                if provider.log_path.exists():
                    provider.calls = [
                        json.loads(line)
                        for line in provider.log_path.read_text().splitlines()
                        if line.strip()
                    ]
                provider.slot_id = spec["slot_id"]
                backend = (
                    DirectBackend(provider)
                    if method == "direct"
                    else DeepEvalBackend(provider, key)
                )

                def begin(number, provider=provider):
                    provider.attempt = number

                result = run_slot(plan, spec, method, folder, backend, on_attempt=begin)
                output.append((method, result["accepted"], result["attempt_count"]))
        return spec["slot_id"], output

    errors = []
    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        tasks = {
            pool.submit(pair, item): item[1]["slot_id"]
            for item in enumerate(plan.specs)
        }
        for future in as_completed(tasks):
            try:
                slot, output = future.result()
                completed += 1
                print(f"{completed}/{len(plan.specs)} {slot} {output}", flush=True)
            except Exception as exc:
                errors.append(
                    {
                        "slot_id": tasks[future],
                        "error": str(exc).replace(key, "[REDACTED]"),
                    }
                )
                print("pair failure " + tasks[future], flush=True)
            previous[-1]["elapsed_seconds"] = time.monotonic() - start
            save(workspace / "run_sessions.json", previous)
            save(
                workspace / "progress.json",
                {
                    "completed_pairs_this_session": completed,
                    "planned_pairs": len(plan.specs),
                    "errors": errors,
                    "elapsed_seconds": time.monotonic() - start,
                },
            )
    elapsed = time.monotonic() - start
    previous[-1].update(
        state="COMPLETED",
        elapsed_seconds=elapsed,
        completed_pairs=completed,
        errors=errors,
    )
    save(workspace / "run_sessions.json", previous)
    if errors:
        save(
            workspace / "summary.json",
            {"status": "INCOMPLETE", "errors": errors, "resume_supported": True},
        )
        raise RuntimeError("pair failures recorded; resume required")
    summary = summarize(plan, workspace, sum(s["elapsed_seconds"] for s in previous))
    history = read(workspace / "history_hashes.json")
    changed = [
        name
        for name, h in history.items()
        if not (ROOT / name).is_file() or sha(ROOT / name) != h
    ]
    leaks = [
        str(p.relative_to(workspace))
        for p in workspace.rglob("*")
        if p.is_file() and key.encode() in p.read_bytes()
    ]
    save(
        workspace / "integrity_report.json",
        {
            "history_files_checked": len(history),
            "changed_history_files": changed,
            "credential_leaks": leaks,
        },
    )
    if changed or leaks:
        summary["status"] = "FAILED_INTEGRITY"
        save(workspace / "summary.json", summary)
        raise RuntimeError("integrity failure")
    print(
        "Generation complete; semantic review pending; no approval or freeze.",
        flush=True,
    )


if __name__ == "__main__":
    main()
