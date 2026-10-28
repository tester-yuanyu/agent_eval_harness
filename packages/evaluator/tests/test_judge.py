from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import module_case
from support.judge_client import ScriptedJudgeClient
from support.model_client import DeterministicModelClient

from eval_framework.cli import _parser
from eval_framework.judge import (
    JudgeInvocationError,
    JudgeTimeoutError,
    evaluate_trial_with_judge,
    load_judge_rubric,
    resolve_quality_conclusion,
)
from eval_framework.phase2_schemas import (
    JudgeCaseSpec,
    JudgeDimensionSpec,
    JudgeResult,
    JudgeRunConfig,
)
from eval_framework.provider import EvaluationPreflightError
from eval_framework.runner import run_evaluation
from eval_framework.schemas import AssertionResult, EvalCase, RunConfig


def rubric_file(tmp_path: Path) -> Path:
    path = tmp_path / "rubric.json"
    path.write_text(
        json.dumps(
            {
                "rubric_id": "semantic-response",
                "version": "1.0",
                "prompt_version": "judge-prompt-v1",
                "output_schema_version": "judge-output-v1",
                "dimensions": [
                    {"name": "clarity", "instruction": "Score clarity."},
                    {"name": "completeness", "instruction": "Score completeness."},
                ],
                "max_text_chars": 4000,
            }
        ),
        encoding="utf-8",
    )
    return path


def judged_case() -> EvalCase:
    payload = module_case()
    payload["oracle"]["judge"] = {
        "rubric_id": "semantic-response",
        "rubric_version": "1.0",
        "dimensions": [
            {"name": "clarity", "weight": 1, "threshold": 80},
            {"name": "completeness", "weight": 3, "threshold": 70},
        ],
        "reference_facts": {
            "expected": "fixture found",
            "api_key": "must-not-leak",
        },
        "required": True,
    }
    return EvalCase.model_validate(payload)


def judge_candidate(clarity=90, completeness=80):
    return {
        "dimensions": [
            {"name": "clarity", "score": clarity, "reason": "clear"},
            {
                "name": "completeness",
                "score": completeness,
                "reason": "complete",
            },
        ],
        "token_usage": {"input_tokens": 12, "output_tokens": 8},
    }


def case_result(case_result_factory):
    return case_result_factory(
        turn_results=[
            {
                "run_id": "run-1",
                "status": "SUCCESS",
                "tool_calls": [],
                "events": [],
                "final_response": "fixture found",
            }
        ]
    )


def test_judge_scores_declared_dimensions_and_redacts_secret_keys(
    tmp_path,
    case_result_factory,
):
    client = ScriptedJudgeClient([judge_candidate()])
    rubric = load_judge_rubric(rubric_file(tmp_path))

    result = evaluate_trial_with_judge(
        judged_case(),
        case_result(case_result_factory),
        JudgeRunConfig(rubric_path=str(rubric_file(tmp_path)), max_retries=0),
        client,
        rubric,
    )

    assert result.status == "COMPLETED"
    assert result.score == 82.5
    assert result.passed is True
    assert result.token_usage == {"input_tokens": 12, "output_tokens": 8}
    request_json = client.requests[0].model_dump_json()
    assert "must-not-leak" not in request_json
    assert "[REDACTED]" in request_json
    assert client.requests[0].dimension_instructions == {
        "clarity": "Score clarity.",
        "completeness": "Score completeness.",
    }


def test_judge_retries_only_temporary_invocation_errors(
    tmp_path,
    case_result_factory,
):
    client = ScriptedJudgeClient(
        [JudgeInvocationError("temporary", temporary=True), judge_candidate()]
    )

    result = evaluate_trial_with_judge(
        judged_case(),
        case_result(case_result_factory),
        JudgeRunConfig(rubric_path=str(rubric_file(tmp_path)), max_retries=1),
        client,
        load_judge_rubric(rubric_file(tmp_path)),
    )

    assert result.status == "COMPLETED"
    assert len(result.attempts) == 2
    assert len(client.requests) == 2


def test_required_judge_timeout_is_inconclusive_but_cannot_override_failure():
    spec = JudgeCaseSpec(
        rubric_id="semantic-response",
        rubric_version="1.0",
        dimensions=[JudgeDimensionSpec(name="clarity", weight=1, threshold=80)],
        required=True,
    )
    timeout = JudgeResult(status="MODEL_TIMEOUT", error="timed out")
    passing = [AssertionResult(name="x", weight=1, critical=True, passed=True)]
    failing = [AssertionResult(name="x", weight=1, critical=True, passed=False)]

    assert resolve_quality_conclusion("PASS", passing, spec, timeout) == "INCONCLUSIVE"
    assert resolve_quality_conclusion("FAIL", failing, spec, timeout) == "FAIL"


def test_timeout_is_not_retried_when_retry_budget_is_zero(
    tmp_path,
    case_result_factory,
):
    client = ScriptedJudgeClient([JudgeTimeoutError("timed out")])

    result = evaluate_trial_with_judge(
        judged_case(),
        case_result(case_result_factory),
        JudgeRunConfig(rubric_path=str(rubric_file(tmp_path)), max_retries=0),
        client,
        load_judge_rubric(rubric_file(tmp_path)),
    )

    assert result.status == "MODEL_TIMEOUT"
    assert len(client.requests) == 1


def test_rubric_identity_must_match_case(tmp_path, case_result_factory):
    case = judged_case()
    case.oracle.judge.rubric_version = "2.0"

    with pytest.raises(ValueError, match="rubric"):
        evaluate_trial_with_judge(
            case,
            case_result(case_result_factory),
            JudgeRunConfig(rubric_path=str(rubric_file(tmp_path))),
            ScriptedJudgeClient([judge_candidate()]),
            load_judge_rubric(rubric_file(tmp_path)),
        )


def test_runner_records_judge_result_and_applies_required_failure(
    dataset_path,
    tmp_path,
):
    from conftest import intent

    from eval_framework import load_dataset

    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    dataset.cases[0] = judged_case()
    client = ScriptedJudgeClient([judge_candidate(clarity=70, completeness=80)])
    config = RunConfig(
        run_mode="framework_self_test",
        judge=JudgeRunConfig(
            rubric_path=str(rubric_file(tmp_path)),
            max_retries=0,
        ),
    )

    with pytest.warns(DeprecationWarning):
        result = run_evaluation(
            dataset,
            config,
            lambda execution: DeterministicModelClient([intent()]),
            judge_client=client,
        )

    assert result.cases[0].judge_result.status == "COMPLETED"
    assert result.cases[0].judge_result.passed is False
    assert result.cases[0].quality_conclusion == "FAIL"
    assert result.cases[0].score == 100
    assert result.judge_metadata["rubric_sha256"]


def test_runner_rejects_enabled_judge_before_agent_runtime_without_client(
    dataset_path,
    tmp_path,
):
    from eval_framework import load_dataset

    calls = 0

    def factory(execution):
        nonlocal calls
        calls += 1
        raise AssertionError(execution)

    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    dataset.cases[0] = judged_case()
    config = RunConfig(
        run_mode="framework_self_test",
        judge=JudgeRunConfig(rubric_path=str(rubric_file(tmp_path))),
    )

    with pytest.warns(DeprecationWarning):
        with pytest.raises(EvaluationPreflightError, match="Judge client"):
            run_evaluation(dataset, config, factory)

    assert calls == 0


def test_runner_validates_case_rubric_before_agent_runtime(dataset_path, tmp_path):
    from eval_framework import load_dataset

    calls = 0

    def factory(execution):
        nonlocal calls
        calls += 1
        raise AssertionError(execution)

    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    case = judged_case()
    case.oracle.judge.rubric_version = "2.0"
    dataset.cases[0] = case
    config = RunConfig(
        run_mode="framework_self_test",
        judge=JudgeRunConfig(rubric_path=str(rubric_file(tmp_path))),
    )

    with pytest.warns(DeprecationWarning):
        with pytest.raises(EvaluationPreflightError, match="rubric"):
            run_evaluation(
                dataset,
                config,
                factory,
                judge_client=ScriptedJudgeClient([judge_candidate()]),
            )

    assert calls == 0


def test_run_cli_accepts_judge_config():
    args = _parser().parse_args(
        [
            "run",
            "--dataset",
            "cases.jsonl",
            "--output-dir",
            "artifacts",
            "--judge-config",
            "rubric.json",
        ]
    )

    assert args.judge_config == "rubric.json"
