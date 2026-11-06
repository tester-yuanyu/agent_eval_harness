"""评分插件必须消费可信证据，缺失终态不能由参考答案补齐。"""

from copy import deepcopy
from importlib import import_module, util

import pytest


def scorers():
    name = "eval_framework.benchmark.scorers"
    assert util.find_spec(name) is not None, "Scorer implementation is required"
    return import_module(name)


@pytest.fixture
def evidence():
    task = {
        "id": "example",
        "prompt": "Read value.txt",
        "followups": [],
        "allowed_tools": ["read_file"],
        "required_tools": [],
        "fixtures": {"value.txt": "value=42\n"},
        "oracle": {"response_contains": ["RESULT=42"]},
        "reference": [
            {
                "op": "answer",
                "kind": "line_value",
                "path": "value.txt",
                "key": "value",
                "prefix": "RESULT=",
            }
        ],
    }
    observation = {
        "status": "completed",
        "evidence_complete": True,
        "before_files": {"value.txt": "value=42\n"},
        "final_files": {"value.txt": "value=42\n"},
        "turns": [{"input": "Read value.txt", "output": "RESULT=42"}],
        "events": [],
    }
    return task, observation


def test_executable_scorer_uses_observed_state_and_preserves_inputs(evidence):
    task, observation = evidence
    before = deepcopy((task, observation))
    scorer = scorers().ExecutableScorer()
    result = scorer.score([], observation, task)
    assert result["success"] is True
    assert result["grader_version"] == "file-tools-oracle-v1"
    assert (task, observation) == before
    observation["final_files"]["value.txt"] = "wrong"
    assert scorer.score([], observation, task)["success"] is False


def test_executable_scorer_does_not_treat_a_snapshot_as_complete_evidence(evidence):
    task, observation = evidence
    result = scorers().ExecutableScorer().score([], observation["final_files"], task)
    assert result["success"] is None
    assert result["verdict"] == "INVALID"


def test_explicit_trace_is_used_instead_of_stale_envelope_events(evidence):
    task, observation = evidence
    task["oracle"]["module_results"] = [
        {"call": 1, "error": False, "output_contains": ["42"]}
    ]
    event = {
        "type": "tool",
        "name": "read_file",
        "input": {},
        "output": "42",
        "is_error": False,
    }
    assert scorers().ExecutableScorer().score([event], observation, task)["success"]
    assert observation["events"] == []


def test_reference_exact_match_is_optional_diagnostic_and_missing_is_unknown(evidence):
    task, observation = evidence
    scorer = scorers().ReferenceScorer()
    result = scorer.score([], observation, task)
    assert result["success"] is True
    assert result["formal"] is False
    assert result["strategy"] == "exact"
    observation["turns"][0]["output"] = "RESULT=420"
    assert scorer.score([], observation, task)["success"] is False
    observation.pop("final_files")
    missing = scorer.score([], observation, task)
    assert missing["success"] is None
    assert missing["verdict"] == "INCONCLUSIVE"
    task.pop("reference")
    assert scorer.score([], observation, task)["success"] is None


def test_llm_judge_scorer_keeps_non_agent_execution_unscored(evidence):
    task, observation = evidence
    observation["execution_kind"] = "real_module"
    result = (
        scorers()
        .LLMJudgeScorer({}, dimensions=["action_appropriateness"])
        .score([], observation, task)
    )
    assert result["formal"] is False
    assert result["metrics"][0]["status"] == "NOT_APPLICABLE"
    assert result["metrics"][0]["score"] is None
    assert result["metrics"][0]["events"] == []


def test_reference_missing_execution_status_does_not_become_measured_failure(evidence):
    task, observation = evidence
    observation.pop("status")
    result = scorers().ReferenceScorer().score([], observation, task)
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["success"] is None


def test_reference_does_not_derive_actual_evidence_from_private_oracle(evidence):
    task, observation = evidence
    task["oracle"] = {"expected_files": {"value.txt": "SECRET"}}
    assert scorers().ReferenceScorer().score([], observation, task)["success"] is True


def test_reference_failed_recipe_is_unscored(evidence):
    task, observation = evidence
    task["reference"] = [
        {
            "op": "answer",
            "kind": "regex",
            "path": "value.txt",
            "pattern": "does-not-match",
        }
    ]
    result = scorers().ReferenceScorer().score([], observation, task)
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["success"] is None


@pytest.mark.parametrize(
    ("mutation", "verdict", "validity"),
    [
        ({"evidence_complete": False}, "INCONCLUSIVE", "VALID"),
        ({"errors": [{"kind": "provider"}]}, "INVALID", "INVALID"),
        ({"errors": [{"kind": "harness"}]}, "INVALID", "INVALID"),
        ({"errors": [{"kind": "environment"}]}, "INVALID", "INVALID"),
        ({"final_files": None}, "INCONCLUSIVE", "VALID"),
    ],
)
def test_public_executable_scorer_gates_missing_or_infrastructure_evidence(
    evidence, mutation, verdict, validity
):
    task, observation = evidence
    observation.update(mutation)
    result = scorers().ExecutableScorer().score([], observation, task)
    assert result["success"] is None
    assert result["verdict"] == verdict
    assert result["validity"] == validity
    assert result["checks"] == []
    assert result["evidence_refs"] == []


def test_public_executable_verdict_is_scoped_to_oracle_and_keeps_evidence_ids(evidence):
    task, observation = evidence
    event = {
        "id": "tool-1",
        "type": "tool",
        "name": "read_file",
        "input": {},
        "output": "42",
    }
    result = scorers().ExecutableScorer().score([event], observation, task)
    assert result["verdict"] == "PASS"
    assert result["validity"] == "VALID"
    assert result["success"] is True
    assert result["evidence_refs"] == ["tool-1"]
    observation["turns"][0]["output"] = "wrong"
    assert (
        scorers().ExecutableScorer().score([event], observation, task)["verdict"]
        == "FAIL"
    )


def test_raw_legacy_oracle_does_not_acquire_new_public_plugin_fields(evidence):
    from eval_framework.benchmark.oracle import evaluate_oracle

    task, observation = evidence
    observation["evidence_complete"] = False
    result = scorers().ExecutableScorer().score_observation(task, observation)
    assert result == evaluate_oracle(task, observation)
    assert set(result) == {"success", "checks", "violations", "grader_version"}
    assert result["success"] is True


def test_diagnostic_scorers_expose_common_shape_without_formal_judge_pass(evidence):
    task, observation = evidence
    event = {"id": "turn-1", "type": "turn", "turn": 1}
    reference = scorers().ReferenceScorer().score([event], observation, task)
    assert reference["evidence_refs"] == ["turn-1"]
    assert reference["validity"] == "VALID"
    observation["execution_kind"] = "real_module"
    judged = (
        scorers()
        .LLMJudgeScorer({}, dimensions=["action_appropriateness"])
        .score([event], observation, task)
    )
    assert judged["evidence_refs"] == ["turn-1"]
    assert judged["checks"] == []
    assert judged["verdict"] == "INCONCLUSIVE"
    assert judged["success"] is None
    assert judged["formal"] is False
