from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from dataset_builder.freezing import freeze
from dataset_builder.orchestration import StageLedger
from dataset_builder.pipeline import (
    approval_from_review,
    build_review,
    freeze_dataset,
    validate_draft,
)
from dataset_builder.schemas import Approval, GateResult, ValidationSummary
from dataset_builder.source_pack import sha256_file
from dataset_builder.suite_config import ExecutionProfileConfig


def approval_for(draft, reviewer="Lifecycle Unit Test", reviewed_case_ids=None):
    rows = [json.loads(line) for line in draft.read_text().splitlines()]
    case_ids = [row["case_id"] for row in rows]
    return Approval(
        reviewer=reviewer,
        approved_at=datetime.now(UTC),
        draft_sha256=sha256_file(draft),
        review_artifact_sha256="a" * 64,
        reviewed_case_ids=(
            case_ids if reviewed_case_ids is None else reviewed_case_ids
        ),
    )


def test_review_uses_chinese_and_does_not_auto_approve(tmp_path, authored, suite):
    workspace, _, _, _ = authored
    report = validate_draft(suite, workspace / "draft.jsonl")
    output = tmp_path / "review.md"
    build_review(suite, workspace / "draft.jsonl", report, output)
    text = output.read_text()
    assert "# 人工审核清单：mini_agent_intent_v1" in text
    assert "本文档不代表数据集已获批准" in text
    assert "审核人：____________________" in text
    assert "## 自动校验结果" in text
    assert "## 案例审核清单" in text
    assert "## 人工审核声明" in text
    assert "Confirm every input" not in text


def test_approval_from_review_requires_every_case_checked(tmp_path, authored, suite):
    workspace, _, _, _ = authored
    draft = workspace / "draft.jsonl"
    report = validate_draft(suite, draft)
    review = tmp_path / "review.md"
    build_review(suite, draft, report, review)

    with pytest.raises(ValueError, match="review every case"):
        approval_from_review(draft, review, "YY")

    review.write_text(
        review.read_text().replace("- [ ] MINI-INTENT-", "- [x] MINI-INTENT-")
    )
    approval = approval_from_review(draft, review, "YY")

    assert approval.reviewer == "YY"
    assert len(approval.reviewed_case_ids) == 15
    assert approval.review_artifact_sha256 == sha256_file(review)


def test_review_and_freeze_append_bound_stage_records(tmp_path, authored, suite):
    workspace, _, _, _ = authored
    draft = workspace / "draft.jsonl"
    report = validate_draft(suite, draft, workspace)
    review = workspace / "review.md"
    build_review(suite, draft, report, review)
    review.write_text(
        review.read_text().replace("- [ ] MINI-INTENT-", "- [x] MINI-INTENT-")
    )
    approval = approval_from_review(draft, review, "YY")

    freeze_dataset(suite, draft, approval, tmp_path / "frozen.jsonl")
    ledger = StageLedger(workspace / "stage_ledger.jsonl")

    assert [record.stage_id for record in ledger.records] == [
        "prepare",
        "generate",
        "compile",
        "validate",
        "review",
        "freeze",
    ]
    assert ledger.records[-2].plugin.role == "review_renderer"
    assert ledger.records[-1].plugin.role == "dataset_freezer"


def test_approval_rejects_review_for_different_draft(tmp_path, authored, suite):
    workspace, _, _, _ = authored
    draft = workspace / "draft.jsonl"
    report = validate_draft(suite, draft)
    review = tmp_path / "review.md"
    build_review(suite, draft, report, review)
    review.write_text(
        review.read_text().replace("- [ ] MINI-INTENT-", "- [x] MINI-INTENT-")
    )
    draft.write_text(draft.read_text().replace("12031", "12032", 1))

    with pytest.raises(ValueError, match="draft hash"):
        approval_from_review(draft, review, "YY")


def test_blank_reviewer_rejected(authored):
    workspace, _, _, _ = authored
    with pytest.raises(ValueError, match="reviewer"):
        Approval(
            reviewer=" ",
            approved_at=datetime.now(UTC),
            draft_sha256=sha256_file(workspace / "draft.jsonl"),
            review_artifact_sha256="a" * 64,
            reviewed_case_ids=["CASE-001"],
        )


def test_invalid_draft_cannot_freeze(tmp_path, authored, suite):
    workspace, _, _, _ = authored
    draft = workspace / "draft.jsonl"
    rows = draft.read_text().splitlines()
    draft.write_text("\n".join(rows[:-1]) + "\n")
    approval = approval_for(draft, reviewer="Real Reviewer")
    with pytest.raises(ValueError, match="pass every gate"):
        freeze_dataset(suite, draft, approval, tmp_path / "frozen.jsonl")


def test_freezer_hash_manifest_and_no_overwrite(tmp_path, authored, suite):
    workspace, _, _, _ = authored
    draft = workspace / "draft.jsonl"
    digest = sha256_file(draft)
    report = ValidationSummary(
        state="VALIDATED",
        valid=True,
        draft_sha256=digest,
        case_count=15,
        gates=[GateResult(name="coverage", passed=True, details={"case_count": 15})],
    )
    approval = approval_for(draft)
    output = tmp_path / "module_intent_v1.jsonl"
    metadata = json.loads((workspace / "generation_manifest.json").read_text())
    dataset, manifest, coverage = freeze(
        suite, draft, approval, output, report, metadata
    )
    assert sha256_file(dataset) == digest
    assert manifest.exists() and coverage.exists()
    frozen_manifest = json.loads(manifest.read_text())
    assert frozen_manifest["approval"]["review_artifact_sha256"] == "a" * 64
    assert frozen_manifest["approval"]["reviewed_case_count"] == 15
    assert frozen_manifest["capability_bundle"]["bundle_format_version"] == "3.0"
    assert (
        frozen_manifest["capability_bundle"]["sha256"]
        == (metadata["capability_bundle_sha256"])
    )
    assert frozen_manifest["execution_profiles"] == {
        "shadow_full": {"allowed_tools": []}
    }
    with pytest.raises(FileExistsError):
        freeze(suite, draft, approval, output, report)


def test_prepare_and_generation_manifest_preserve_execution_profiles(authored, suite):
    workspace, request, _, _ = authored
    expected = {"shadow_full": {"allowed_tools": []}}

    assert request.model_dump(mode="json")["execution_profiles"] == expected
    manifest = json.loads((workspace / "generation_manifest.json").read_text())
    assert manifest["execution_profiles"] == expected


def test_freeze_rejects_generation_profile_drift(tmp_path, authored, suite):
    workspace, _, _, _ = authored
    draft = workspace / "draft.jsonl"
    metadata = json.loads((workspace / "generation_manifest.json").read_text())
    metadata["execution_profiles"] = {"other": {"allowed_tools": []}}
    report = ValidationSummary(
        state="VALIDATED",
        valid=True,
        draft_sha256=sha256_file(draft),
        case_count=15,
        gates=[GateResult(name="coverage", passed=True)],
    )

    with pytest.raises(ValueError, match="execution profile"):
        freeze(
            suite,
            draft,
            approval_for(draft),
            tmp_path / "frozen.jsonl",
            report,
            metadata,
        )


def test_freeze_rejects_profile_tool_not_in_selected_bundle(
    tmp_path, authored, suite
):
    workspace, _, _, _ = authored
    draft = workspace / "draft.jsonl"
    metadata = json.loads((workspace / "generation_manifest.json").read_text())
    metadata["execution_profiles"] = {
        "shadow_full": {"allowed_tools": ["not_selected"]}
    }
    changed_config = suite.config.model_copy(
        update={
            "execution_profiles": {
                "shadow_full": ExecutionProfileConfig(
                    allowed_tools=["not_selected"]
                )
            }
        }
    )
    changed_suite = replace(suite, config=changed_config)
    report = ValidationSummary(
        state="VALIDATED",
        valid=True,
        draft_sha256=sha256_file(draft),
        case_count=15,
        gates=[GateResult(name="coverage", passed=True)],
    )

    with pytest.raises(ValueError, match="not selected"):
        freeze(
            changed_suite,
            draft,
            approval_for(draft),
            tmp_path / "frozen.jsonl",
            report,
            metadata,
        )


def test_freezer_rejects_incomplete_case_review(tmp_path, authored, suite):
    workspace, _, _, _ = authored
    draft = workspace / "draft.jsonl"
    digest = sha256_file(draft)
    report = ValidationSummary(
        state="VALIDATED",
        valid=True,
        draft_sha256=digest,
        case_count=15,
        gates=[GateResult(name="coverage", passed=True, details={"case_count": 15})],
    )
    approval = approval_for(draft, reviewed_case_ids=["MINI-INTENT-001"])

    with pytest.raises(ValueError, match="review every case"):
        freeze(suite, draft, approval, tmp_path / "frozen.jsonl", report)


def test_generation_metadata_cannot_override_frozen_manifest_fields(
    tmp_path, authored, suite
):
    workspace, _, _, _ = authored
    draft = workspace / "draft.jsonl"
    digest = sha256_file(draft)
    report = ValidationSummary(
        state="VALIDATED",
        valid=True,
        draft_sha256=digest,
        case_count=15,
        gates=[GateResult(name="coverage", passed=True, details={"case_count": 15})],
    )
    approval = approval_for(draft)
    output = tmp_path / "module_intent_v1.jsonl"

    metadata = json.loads((workspace / "generation_manifest.json").read_text())
    metadata.update({"state": "VALIDATED", "dataset_version": "untrusted"})
    _, manifest, _ = freeze(
        suite,
        draft,
        approval,
        output,
        report,
        metadata,
    )

    frozen = json.loads(manifest.read_text())
    assert frozen["state"] == "FROZEN"
    assert frozen["dataset_version"] == suite.dataset_version
