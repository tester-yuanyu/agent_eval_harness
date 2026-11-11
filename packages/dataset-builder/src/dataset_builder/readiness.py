"""P0 发布门槛；只消费本地证据，不导入或执行 Evaluator。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from eval_contracts.readiness import (
    ReadinessDataset,
    ReadinessEvidence,
    ReleaseReview,
    RunnerIdentity,
    assertion_identity,
    digest_bytes,
    reference_checks,
)


def prepare(dataset: Path, output: Path) -> dict[str, Any]:
    data = dataset.read_bytes()
    parsed = ReadinessDataset.model_validate_json(data)
    with output.open("xb") as handle:
        handle.write(data)
    return {
        "static_valid": True,
        "dataset_sha256": digest_bytes(data),
        "case_count": len(parsed.cases),
    }


def assess(
    dataset: Path,
    evidence: Path | None,
    current_identity: dict[str, Any],
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "static_valid": False,
        "ready_for_review": False,
        "release_ready": False,
        "runtime_binding_rate": 0.0,
        "reference_verified_rate": 0.0,
        "approval": "PENDING",
        "issues": [],
        "results": [],
        "scope": "read_file tool reference; not Agent evaluation",
    }
    try:
        data = dataset.read_bytes()
        parsed = ReadinessDataset.model_validate_json(data)
        report.update(
            static_valid=True,
            dataset_sha256=digest_bytes(data),
            case_count=len(parsed.cases),
        )
        identity = RunnerIdentity.model_validate(current_identity)
        if identity.runtime.get("assertions_sha256") != assertion_identity():
            raise ValueError("Builder and runner assertion implementations differ")
        if evidence is None:
            raise ValueError("runner evidence is missing")
        raw = evidence.read_bytes()
        proof = ReadinessEvidence.model_validate_json(raw)
        report["evidence_sha256"] = digest_bytes(raw)
        if proof.dataset_sha256 != report["dataset_sha256"]:
            raise ValueError("dataset/fixture/assertion binding is stale")
        if proof.runner != identity:
            raise ValueError("runner identity is stale")
        ids = [row.case_id for row in proof.results]
        required = {case.case_id for case in parsed.cases}
        if len(ids) != len(set(ids)) or set(ids) != required:
            raise ValueError("evidence must cover the exact fixed case set once")
        rows = {row.case_id: row for row in proof.results}
        for case in parsed.cases:
            row = rows[case.case_id]
            checks = reference_checks(case, row)
            passed = all(checks.values())
            report["results"].append(
                {
                    "case_id": case.case_id,
                    "checks": checks,
                    "reference_verified": passed,
                }
            )
        report["runtime_binding_rate"] = sum(
            row["checks"]["harness_binding"] for row in report["results"]
        ) / len(parsed.cases)
        report["reference_verified_rate"] = sum(
            row["reference_verified"] for row in report["results"]
        ) / len(parsed.cases)
        report["ready_for_review"] = all(
            row["reference_verified"] for row in report["results"]
        )
        if not report["ready_for_review"]:
            report["issues"].append("reference verification failed")
        if review is not None:
            approval = ReleaseReview.model_validate(review)
            reviewed = approval.reviewed_case_ids
            if (
                approval.dataset_sha256 != report["dataset_sha256"]
                or approval.evidence_sha256 != report["evidence_sha256"]
                or set(reviewed) != required
                or len(reviewed) != len(required)
            ):
                raise ValueError("review does not bind current dataset and evidence")
            report["approval"] = "APPROVED"
            report["release_ready"] = report["ready_for_review"]
    except (ValueError, OSError) as exc:
        report["issues"].append(str(exc))
    return report


def freeze_release(
    dataset: Path,
    evidence: Path,
    current_identity: dict[str, Any],
    review: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    # Capture the approved bytes, then assess those exact copies to avoid a
    # check/copy race. The final manifest is the completion marker.
    output.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copyfile(dataset, output / "dataset.json")
        shutil.copyfile(evidence, output / "evidence.json")
        report = assess(
            output / "dataset.json", output / "evidence.json", current_identity, review
        )
        if not report["release_ready"]:
            raise ValueError("release gate failed: " + "; ".join(report["issues"]))
        manifest = {
            "state": "FROZEN",
            "format": "readiness-read-file-v1",
            "runner": current_identity,
            "review": review,
            "validation": report,
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
        return manifest
    except BaseException:
        shutil.rmtree(output)
        raise
