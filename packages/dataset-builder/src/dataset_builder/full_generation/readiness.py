"""直接绑定现有 generate-full 产物，保留完整分母和原始协议字节。"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

from eval_contracts.agent_readiness import (
    AgentPlan,
    agent_checks,
    binding_for,
    category_for,
)
from eval_contracts.full_readiness import (
    FullCase,
    FullEvidence,
    FullRequest,
    assertion_identity,
    execution_for,
    reference_checks,
)
from eval_contracts.operation_readiness import operation_checks
from eval_contracts.readiness import (
    ReleaseReview,
    RunnerIdentity,
    digest_bytes,
    local_path,
)

from .delivery import definition_kind, verify_delivery
from .models import GenerationResult


def build_request(delivery: Path) -> FullRequest:
    delivery = delivery.resolve()
    manifest_bytes = (delivery / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    # Validate paths before the legacy verifier reads them.
    for name in [
        *manifest["files_sha256"],
        *(ds["path"] for ds in manifest["datasets"]),
    ]:
        local_path(name)
        if not (delivery / name).resolve().is_relative_to(delivery):
            raise ValueError("delivery path escapes root")
    report = verify_delivery(delivery)
    if not report["valid"]:
        raise ValueError("delivery invalid: " + "; ".join(report["issues"]))
    if "generation_result.json" not in manifest["files_sha256"]:
        raise ValueError("generation result missing hash binding")
    generation = GenerationResult.model_validate_json(
        (delivery / "generation_result.json").read_bytes()
    )
    generated = {c.payload["case_id"]: c for c in generation.cases}
    if len(generated) != len(generation.cases):
        raise ValueError("duplicate generated case identity")
    seen, counts, cases = set(), Counter(), []
    for ds in manifest["datasets"]:
        data = (delivery / ds["path"]).read_bytes()
        if (
            digest_bytes(data) != ds["sha256"]
            or manifest["files_sha256"].get(ds["path"]) != ds["sha256"]
        ):
            raise ValueError("dataset hash binding mismatch")
        rows = [json.loads(line) for line in data.splitlines() if line.strip()]
        for row in rows:
            cid = row["case_id"]
            if cid in seen or cid not in generated or generated[cid].payload != row:
                raise ValueError("dataset/generation case mismatch or duplicate")
            kind = definition_kind(generated[cid])
            if ds["definition_kind"] != kind:
                raise ValueError("definition kind mismatch")
            seen.add(cid)
            counts[kind] += 1
            if kind == "behavior_case":
                cases.append(FullCase(case_id=cid, source_path=ds["path"], payload=row))
    if seen != set(generated) or dict(counts) != manifest["definition_counts"]:
        raise ValueError("full delivery denominator mismatch")
    schema_path = "source_delivery/bundle/tools/query_user_info.json"
    schema = {}
    if (delivery / schema_path).exists():
        data = (delivery / schema_path).read_bytes()
        if digest_bytes(data) != manifest["files_sha256"].get(schema_path):
            raise ValueError("tool schema missing hash binding")
        schema = json.loads(data)["function_schema"]
    target_schemas = {}
    capability_documents = []
    for name in manifest["files_sha256"]:
        path = Path(name)
        if name.startswith("source_delivery/bundle/") and name.endswith(".json"):
            document = json.loads((delivery / path).read_bytes())
            if (
                isinstance(document, dict)
                and "snapshot_id" in document
                and "snapshot_type" in document
            ):
                capability_documents.append(document)
        if path.parent.as_posix() == "source_delivery/bundle/tools":
            doc = json.loads((delivery / path).read_bytes())
            target_schemas["tool." + path.stem] = doc["function_schema"]
        elif path.parent.as_posix() == "source_delivery/bundle/intents":
            doc = json.loads((delivery / path).read_bytes())
            target_schemas["intent." + path.stem] = doc["parameters_schema"]
    # Recheck after constructing the request: no file read can race preparation.
    for name, expected in manifest["files_sha256"].items():
        if digest_bytes((delivery / name).read_bytes()) != expected:
            raise ValueError("delivery changed during preparation")
    if (delivery / "manifest.json").read_bytes() != manifest_bytes:
        raise ValueError("manifest changed during preparation")
    return FullRequest(
        schema_version="builder-full-readiness-v3",
        capability_documents=sorted(
            capability_documents, key=lambda d: d["snapshot_id"]
        ),
        target_schemas=target_schemas,
        source_manifest_sha256=digest_bytes(manifest_bytes),
        bundle_sha256=manifest["bundle_sha256"],
        source_files=manifest["files_sha256"],
        definition_counts=dict(counts),
        tool_schema=schema,
        cases=sorted(cases, key=lambda c: c.case_id),
    )


def prepare(delivery: Path, output: Path) -> dict:
    request = build_request(delivery)
    with output.open("x") as handle:
        handle.write(request.model_dump_json(indent=2) + "\n")
    return {
        "static_valid": True,
        "dataset_sha256": request.sha256(),
        "behavior_case_count": len(request.cases),
    }


def assess(
    delivery: Path, evidence: Path | None, current_identity: dict, review=None
) -> dict:
    report = {
        "static_valid": False,
        "ready_for_review": False,
        "release_ready": False,
        "approval": "PENDING",
        "runtime_binding_rate": 0.0,
        "reference_verified_rate": 0.0,
        "verified_behavior_count": 0,
        "unbound_behavior_count": 0,
        "results": [],
        "issues": [],
    }
    try:
        request = build_request(delivery)
        report.update(
            static_valid=True,
            dataset_sha256=request.sha256(),
            source_manifest_sha256=request.source_manifest_sha256,
            behavior_case_count=len(request.cases),
            blocked_obligation_count=request.definition_counts.get(
                "blocked_obligation", 0
            ),
            contract_check_count=request.definition_counts.get("contract_check", 0),
        )
        operations = request.schema_version != "builder-full-readiness-v1"
        plans = (
            {c.case_id: binding_for(c, request) for c in request.cases}
            if operations
            else {}
        )
        selected = {
            c.case_id: c
            for c in request.cases
            if (plans[c.case_id] if operations else execution_for(c)) is not None
        }
        report["unbound_behavior_count"] = len(request.cases) - len(selected)
        report["unbound_case_ids"] = [
            c.case_id for c in request.cases if c.case_id not in selected
        ]
        identity = RunnerIdentity.model_validate(current_identity)
        if (
            identity.runner_id
            != (
                "inspect-mini-agent-v3"
                if request.schema_version == "builder-full-readiness-v3"
                else "inspect-mini-operations-v2"
                if operations
                else "native-mini-query-user-v1"
            )
            or identity.runtime.get("full_assertions_sha256") != assertion_identity()
        ):
            raise ValueError("Builder/runner assertion identity mismatch")
        if evidence is None:
            raise ValueError("runner evidence is missing")
        raw = evidence.read_bytes()
        proof = FullEvidence.model_validate_json(raw)
        if proof.dataset_sha256 != request.sha256() or proof.runner != identity:
            raise ValueError("delivery or runner evidence is stale")
        report["evidence_sha256"] = digest_bytes(raw)
        ids = [r.case_id for r in proof.results]
        if len(ids) != len(set(ids)) or set(ids) != set(selected):
            raise ValueError("evidence must cover exact runnable case set once")
        for row in proof.results:
            case = selected[row.case_id]
            checks = (
                (
                    agent_checks(case, plans[row.case_id], row, request)
                    if isinstance(plans[row.case_id], AgentPlan)
                    else operation_checks(case, plans[row.case_id], row)
                )
                if operations
                else reference_checks(case, row)
            )
            report["results"].append(
                {
                    "case_id": row.case_id,
                    "checks": checks,
                    "source_path": selected[row.case_id].source_path,
                    "category": category_for(case),
                    "agent_category": plans[row.case_id].category
                    if operations and isinstance(plans[row.case_id], AgentPlan)
                    else None,
                    "reference_verified": all(checks.values()),
                }
            )
        report["verified_behavior_count"] = sum(
            r["reference_verified"] for r in report["results"]
        )
        report["category_counts"] = {}
        for category in ("schema_validation", "tool_behavior", "agent_behavior"):
            rows = [r for r in report["results"] if r["category"] == category]
            total = sum(category_for(c) == category for c in request.cases)
            report["category_counts"][category] = {
                "total": total,
                "bound": len(rows),
                "verified": sum(r["reference_verified"] for r in rows),
                "failed": sum(not r["reference_verified"] for r in rows),
                "unbound": total - len(rows),
            }
        report["agent_category_counts"] = {}
        for name in ("intent_module", "early_stop", "module_event", "agent_chain"):
            rows = [r for r in report["results"] if r.get("agent_category") == name]
            report["agent_category_counts"][name] = {
                "bound": len(rows),
                "verified": sum(r["reference_verified"] for r in rows),
                "failed": sum(not r["reference_verified"] for r in rows),
            }
        report["runtime_binding_rate"] = sum(
            r["checks"]["harness_binding"] for r in report["results"]
        ) / len(request.cases)
        report["reference_verified_rate"] = report["verified_behavior_count"] / len(
            request.cases
        )
        report["ready_for_review"] = (
            report["verified_behavior_count"] == len(request.cases)
            and report["blocked_obligation_count"] == 0
        )
        if not report["ready_for_review"]:
            report["issues"].append(
                "whole delivery has unverified behavior or blocked obligations"
            )
        if review is not None:
            approval = ReleaseReview.model_validate(review)
            expected = [c.case_id for c in request.cases]
            if (
                approval.dataset_sha256 != request.sha256()
                or approval.evidence_sha256 != report["evidence_sha256"]
                or sorted(approval.reviewed_case_ids) != sorted(expected)
            ):
                raise ValueError(
                    "review does not bind current full delivery and evidence"
                )
            report["approval"] = "APPROVED"
            report["release_ready"] = report["ready_for_review"]
    except (ValueError, OSError, KeyError) as exc:
        report["issues"].append(str(exc))
    return report


def freeze_release(
    delivery: Path, evidence: Path, identity: dict, review: dict, output: Path
) -> dict:
    if not assess(delivery, evidence, identity, review)["release_ready"]:
        raise ValueError("full delivery release gate has not passed")
    output.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copytree(delivery, output / "delivery")
        shutil.copyfile(evidence, output / "evidence.json")
        report = assess(output / "delivery", output / "evidence.json", identity, review)
        if not report["release_ready"]:
            raise ValueError("full delivery changed before freezing")
        manifest = {
            "state": "FROZEN",
            "format": "builder-full-readiness-v1",
            "runner": identity,
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
