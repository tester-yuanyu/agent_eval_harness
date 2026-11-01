"""Real GEval translation with an HTTP-only stub; no model services are called."""

import json
import subprocess
from copy import deepcopy

import httpx
import openai
import pytest

from eval_framework.benchmark import judging


@pytest.fixture
def evidence():
    task = {
        "id": "case",
        "prompt": "Read a then write b.",
        "followups": ["Change b."],
        "oracle": {"expected_files": {"b": "PRIVATE_ORACLE"}},
        "checkpoints": [{"secret": "PRIVATE_CHECKPOINT"}],
    }
    events = [
        {
            "id": "t1",
            "type": "turn",
            "input": task["prompt"],
            "output": "Created b.",
            "snapshot": {"b": "FIRST_STATE"},
        },
        {
            "id": "g1",
            "type": "generation",
            "parent_id": "t1",
            "input": {"messages": [{"role": "user", "content": task["prompt"]}]},
            "output": {
                "tool_calls": [{"name": "read_file", "arguments": {"path": "a"}}]
            },
        },
        {
            "id": "r1",
            "type": "tool",
            "parent_id": "t1",
            "name": "read_file",
            "input": {"path": "a"},
            "output": "Error: missing file",
            "error": "missing file",
        },
        {
            "id": "g2",
            "type": "generation",
            "parent_id": "t1",
            "input": {
                "messages": [
                    {"role": "user", "content": task["prompt"]},
                    {"role": "tool", "content": "Error: missing file"},
                ]
            },
            "output": {"content": "Cannot read a."},
        },
        {
            "id": "t2",
            "type": "turn",
            "input": "Change b.",
            "output": "Changed b.",
            "snapshot": {"b": "FUTURE_STATE"},
        },
        {
            "id": "g3",
            "type": "generation",
            "parent_id": "t2",
            "input": {"messages": [{"role": "user", "content": "Change b."}]},
            "output": {"content": "Changed b."},
        },
    ]
    observation = {
        "status": "completed",
        "evidence_complete": True,
        "execution_kind": "real_agent",
        "events": events,
        "turns": [
            {
                "input": task["prompt"],
                "output": "Created b.",
                "snapshot": {"b": "FIRST_STATE"},
            },
            {
                "input": "Change b.",
                "output": "Changed b.",
                "snapshot": {"b": "FUTURE_STATE"},
            },
        ],
        "final_files": {"b": "FUTURE_STATE"},
    }
    return task, observation


@pytest.fixture
def judge_transport(monkeypatch):
    requests = []
    original = openai.OpenAI

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "judge",
                "object": "chat.completion",
                "created": 0,
                "model": "test-judge",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": (
                                '{"score": 7, "reason": "Evidence partly '
                                'supports the action."}'
                            ),
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 40,
                    "completion_tokens": 10,
                    "total_tokens": 50,
                },
            },
        )

    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **kw: original(
            **kw, http_client=httpx.Client(transport=httpx.MockTransport(respond))
        ),
    )
    return requests, {
        "model": "test-judge",
        "api_key": "SECRET_KEY",
        "base_url": "https://judge.invalid/v1",
    }


def test_real_geval_scopes_normalization_and_private_data_exclusion(
    evidence, judge_transport
):
    task, observation = evidence
    requests, config = judge_transport
    original = deepcopy((task, observation))
    records = judging.judge_observation(
        task, observation, config, dimensions=list(judging.GEVAL_DIMENSIONS)
    )
    assert len(requests) == 6  # 3 decisions + 1 recovery + 2 responses
    assert len(records) == 6
    assert all(
        r["score"] == pytest.approx(0.7) and r["status"] == "SCORED" for r in records
    )
    assert all(
        r["formal"] is False and r["threshold"] is None and r["success"] is None
        for r in records
    )
    assert all(
        r["calibration"] == "not_calibrated" and r["rubric_sha256"] for r in records
    )
    response = next(
        r
        for r in records
        if r["name"] == "response_groundedness" and r["event_id"] == "t1"
    )
    assert "FIRST_STATE" in response["events"][0]["input"]
    assert "FUTURE_STATE" not in response["events"][0]["input"]
    action = next(
        r
        for r in records
        if r["name"] == "action_appropriateness" and r["event_id"] == "g1"
    )
    assert "FIRST_STATE" not in action["events"][0]["input"]
    assert "FUTURE_STATE" not in action["events"][0]["input"]
    assert "Change b." not in action["events"][0]["input"]
    assert "PRIVATE_ORACLE" not in json.dumps(requests)
    assert "PRIVATE_CHECKPOINT" not in json.dumps(requests)
    assert "SECRET_KEY" not in json.dumps(records)
    assert (task, observation) == original


def test_no_error_recovery_is_not_applicable(evidence, judge_transport):
    task, observation = evidence
    observation["events"] = [e for e in observation["events"] if e["id"] != "r1"]
    requests, config = judge_transport
    records = judging.judge_observation(
        task, observation, config, dimensions=["recovery_appropriateness"]
    )
    assert not requests
    assert len(records) == 1
    assert records[0]["status"] == "NOT_APPLICABLE"
    assert records[0]["score"] is None
    summary = judging.summarize_judgments(records)
    assert summary["coverage"] is None
    assert summary["applicable"] == 0


def test_missing_turn_snapshot_is_missing_not_final_state_substitution(
    evidence, judge_transport
):
    task, observation = evidence
    observation["events"][0].pop("snapshot")
    observation["turns"][0].pop("snapshot")
    requests, config = judge_transport
    records = judging.judge_observation(
        task, observation, config, dimensions=["response_groundedness"]
    )
    assert len(requests) == 1
    assert records[0]["status"] == "MISSING"
    assert records[0]["score"] is None
    assert judging.summarize_judgments(records)["coverage"] == 0.5


def test_call_budget_preserves_unscored_population(evidence, judge_transport):
    task, observation = evidence
    requests, config = judge_transport
    records = judging.judge_observation(
        task,
        observation,
        config,
        dimensions=["action_appropriateness"],
        max_evaluations=1,
    )
    assert len(requests) == 1
    assert [r["status"] for r in records] == ["SCORED", "MISSING", "MISSING"]
    assert judging.summarize_judgments(records)["coverage"] == pytest.approx(1 / 3)


def test_native_calls_share_actual_request_budget_with_geval(
    evidence, judge_transport, monkeypatch
):
    requests, config = judge_transport
    seen = {}

    def native(task, observation, model_config, *, dimensions, max_model_requests):
        seen.update(
            dimensions=dimensions,
            maximum=max_model_requests,
            config=model_config,
        )
        return [
            {
                "metric_id": "native-step",
                "name": "step_efficiency",
                "backend": "deepeval",
                "implementation": "StepEfficiencyMetric",
                "version": "trajectory-native-v1",
                "scope": "chain",
                "event_id": None,
                "evidence_ids": ["t1"],
                "status": "SCORED",
                "formal": False,
                "calibration": "not_calibrated",
                "score": 0.8,
                "success": None,
                "threshold": None,
                "reason": "Efficient enough.",
                "errors": [],
                "events": [
                    {"input": "derive task", "output": {}, "usage": {}},
                    {"input": "score steps", "output": {}, "usage": {}},
                ],
            }
        ]

    monkeypatch.setattr(judging, "run_agentic_metrics_worker", native)
    records = judging.judge_observation(
        *evidence,
        config,
        dimensions=["step_efficiency", "action_appropriateness"],
        max_evaluations=3,
    )

    assert seen["dimensions"] == ["step_efficiency"]
    assert seen["maximum"] == 3
    assert len(requests) == 1
    assert [record["status"] for record in records] == [
        "SCORED",
        "SCORED",
        "MISSING",
        "MISSING",
    ]
    assert all(record["model"] == "test-judge" for record in records)


def test_native_worker_failure_is_empty_error_score(evidence, monkeypatch):
    monkeypatch.setattr(
        judging,
        "run_agentic_metrics_worker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("worker died")),
    )
    records = judging.judge_observation(
        *evidence,
        {"model": "judge", "api_key": "SECRET"},
        dimensions=["task_completion"],
        max_evaluations=2,
    )

    assert len(records) == 1
    assert records[0]["status"] == "ERROR"
    assert records[0]["score"] is None
    assert records[0]["success"] is None
    assert "RuntimeError" in records[0]["reason"]


def test_native_worker_failure_exhausts_unknown_finite_budget_before_geval(
    evidence, judge_transport, monkeypatch
):
    requests, config = judge_transport
    monkeypatch.setattr(
        judging,
        "run_agentic_metrics_worker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("native-worker", 1)
        ),
    )

    records = judging.judge_observation(
        *evidence,
        config,
        dimensions=["task_completion", "action_appropriateness"],
        max_evaluations=3,
    )

    assert requests == []
    assert records[0]["name"] == "task_completion"
    assert records[0]["status"] == "ERROR"
    assert records[0]["model_requests"] is None
    assert records[0]["model_requests_known_subtotal"] == 0
    assert records[0]["model_requests_unknown"] is True
    assert [record["status"] for record in records[1:]] == [
        "MISSING",
        "MISSING",
        "MISSING",
    ]


def test_missing_credentials_are_error_records_not_zero(evidence, monkeypatch):
    monkeypatch.delenv("UNCONFIGURED_JUDGE", raising=False)
    records = judging.judge_observation(
        *evidence,
        {"model": "test", "api_key_env": "UNCONFIGURED_JUDGE"},
        dimensions=["response_groundedness"],
    )
    assert all(r["status"] == "ERROR" and r["score"] is None for r in records)
    assert judging.summarize_judgments(records)["coverage"] == 0


def test_module_execution_has_no_llm_behavior_judge(evidence, judge_transport):
    task, observation = evidence
    observation["execution_kind"] = "real_module"
    requests, config = judge_transport
    records = judging.judge_observation(task, observation, config)
    assert not requests
    assert all(r["status"] == "NOT_APPLICABLE" for r in records)


def test_repeated_scores_join_by_metric_identity():
    a = {
        "metric_id": "a",
        "name": "response_groundedness",
        "status": "SCORED",
        "score": 0.2,
    }
    b = {**a, "score": 0.8}
    summary = judging.summarize_repeated_judgments([[a], [b]])
    assert summary["matched_metrics"] == 1
    assert summary["mean_range"] == pytest.approx(0.6)
    assert summary["items"][0]["repetitions"] == 2


def test_failed_http_attempt_retains_call_evidence_without_score(evidence, monkeypatch):
    original = openai.OpenAI

    def factory(**kwargs):
        return original(
            **kwargs,
            http_client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        503, json={"error": {"message": "unavailable"}}
                    )
                )
            ),
        )

    monkeypatch.setattr(openai, "OpenAI", factory)
    records = judging.judge_observation(
        *evidence,
        {"model": "test", "api_key": "SECRET"},
        dimensions=["action_appropriateness"],
        max_evaluations=1,
    )
    assert records[0]["status"] == "ERROR"
    assert records[0]["score"] is None
    assert len(records[0]["events"]) == 1
    assert records[0]["events"][0]["error"] == "InternalServerError"
    assert records[0]["events"][0]["usage"]["cost_usd"] is None


def test_absent_error_evidence_is_not_assumed_no_recovery_needed(evidence):
    task, observation = evidence
    observation["events"] = []
    observation["evidence_complete"] = False
    records = judging.judge_observation(
        task, observation, {"model": "test"}, dimensions=["recovery_appropriateness"]
    )
    assert records[0]["status"] == "MISSING"
    assert judging.summarize_judgments(records)["coverage"] == 0


def test_later_response_keeps_prior_evidence_but_first_turn_has_no_future(
    evidence, judge_transport
):
    requests, config = judge_transport
    result = judging.judge_observation(
        *evidence, config, dimensions=["response_groundedness"]
    )
    assert "Error: missing file" in result[1]["events"][0]["input"]
    assert "r1" in result[1]["evidence_ids"]
    assert "FUTURE_STATE" not in result[0]["events"][0]["input"]


def test_unproven_or_incomplete_critical_evidence_cannot_make_recovery_na(
    evidence, judge_transport
):
    task, observation = evidence
    observation["events"] = [
        event for event in observation["events"] if event["id"] != "r1"
    ]
    observation.pop("evidence_complete", None)
    observation["events"][1]["incomplete"] = True
    requests, config = judge_transport
    records = judging.judge_observation(
        task, observation, config, dimensions=["recovery_appropriateness"]
    )
    assert not requests
    assert records[0]["status"] == "MISSING"
    observation["evidence_complete"] = True
    records = judging.judge_observation(
        task, observation, config, dimensions=["recovery_appropriateness"]
    )
    assert records[0]["status"] == "MISSING"
