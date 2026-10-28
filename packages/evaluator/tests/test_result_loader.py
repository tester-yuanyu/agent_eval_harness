from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from conftest import intent
from support.model_client import DeterministicModelClient

from eval_framework.result_loader import load_run_result
from eval_framework.runner import run_evaluation
from eval_framework.schemas import EvaluationRunResult, RunConfig


def test_load_run_result_accepts_directory_and_preserves_source(
    dataset_path: Path,
    tmp_path: Path,
):
    dataset = __import__("eval_framework").load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    with pytest.warns(DeprecationWarning):
        result = run_evaluation(
            dataset,
            RunConfig(run_mode="framework_self_test"),
            lambda execution: DeterministicModelClient([intent()]),
        )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    result_path = run_dir / "results.json"
    legacy_payload = result.model_dump(mode="json")
    legacy_payload.pop("judge_metadata")
    legacy_payload.pop("stability")
    result_path.write_text(
        json.dumps(legacy_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    before = hashlib.sha256(result_path.read_bytes()).hexdigest()

    loaded = load_run_result(run_dir)

    assert loaded.sha256 == before
    assert loaded.source_path == str(result_path.resolve())
    assert loaded.result.trials_per_case == 1
    assert loaded.result.judge_metadata is None
    assert loaded.result.stability is None
    assert loaded.result.cases[0].deterministic_score == result.cases[0].score
    assert hashlib.sha256(result_path.read_bytes()).hexdigest() == before


def test_load_run_result_migrates_legacy_agent_version(
    dataset_path: Path,
    tmp_path: Path,
):
    dataset = __import__("eval_framework").load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    with pytest.warns(DeprecationWarning):
        result = run_evaluation(
            dataset,
            RunConfig(run_mode="framework_self_test"),
            lambda execution: DeterministicModelClient([intent()]),
        )
    payload = result.model_dump(mode="json")
    payload["mini_agent_version"] = payload.pop("agent_version")
    path = tmp_path / "results.json"
    path.write_text(
        EvaluationRunResult.model_validate(payload).model_dump_json(indent=2),
        encoding="utf-8",
    )

    assert load_run_result(path).result.agent_version == result.agent_version
