"""Aggregate all attempted slots without selecting only successful generations."""

from __future__ import annotations

import json
from collections import Counter, defaultdict

from eval_framework import load_dataset, validate_dataset

from dataset_builder.comparison_provider import usage_summary
from dataset_builder.full_generation.models import FullInventory
from dataset_builder.full_generation.validation import evaluator_context

from .plan import sha
from .runner import compile_candidate, read, save
from .validation import fingerprint


def jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def stratum(s):
    if s["extra_oracle_gap"]:
        return "behavior_input_only_new_gap"
    return s["definition_kind"]


def summarize(plan, workspace, wall_seconds):
    all_metrics = {}
    review = []
    review_key = {}
    outcomes = {}
    coverage = []
    tools = sorted(
        d["tool_name"] for d in plan.documents.values() if d["snapshot_type"] == "tool"
    )
    inv = FullInventory.model_validate(read(plan.root / "inventory.json"))
    registry, catalog = evaluator_context(inv)
    for method in ["direct", "deepeval"]:
        root = workspace / method
        results = []
        calls = []
        accepted = []
        compiled = []
        categories = defaultdict(list)
        targets = defaultdict(list)
        layers = defaultdict(list)
        rejections = Counter()
        for spec in plan.specs:
            folder = root / spec["slot_id"]
            result = read(folder / "result.json")
            results.append(result)
            expect_method = (
                result["method"] == method and result["slot_id"] == spec["slot_id"]
            )
            if not expect_method:
                raise ValueError("result binding mismatch")
            categories[stratum(spec)].append(result)
            targets[spec["target_id"]].append(result)
            layers[spec["layer"]].append(result)
            for ap in folder.glob("attempt_*.json"):
                if ".started." not in ap.name:
                    for issue in read(ap).get("issues", []):
                        rejections[issue.split(":", 1)[0]] += 1
            callpath = folder / "model_calls.jsonl"
            if callpath.exists():
                calls.extend(
                    json.loads(line)
                    for line in callpath.read_text().splitlines()
                    if line.strip()
                )
            coverage.append(
                {
                    "method": method,
                    "slot_id": spec["slot_id"],
                    "target_id": spec["target_id"],
                    "definition_kind": spec["definition_kind"],
                    "input_only": spec["input_only"],
                    "accepted": result["accepted"],
                    "attempt_count": result["attempt_count"],
                    "issues": result["final_issues"],
                }
            )
            if result["accepted"]:
                accepted.append(result)
                compiled.append(
                    compile_candidate(result["candidate"], spec, plan, method)
                )
                rid = fingerprint([method, spec["slot_id"]])[:18]
                review.append(
                    {
                        "review_id": rid,
                        "cohort": fingerprint(method)[:10],
                        "slot": spec,
                        "candidate": result["candidate"],
                    }
                )
                review_key[rid] = {"method": method, "slot_id": spec["slot_id"]}

        def counts(rows):
            return {
                "planned": len(rows),
                "first_pass": sum(r["first_pass"] for r in rows),
                "accepted": sum(r["accepted"] for r in rows),
                "exhausted": sum(not r["accepted"] for r in rows),
                "attempts": sum(r["attempt_count"] for r in rows),
                "rejected_attempts": sum(r["rejected_attempt_count"] for r in rows),
                "slot_seconds_sum": sum(r["elapsed_seconds"] for r in rows),
            }

        behavior = [
            r
            for r in accepted
            if r["definition_kind"] == "behavior_case" and not r["input_only"]
        ]
        signatures = []
        stimuli = []
        for r in behavior:
            c = r["candidate"]
            inp = {
                k: v
                for k, v in c["input"].items()
                if k not in {"parameter", "dimension"}
            }
            stimuli.append(fingerprint([r["target_id"], inp, c["preconditions"]]))
            signatures.append(
                fingerprint([r["target_id"], inp, c["preconditions"], c["oracle"]])
            )
        repeated = Counter(signatures)
        metadata = usage_summary(calls)
        metrics = {
            **counts(results),
            **metadata,
            "by_category": {k: counts(v) for k, v in categories.items()},
            "by_target": {k: counts(v) for k, v in targets.items()},
            "by_layer": {k: counts(v) for k, v in layers.items()},
            "rejection_categories": dict(rejections),
            "exact_stimulus_reuse_extra_records": sum(
                n - 1 for n in Counter(stimuli).values() if n > 1
            ),
            "accepted_behavior_candidates": len(behavior),
            "accepted_static_checks": sum(
                r["definition_kind"] == "contract_check" for r in accepted
            ),
            "accepted_input_only": sum(r["input_only"] for r in accepted),
            "exact_behavior_reuse_extra_records": sum(
                n - 1 for n in repeated.values() if n > 1
            ),
            "api_request_seconds_sum": sum(c["elapsed_seconds"] for c in calls),
            "candidate_definition_readiness": dict(
                Counter(c["execution_readiness"] for c in compiled)
            ),
        }
        all_metrics[method] = metrics
        outcomes[method] = results
        save(root / "metrics.json", metrics)
        jsonl(root / "accepted_candidates.jsonl", accepted)
        jsonl(root / "compiled_cases.jsonl", compiled)
        jsonl(root / "blocked_inputs.jsonl", [r for r in accepted if r["input_only"]])
        jsonl(root / "failed_slots.jsonl", [r for r in results if not r["accepted"]])
        for fmt in ["eval_case", "capability_contract_case"]:
            records = [c["payload"] for c in compiled if c["dataset_format"] == fmt]
            path = root / (fmt + ".jsonl")
            jsonl(path, records)
            save(
                path.with_suffix(".manifest.json"),
                {
                    "dataset_sha256": sha(path),
                    "state": "DRAFT",
                    "dataset_version": "full-generation-comparison-1",
                    "capability_bundle_sha256": plan.binding["bundle_sha256"],
                    "execution_profiles": {"full_fixture": {"allowed_tools": tools}},
                },
            )
        eval_path = root / "eval_case.jsonl"
        report = validate_dataset(
            load_dataset(eval_path), capabilities=registry, tools=catalog
        )
        metrics["evaluator_static_valid"] = not report.issues
        save(root / "metrics.json", metrics)
        save(
            root / "evaluator_static_validation.json",
            {
                "valid": not report.issues,
                "issues": [
                    {
                        "case_id": i.case_id,
                        "field_path": i.field_path,
                        "message": i.message,
                    }
                    for i in report.issues
                ],
                "runtime_execution": "NOT_RUN",
                "human_approval": "PENDING",
            },
        )
    # Reproducible label-blinded packet; no method names inside its records.
    review.sort(key=lambda r: r["review_id"])
    save(
        workspace / "semantic_review_packet.json",
        {"review_type": "AI_ONLY_NOT_HUMAN", "records": review},
    )
    save(workspace / "semantic_review_key.json", review_key)
    jsonl(workspace / "coverage_comparison.jsonl", coverage)
    paired = Counter()
    for s in plan.specs:
        a = next(r for r in outcomes["direct"] if r["slot_id"] == s["slot_id"])
        b = next(r for r in outcomes["deepeval"] if r["slot_id"] == s["slot_id"])
        paired[f"direct_{a['accepted']}_deepeval_{b['accepted']}"] += 1
    summary = {
        "status": "GENERATION_COMPLETED"
        if all(m["evaluator_static_valid"] for m in all_metrics.values())
        else "GENERATION_COMPLETED_WITH_EXPORT_ISSUES",
        "planned_per_method": len(plan.specs),
        "targets": len({s["target_id"] for s in plan.specs}),
        "methods": all_metrics,
        "paired_final_acceptance": dict(paired),
        "experiment_wall_seconds": wall_seconds,
        "timing_note": "slot/request seconds are cumulative across concurrent jobs, not observed serial wall time",  # noqa: E501
        "human_approval": "PENDING",
        "runtime_execution": "NOT_RUN",
        "freeze": "NOT_RUN",
    }
    save(workspace / "summary.json", summary)
    return summary
