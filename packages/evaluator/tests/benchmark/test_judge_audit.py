"""Failure audit preserves attempted requests without duplicating parsed failures."""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError


class Answer(BaseModel):
    score: float


@pytest.mark.parametrize("kind", ["shared", "trajectory", "native"])
@pytest.mark.parametrize("outcome", ["http_error", "invalid_json", "success"])
def test_audited_judge_records_one_attempt_with_original_usage(kind, outcome):
    from eval_framework.benchmark.scorers.agentic_metrics_worker import (
        _AuditedNativeJudge,
    )
    from eval_framework.benchmark.scorers.judge_client import AuditedJudge
    from eval_framework.benchmark.scorers.trajectory_judge import _AuditedJudge

    judge_type = {
        "shared": AuditedJudge,
        "trajectory": _AuditedJudge,
        "native": _AuditedNativeJudge,
    }[kind]
    judge = judge_type.__new__(judge_type)
    judge.model_name, judge.max_tokens, judge.extra_body = "offline", 100, {}
    judge.calls = []

    def create(**kwargs):
        if outcome == "http_error":
            raise OSError("offline transport failure")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"score": 0.5}'
                        if outcome == "success"
                        else "invalid JSON"
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
            model="offline-response",
        )

    judge.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    if outcome == "success":
        assert judge.generate("evaluate", schema=Answer).score == 0.5
    else:
        with pytest.raises(OSError if outcome == "http_error" else ValidationError):
            judge.generate("evaluate", schema=Answer)
    assert len(judge.calls) == 1
    event = judge.calls[0]
    assert event["input"].startswith("evaluate\nReturn only a JSON object")
    assert event["start_time"] <= event["end_time"]
    if outcome == "http_error":
        assert event["error"] == "OSError"
        assert event["output"] is None
        assert event["usage"] == {
            "input_tokens": None,
            "output_tokens": None,
            "cost_usd": None,
        }
        assert event["name"] == (
            "deepeval_native_judge" if kind == "native" else "deepeval_response_judge"
        )
    else:
        assert "error" not in event
        assert event["usage"] == {
            "input_tokens": 7,
            "output_tokens": 3,
            "cost_usd": None,
        }
        assert event["name"] == "deepeval_response_judge"


def test_opencode_judge_has_stable_truthful_session_headers(monkeypatch):
    import openai
    from eval_framework.benchmark.scorers.judge_client import OpenAICompatibleJudge

    clients = []

    def client(**kwargs):
        clients.append(kwargs)
        return object()

    monkeypatch.setattr(openai, "OpenAI", client)
    monkeypatch.setenv("TEST_JUDGE_KEY", "test-only")
    config = {
        "model": "deepseek-test",
        "api_key_env": "TEST_JUDGE_KEY",
        "base_url": "https://opencode.ai/zen/go/v1",
    }
    first = OpenAICompatibleJudge(config)
    second = OpenAICompatibleJudge(config)
    assert first.client is not second.client
    headers = [c["default_headers"] for c in clients]
    assert all(h["User-Agent"] == "agent-eval-suite/0.1.0" for h in headers)
    assert headers[0]["x-opencode-session"] != headers[1]["x-opencode-session"]
    assert clients[0]["max_retries"] == 0
    OpenAICompatibleJudge({**config, "base_url": "https://api.example.test/v1"})
    assert "default_headers" not in clients[-1]
