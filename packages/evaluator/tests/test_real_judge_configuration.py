"""Build the real Inspect transport without a paid request or mocked registry."""

import importlib.util

import pytest

from eval_framework.diagnostic_metrics import ConversationMetricConfig
from eval_framework.judges.conversation import ConversationMetricClient
from eval_framework.judges.inspect import InspectJudgeClient


@pytest.mark.parametrize("kind", ["semantic", "conversation"])
def test_judge_builds_actual_inspect_openai_compatible_transport(monkeypatch, kind):
    monkeypatch.setenv("DEEPSEEK_JUDGE_API_KEY", "unit-test-not-a-real-key")
    monkeypatch.setenv("DEEPSEEK_JUDGE_MODEL", "deepseek-flash")
    if kind == "conversation":
        if importlib.util.find_spec("deepeval") is None:
            pytest.skip("optional conversation extra is not installed")
        client = ConversationMetricClient.from_env(ConversationMetricConfig())
    else:
        client = InspectJudgeClient.from_env()
    assert client.metadata()["model"] == "openai-api/deepseek/deepseek-flash"
