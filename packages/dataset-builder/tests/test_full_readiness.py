import json
import shutil
from pathlib import Path

import pytest

DELIVERY = Path(__file__).parent / "fixtures/full_tools_fixture_v1_full_eval_20261020"


def test_existing_delivery_preserves_full_denominator_and_case_origins():
    from dataset_builder.full_generation.readiness import build_request
    from eval_contracts.agent_readiness import binding_for

    request = build_request(DELIVERY)
    assert len(request.cases) == 365
    assert request.definition_counts == {
        "behavior_case": 365,
        "contract_check": 202,
        "blocked_obligation": 280,
    }
    runnable = [c for c in request.cases if binding_for(c, request) is not None]
    assert request.schema_version == "builder-full-readiness-v3"
    assert len(request.target_schemas) == 13
    assert len(runnable) == 365
    assert (
        sum(
            c.payload.get("input", {}).get("operation") == "validate_arguments"
            for c in runnable
        )
        == 233
    )
    assert all(c.case_id == c.payload["case_id"] for c in request.cases)


def test_changed_source_delivery_rejected(tmp_path):
    from dataset_builder.full_generation.readiness import build_request

    root = tmp_path / "delivery"
    shutil.copytree(DELIVERY, root)
    target = (
        root
        / "datasets/tools"
        / "tool.query_user_info.capability_contract_case.behavior_case.jsonl"
    )
    target.write_text(target.read_text() + "\n")
    with pytest.raises(ValueError, match="hash"):
        build_request(root)


def test_legacy_full_report_cannot_promote_two_passes_to_whole_delivery(
    tmp_path, monkeypatch
):
    from dataset_builder.full_generation.readiness import assess, build_request
    from eval_contracts.full_readiness import (
        FullEvidence,
        ToolEvidence,
        assertion_identity,
        execution_for,
    )
    from eval_contracts.readiness import RunnerIdentity

    request = build_request(DELIVERY)
    request = request.model_copy(
        update={"schema_version": "builder-full-readiness-v1", "target_schemas": {}}
    )
    monkeypatch.setattr(
        "dataset_builder.full_generation.readiness.build_request",
        lambda delivery: request,
    )
    identity = RunnerIdentity(
        runner_id="native-mini-query-user-v1",
        implementation_sha256="a" * 64,
        runtime={"full_assertions_sha256": assertion_identity()},
    )
    rows = []
    for case in request.cases:
        execution = execution_for(case)
        if execution is None:
            continue
        user = execution.users[0] if execution.users else None
        rows.append(
            ToolEvidence(
                case_id=case.case_id,
                status="completed",
                evidence_complete=True,
                before_state={"users": execution.users},
                after_state={"users": execution.users},
                tool_calls=[
                    {"name": "query_user_info", "arguments": execution.arguments}
                ],
                tool_result={
                    "code": "OK" if user else "EMPTY",
                    "success": True,
                    "data": {"user": user},
                },
                errors=[],
            )
        )
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        FullEvidence(
            dataset_sha256=request.sha256(), runner=identity, results=rows
        ).model_dump_json()
    )
    report = assess(DELIVERY, evidence, identity.model_dump())
    assert report["verified_behavior_count"] == 2
    assert report["unbound_behavior_count"] == 363
    assert report["reference_verified_rate"] == 2 / 365
    assert not report["ready_for_review"] and not report["release_ready"]
    assert report["blocked_obligation_count"] == 280
    bad = json.loads(evidence.read_text())
    bad["results"][0]["tool_result"]["code"] = "BROKEN"
    evidence.write_text(json.dumps(bad))
    assert (
        assess(DELIVERY, evidence, identity.model_dump())["verified_behavior_count"]
        == 1
    )


@pytest.mark.parametrize(
    "fault", ["missing", "stale_runner", "stale_delivery", "duplicate", "partial"]
)
def test_missing_stale_or_incomplete_evidence_blocks_release(tmp_path, fault):
    from dataset_builder.full_generation.readiness import (
        assess,
        build_request,
        freeze_release,
    )
    from eval_contracts.agent_readiness import binding_for
    from eval_contracts.full_readiness import (
        FullEvidence,
        ToolEvidence,
        assertion_identity,
    )
    from eval_contracts.readiness import RunnerIdentity

    request = build_request(DELIVERY)
    identity = RunnerIdentity(
        runner_id="inspect-mini-agent-v3",
        implementation_sha256="a" * 64,
        runtime={"full_assertions_sha256": assertion_identity()},
    )
    rows = [
        ToolEvidence(
            case_id=c.case_id,
            status="error",
            evidence_complete=False,
            before_state={},
            after_state={},
            tool_calls=[],
            tool_result={},
            errors=["failed"],
        )
        for c in request.cases
        if binding_for(c, request) is not None
    ]
    proof = FullEvidence(dataset_sha256=request.sha256(), runner=identity, results=rows)
    if fault == "stale_runner":
        proof.runner = identity.model_copy(update={"implementation_sha256": "b" * 64})
    if fault == "stale_delivery":
        proof.dataset_sha256 = "b" * 64
    if fault == "duplicate":
        proof.results.append(rows[0])
    if fault == "partial":
        proof.results.pop()
    evidence = tmp_path / "evidence.json"
    evidence.write_text(proof.model_dump_json())
    path = None if fault == "missing" else evidence
    report = assess(DELIVERY, path, identity.model_dump())
    assert report["static_valid"] and not report["release_ready"]
    assert report["verified_behavior_count"] == 0
    assert report["issues"]
    with pytest.raises(ValueError, match="gate"):
        freeze_release(
            DELIVERY, evidence, identity.model_dump(), {}, tmp_path / "release"
        )
    assert not (tmp_path / "release").exists()
