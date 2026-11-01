"""Diagnostic semantics, actual-turn provenance and public DeepEval integration."""

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from eval_framework.diagnostic_metrics import (
    METRIC_ID,
    ConversationMetricConfig,
    DiagnosticMetricResult,
    conversation_input,
)
from eval_framework.judges.conversation import ConversationMetricClient
from inspect_ai.model import ModelOutput, ModelUsage, get_model


def dialogue():
    return [
        {"role": "user", "content": "Find gift 42"},
        {"role": "assistant", "content": "Which region?"},
        {"role": "user", "content": "CN"},
        {"role": "assistant", "content": "Gift 42 is available in CN"},
    ]


def test_input_uses_only_actual_turns(case_result_factory):
    case = SimpleNamespace(
        execution=SimpleNamespace(
            user_input="Find gift 42", user_responses=["CN", "UNUSED SECRET"]
        )
    )
    result = case_result_factory(
        module_output=None,
        test_scope="end_to_end",
        turn_results=[
            {"final_response": "Which region?"},
            {"final_response": "Gift 42 is available in CN"},
        ],
    )
    assert conversation_input(case, result) == dialogue()
    result.turn_results.append({"final_response": None})
    with pytest.raises(ValueError):
        conversation_input(case, result)


def test_result_cannot_claim_score_for_error():
    with pytest.raises(ValueError):
        DiagnosticMetricResult(status="ERROR", score=1)
    with pytest.raises(ValueError):
        DiagnosticMetricResult(status="SUCCESS", score=None)


def mock_client(*, intention_payload=None, verdict_payload=None):
    if importlib.util.find_spec("deepeval") is None:
        pytest.skip("optional conversation extra is not installed")
    captured = []

    def output(messages, *_):
        prompt = "\n".join(m.text for m in messages)
        captured.append(prompt)
        if '"intentions"' in prompt:
            data = (
                intention_payload
                if intention_payload is not None
                else {"intentions": ["Find gift 42 in CN"]}
            )
        elif '"verdict"' in prompt:
            data = verdict_payload or {"verdict": "yes", "reason": "Found"}
        else:
            data = {"reason": "The requested gift was found"}
        result = ModelOutput.from_content(
            model="mockllm/metric", content=json.dumps(data)
        )
        # MockLLM otherwise estimates usage with tiktoken, whose cold cache can
        # download tokenizer data. This transport test must stay fully local.
        result.usage = ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        return result

    return ConversationMetricClient(
        get_model("mockllm/metric", custom_outputs=output),
        ConversationMetricConfig(),
    ), captured


def test_public_metric_via_inspect_transport():
    client, prompts = mock_client()
    result = asyncio.run(client.evaluate(dialogue()))
    assert result.status == "SUCCESS", result
    assert result.score == 1
    assert result.input_turn_count == 4
    assert len(result.input_sha256) == 64
    assert result.evidence["intentions"] == ["Find gift 42 in CN"]
    assert len(result.evidence["verdicts"]) == 1
    assert prompts and all("Find gift 42" in p for p in prompts[:2])
    assert result.token_usage == {
        "input_tokens": 10 * len(prompts),
        "output_tokens": 5 * len(prompts),
    }
    assert client.metadata()["metric_id"] == METRIC_ID
    assert client.metadata()["eval_mode"] == "llm"


@pytest.mark.parametrize(
    "intentions,verdict",
    [
        ({"intentions": []}, None),
        (None, {"verdict": "unknown"}),
        (None, {"verdict": None}),
    ],
)
def test_incomplete_judgments_are_unknown(intentions, verdict):
    client, _ = mock_client(intention_payload=intentions, verdict_payload=verdict)
    result = asyncio.run(client.evaluate(dialogue()))
    assert result.status == "ERROR"
    assert result.score is None


def test_zero_is_a_valid_score():
    client, _ = mock_client(verdict_payload={"verdict": "no", "reason": "Not found"})
    result = asyncio.run(client.evaluate(dialogue()))
    assert result.status == "SUCCESS"
    assert result.score == 0


def test_timeout_is_unknown_and_does_not_leak_exception(monkeypatch):
    client, _ = mock_client()
    client.config = ConversationMetricConfig(timeout_seconds=0.01)

    class SlowMetric:
        def __init__(self, **kwargs):
            pass

        async def a_measure(self, *args, **kwargs):
            await asyncio.sleep(1)

    client.metric_type = SlowMetric
    result = asyncio.run(client.evaluate(dialogue()))
    assert result.status == "ERROR" and result.score is None
    assert result.issue_code == "METRIC_TIMEOUT"


def test_partial_verdicts_cannot_use_successful_subset():
    client, _ = mock_client()

    class PartialMetric:
        def __init__(self, **kwargs):
            self.user_intentions = ["first", "second"]
            self.verdicts = [SimpleNamespace(verdict="yes"), None]
            self.score, self.error = 1, None

        async def a_measure(self, *args, **kwargs):
            return self.score

    client.metric_type = PartialMetric
    result = asyncio.run(client.evaluate(dialogue()))
    assert result.status == "ERROR" and result.score is None


def test_metric_instance_is_new_for_each_trial():
    client, _ = mock_client()
    instances = []
    original = client.metric_type

    def create(**kwargs):
        instance = original(**kwargs)
        instances.append(instance)
        return instance

    client.metric_type = create
    assert asyncio.run(client.evaluate(dialogue())).status == "SUCCESS"
    assert asyncio.run(client.evaluate(dialogue())).status == "SUCCESS"
    assert len(instances) == 2 and instances[0] is not instances[1]


def test_ambient_credentials_do_not_cause_network_or_dotenv_loading(tmp_path):
    if importlib.util.find_spec("deepeval") is None:
        pytest.skip("optional conversation extra is not installed")
    (tmp_path / ".env").write_text("CONVERSATION_DOTENV_LEAK=yes\n")
    script = """
import os, socket, asyncio, json
attempts = []
def forbidden(*args, **kwargs):
    attempts.append(True)
    raise AssertionError("Unexpected external network")
socket.socket.connect = forbidden
from inspect_ai.model import get_model, ModelOutput, ModelUsage
from eval_framework.judges.conversation import ConversationMetricClient
from eval_framework.diagnostic_metrics import ConversationMetricConfig
def output(messages, *_):
    text = "\\n".join(m.text for m in messages)
    data = {"intentions": ["hello"]} if '"intentions"' in text else (
        {"verdict": "yes", "reason": "ok"} if '"verdict"' in text else {"reason": "ok"})
    result = ModelOutput.from_content(model="mockllm/judge", content=json.dumps(data))
    result.usage = ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15)
    return result
client = ConversationMetricClient(
    get_model("mockllm/judge", custom_outputs=output), ConversationMetricConfig())
result = asyncio.run(client.evaluate([
    {"role": "user", "content": "hello"}, {"role": "assistant", "content": "hello"},
    {"role": "user", "content": "bye"}, {"role": "assistant", "content": "bye"}]))
assert result.status == "SUCCESS", result
assert "CONVERSATION_DOTENV_LEAK" not in os.environ
assert attempts == [], attempts
"""
    process = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "CONFIDENT_API_KEY": "test-ambient-key",
            "DEEPEVAL_TELEMETRY_OPT_OUT": "0",
            "CONFIDENT_TRACE_INTERNAL": "1",
            "TIKTOKEN_CACHE_DIR": str(tmp_path / "empty-tokenizer-cache"),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr


@pytest.mark.parametrize(
    "updates,status,code",
    [
        ({"test_scope": "module"}, "NOT_APPLICABLE", "MODULE"),
        ({"execution_status": "MODEL_TIMEOUT"}, "ERROR", "EXECUTION_UNAVAILABLE"),
        ({"evaluation_validity": "INVALID"}, "ERROR", "EXECUTION_UNAVAILABLE"),
        ({"turn_results": [{"final_response": "hi"}]}, "NOT_APPLICABLE", "SINGLE_TURN"),
        ({"turn_results": [{"final_response": None}]}, "ERROR", "INCOMPLETE_DIALOGUE"),
    ],
)
def test_inapplicable_inputs_never_call_metric(
    case_result_factory, updates, status, code
):
    from eval_framework.diagnostic_metrics import evaluate_conversation

    case = SimpleNamespace(
        execution=SimpleNamespace(user_input="hi", user_responses=[])
    )
    result = case_result_factory(
        **{"test_scope": "end_to_end", "module_output": None, **updates}
    )
    metric = asyncio.run(
        evaluate_conversation(SimpleNamespace(case=case), result, None)
    )
    assert (metric.status, metric.issue_code, metric.score) == (status, code, None)


@pytest.mark.parametrize(
    "terminal",
    [
        "NEED_CONFIRMATION",
        "NEED_CLARIFICATION",
        "MAX_STEPS_EXCEEDED",
        "FAILED",
        "TIMEOUT",
    ],
)
def test_open_conversation_is_not_graded_as_finished(case_result_factory, terminal):
    from eval_framework.diagnostic_metrics import evaluate_conversation

    case = SimpleNamespace(
        execution=SimpleNamespace(
            user_input="grant gift",
            user_responses=["confirm"],
        )
    )
    result = case_result_factory(
        test_scope="end_to_end",
        module_output=None,
        turn_results=[
            {"final_response": "Confirm?", "status": "NEED_CONFIRMATION"},
            {
                "final_response": "Still needs confirmation",
                "status": terminal,
            },
        ],
    )
    metric = asyncio.run(
        evaluate_conversation(SimpleNamespace(case=case), result, None)
    )
    assert metric.status == "ERROR" and metric.issue_code == "CONVERSATION_OPEN"


def test_failed_verdict_cancels_and_joins_other_model_calls(monkeypatch):
    client, _ = mock_client()
    late_completions, cancelled = [], []
    calls = 0

    async def generate(prompt, **kwargs):
        nonlocal calls
        if '"intentions"' in prompt:
            return ModelOutput.from_content(
                model="mockllm/judge",
                content=json.dumps({"intentions": ["first", "second"]}),
            )
        calls += 1
        if calls == 1:
            return ModelOutput.from_content(
                model="mockllm/judge", content="invalid JSON"
            )
        try:
            await asyncio.sleep(0.2)
            late_completions.append(True)
            return ModelOutput.from_content(
                model="mockllm/judge", content='{"verdict":"yes"}'
            )
        finally:
            cancelled.append(True)

    monkeypatch.setattr(client.model, "generate", generate)

    async def run():
        result = await client.evaluate(dialogue())
        assert result.status == "ERROR" and result.score is None
        assert cancelled == [True]
        await asyncio.sleep(0.25)
        assert late_completions == []

    asyncio.run(run())
