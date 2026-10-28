from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dataset_builder.generation_client import ScriptedGenerationClient
from dataset_builder.pipeline import (
    compile_candidates,
    freeze_dataset,
    generate_candidates,
    prepare_generation,
    validate_draft,
)
from dataset_builder.schemas import Approval
from dataset_builder.source_pack import sha256_file
from dataset_builder.suite_definition import ROOT, load_suite

TRACE_V1_HASH = "61ff546b81d3969f24cde3d216f17e37b13cb87663bdcc7a6b7b80183a776544"
LEGACY_BUNDLE_HASH = (
    "99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8"
)
SUITE_MIGRATIONS = {
    "mini_agent_intent_v2": "mini_agent_intent_v1",
    "mini_agent_query_user_intent_v2": "mini_agent_query_user_intent_v1",
    "mini_agent_query_gift_intent_v2": "mini_agent_query_gift_intent_v1",
    "mini_agent_add_backpack_gift_intent_v2": (
        "mini_agent_add_backpack_gift_intent_v1"
    ),
}


def _author(suite_id: str, workspace: Path):
    suite = load_suite(suite_id)
    seed = json.loads(suite.seed_catalog_path.read_text())
    request = prepare_generation(suite, workspace)
    raw = generate_candidates(
        request,
        ScriptedGenerationClient(seed),
        workspace,
    )
    cases = compile_candidates(suite, raw, workspace)
    return suite, request, cases


@pytest.mark.parametrize("suite_id", SUITE_MIGRATIONS)
def test_trace_v1_suite_loads_and_preserves_business_case_inputs(
    tmp_path, suite_id
):
    legacy = load_suite(SUITE_MIGRATIONS[suite_id])
    suite, request, cases = _author(suite_id, tmp_path / suite_id)
    _, _, legacy_cases = _author(
        SUITE_MIGRATIONS[suite_id],
        tmp_path / SUITE_MIGRATIONS[suite_id],
    )

    assert suite.capability_bundle_path == ROOT.parents[1] / "examples/mini_agent/exports/trace_v1"
    assert suite.config.capability_input.bundle_hash == TRACE_V1_HASH
    assert suite.validated_capability_bundle.capability_bundle_sha256 == TRACE_V1_HASH
    assert suite.config.capability_input.scope_or_chain_id == (
        legacy.config.capability_input.scope_or_chain_id
    )
    assert suite.config.capability_input.intent_id == (
        legacy.config.capability_input.intent_id
    )
    assert suite.config.capability_input.tool_id == (
        legacy.config.capability_input.tool_id
    )
    assert request.capability_bundle_sha256 == TRACE_V1_HASH
    assert len(cases) == legacy.coverage_plan["case_count"]
    assert suite.suggested_freeze_path != legacy.suggested_freeze_path
    assert suite.suggested_freeze_path.name.endswith("_v2_1.jsonl")
    assert [case.model_dump(mode="json") for case in cases] == [
        case.model_dump(mode="json") for case in legacy_cases
    ]

    report = validate_draft(suite, tmp_path / suite_id / "draft.jsonl")
    assert report.valid, [issue for gate in report.gates for issue in gate.issues]


def test_evaluator_gate_blocks_check_whose_required_evidence_is_unavailable(
    tmp_path,
):
    workspace = tmp_path / "unsupported-evidence"
    suite, _, cases = _author("mini_agent_intent_v2", workspace)
    draft = workspace / "draft.jsonl"
    rows = [json.loads(line) for line in draft.read_text().splitlines()]
    rows[0]["oracle"]["evaluation"]["checks"][0]["name"] = (
        "confirmation_accepted"
    )
    draft.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    )

    report = validate_draft(suite, draft)
    evaluator = next(gate for gate in report.gates if gate.name == "evaluator")

    assert not report.valid
    assert not evaluator.passed
    assert any(
        "confirmation_accepted: required evidence "
        "safety_recovery_event/confirmation_accepted unavailable" in issue
        for issue in evaluator.issues
    )

    approval = Approval(
        reviewer="Evidence Gate Integration Test",
        approved_at=datetime.now(UTC),
        draft_sha256=sha256_file(draft),
        review_artifact_sha256="a" * 64,
        reviewed_case_ids=[case.case_id for case in cases],
    )
    with pytest.raises(ValueError, match="pass every gate"):
        freeze_dataset(
            suite,
            draft,
            approval,
            tmp_path / "must-not-freeze.jsonl",
        )


def test_draft_generated_from_legacy_snapshot_is_stale_under_trace_v1_suite(
    tmp_path,
):
    current = load_suite("mini_agent_query_user_intent_v2")
    legacy = load_suite("mini_agent_query_user_intent_v1")
    legacy_input = current.config.capability_input.model_copy(
        update={
            "bundle": legacy.config.capability_input.bundle,
            "bundle_hash": LEGACY_BUNDLE_HASH,
        }
    )
    generation_suite = replace(
        current,
        config=current.config.model_copy(
            update={"capability_input": legacy_input}
        ),
        capability_bundle_path=legacy.capability_bundle_path,
    )
    workspace = tmp_path / "legacy-bound-draft"
    seed = json.loads(generation_suite.seed_catalog_path.read_text())
    request = prepare_generation(generation_suite, workspace)
    raw = generate_candidates(
        request,
        ScriptedGenerationClient(seed),
        workspace,
    )
    compile_candidates(generation_suite, raw, workspace)

    report = validate_draft(current, workspace / "draft.jsonl")
    snapshot_gate = next(
        gate for gate in report.gates if gate.name == "capability_snapshot"
    )

    assert report.state == "STALE"
    assert not snapshot_gate.passed
    assert any(LEGACY_BUNDLE_HASH in issue for issue in snapshot_gate.issues)
    assert any(TRACE_V1_HASH in issue for issue in snapshot_gate.issues)


@pytest.mark.parametrize("suite_id", SUITE_MIGRATIONS.values())
def test_legacy_suites_remain_bound_to_legacy_snapshot(suite_id):
    suite = load_suite(suite_id)

    assert suite.config.capability_input.bundle.path == "mini_agent/capabilities"
    assert suite.config.capability_input.bundle_hash == LEGACY_BUNDLE_HASH
    assert suite.validated_capability_bundle.capability_bundle_sha256 == (
        LEGACY_BUNDLE_HASH
    )
