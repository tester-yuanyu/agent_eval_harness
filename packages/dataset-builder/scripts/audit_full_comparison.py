"""Read-only final verification of generated candidates and actual wire settings."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from dataset_builder.full_comparison.plan import load_plan, sha
from dataset_builder.full_comparison.runner import read, save
from dataset_builder.full_comparison.validation import validate_candidate

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workspace", type=Path)
    args = ap.parse_args()
    w = args.workspace.resolve()
    plan = load_plan(ROOT / "tests/fixtures/full_tools_fixture_v1_full_eval_20261020")
    protocol = read(w / "protocol.json")
    ids = set(protocol["planned_slots"])
    specs = {s["slot_id"]: s for s in plan.specs if s["slot_id"] in ids}
    issues = []
    counts = {"results": 0, "accepted_revalidated": 0, "wire_calls": 0}
    for method in ["direct", "deepeval"]:
        for sid, spec in specs.items():
            folder = w / method / sid
            if not (folder / "result.json").exists():
                issues.append(
                    {"method": method, "slot_id": sid, "issue": "missing result"}
                )
                continue
            result = read(folder / "result.json")
            counts["results"] += 1
            if result["accepted"]:
                validation = validate_candidate(result["candidate"], spec, plan)
                counts["accepted_revalidated"] += 1
                if validation:
                    issues.append(
                        {"method": method, "slot_id": sid, "issue": validation}
                    )
            log = folder / "model_calls.jsonl"
            for line in log.read_text().splitlines() if log.exists() else []:
                call = json.loads(line)
                counts["wire_calls"] += 1
                body = call["request_body"]
                for name in ["model", "temperature", "max_tokens"]:
                    if body.get(name) != protocol[name]:
                        issues.append(
                            {"slot_id": sid, "issue": "wire setting drift: " + name}
                        )
                if body.get("thinking") != {"type": protocol["thinking"]}:
                    issues.append({"slot_id": sid, "issue": "thinking setting drift"})
                encoded = json.dumps(
                    body, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                ).encode()
                if (
                    call.get("request_sha256")
                    and hashlib.sha256(encoded).hexdigest() != call["request_sha256"]
                ):
                    issues.append({"slot_id": sid, "issue": "request hash mismatch"})
    for path, digest in protocol["implementation_hashes"].items():
        if sha(ROOT / path) != digest:
            issues.append({"issue": "implementation changed since run", "path": path})
    for path, digest in read(w / "history_hashes.json").items():
        if not (ROOT / path).is_file() or sha(ROOT / path) != digest:
            issues.append({"issue": "historical artifact changed", "path": path})
    result = {
        "valid": not issues,
        "counts": counts,
        "issues": issues,
        "runtime_execution": "NOT_RUN",
    }
    save(w / "final_audit.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
