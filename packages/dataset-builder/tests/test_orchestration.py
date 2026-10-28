from __future__ import annotations

import pytest

from dataset_builder.orchestration import (
    PipelineEngine,
    PolicyBinding,
    StageExecutionError,
    StageInput,
    StageInputMismatchError,
    StageLedger,
)
from dataset_builder.pipeline import prepare_generation
from dataset_builder.plugins import PluginKey
from dataset_builder.suite_definition import load_suite


def _inputs(capability_hash: str = "a" * 64) -> tuple[StageInput, ...]:
    return (StageInput(name="capability_bundle", sha256=capability_hash),)


def _policies(policy_hash: str = "b" * 64) -> tuple[PolicyBinding, ...]:
    return (
        PolicyBinding(
            kind="generation",
            version="1.0",
            path="policies/generation.json",
            sha256=policy_hash,
            schema_sha256="c" * 64,
        ),
    )


def _key() -> PluginKey:
    return PluginKey("case_generator", "dataset-builder-core", "1.0")


def test_stage_hashes_are_deterministic_and_bind_exact_inputs(tmp_path):
    left = PipelineEngine(StageLedger(tmp_path / "left.jsonl"))
    right = PipelineEngine(StageLedger(tmp_path / "right.jsonl"))

    first = left.run_stage(
        "generate", _key(), _inputs(), _policies(), lambda: {"cases": [1, 2]}
    )
    second = right.run_stage(
        "generate", _key(), _inputs(), _policies(), lambda: {"cases": [1, 2]}
    )

    assert first.sha256 == second.sha256
    assert left.ledger.records[0].input_fingerprint == (
        right.ledger.records[0].input_fingerprint
    )
    assert left.ledger.records[0].plugin == _key()
    assert left.ledger.records[0].inputs == _inputs()
    assert left.ledger.records[0].policy_bindings == _policies()


def test_stage_ids_are_append_only_and_cannot_be_reused_with_changed_inputs(tmp_path):
    engine = PipelineEngine(StageLedger(tmp_path / "ledger.jsonl"))
    engine.run_stage("generate", _key(), _inputs(), _policies(), lambda: {"ok": True})

    with pytest.raises(ValueError, match="already recorded"):
        engine.run_stage(
            "generate", _key(), _inputs(), _policies(), lambda: {"ok": True}
        )
    with pytest.raises(StageInputMismatchError, match="input fingerprint"):
        engine.ledger.assert_reusable(
            "generate", _key(), _inputs("d" * 64), _policies()
        )
    with pytest.raises(StageInputMismatchError, match="input fingerprint"):
        engine.ledger.assert_reusable(
            "generate", _key(), _inputs(), _policies("e" * 64)
        )


def test_stage_failure_is_structured_and_persisted(tmp_path):
    engine = PipelineEngine(StageLedger(tmp_path / "ledger.jsonl"))

    def fail():
        raise RuntimeError("generator unavailable")

    with pytest.raises(StageExecutionError, match="generator unavailable"):
        engine.run_stage("generate", _key(), _inputs(), _policies(), fail)

    record = engine.ledger.records[0]
    assert record.status == "failed"
    assert record.error_type == "RuntimeError"
    assert record.error_message == "generator unavailable"
    assert record.output_sha256 is None


def test_reusable_stage_requires_successful_matching_record(tmp_path):
    engine = PipelineEngine(StageLedger(tmp_path / "ledger.jsonl"))
    output = engine.run_stage(
        "generate", _key(), _inputs(), _policies(), lambda: {"ok": True}
    )

    record = engine.ledger.assert_reusable(
        "generate", _key(), _inputs(), _policies()
    )

    assert record.status == "succeeded"
    assert record.output_sha256 == output.sha256


def test_prepare_stage_records_plugin_and_request_bindings(tmp_path):
    suite = load_suite("mini_agent_query_user_intent_v1")

    request = prepare_generation(suite, tmp_path)
    ledger = StageLedger(tmp_path / "stage_ledger.jsonl")

    assert {item["role"] for item in request.plugin_bindings} == {
        "capability_adapter",
        "snapshot_loader",
        "capability_resolver",
        "source_pack_compiler",
        "coverage_planner",
        "case_generator",
        "validation_gate",
        "review_renderer",
        "dataset_freezer",
    }
    assert request.policy_bindings == list(suite.policy_bindings)
    assert {item["kind"] for item in request.policy_bindings} == {
        "source",
        "coverage",
        "generation",
        "validation",
        "review",
        "freeze",
    }
    assert [record.stage_id for record in ledger.records] == ["prepare"]
    assert ledger.records[0].plugin.role == "source_pack_compiler"
    assert [vars(item) for item in ledger.records[0].policy_bindings] == (
        request.policy_bindings
    )
