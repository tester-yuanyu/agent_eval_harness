from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from dataset_builder.generation_comparison import (
    DirectSlotSynthesizer,
    run_arm,
    summarize_arm,
)
from dataset_builder.pipeline import prepare_generation
from dataset_builder.suite_definition import load_suite


@pytest.fixture
def suite():
    return load_suite("mini_agent_query_user_intent_v3")


@pytest.fixture
def seeds(suite):
    return json.loads((suite.suite_dir / "seed_catalog.json").read_text())["candidates"]


def sample(candidate, blocked=False):
    return SimpleNamespace(
        input=candidate["user_input"],
        expected_output=None if blocked else json.dumps(candidate),
        context=[],
        additional_metadata={},
    )


def test_direct_one_call_returns_untouched_candidate(suite, seeds):
    calls = []
    raw = json.dumps(seeds[0], ensure_ascii=False)

    def complete(prompt, *, json_mode):
        calls.append((prompt, json_mode))
        return raw, 0.0

    generator = DirectSlotSynthesizer(complete)
    result = generator.generate(
        "BOUND SOURCE",
        suite.coverage_plan["slots"][0],
        json.dumps(suite.candidate_type.model_json_schema()),
    )
    assert result[0].expected_output == raw
    assert result[0].input == seeds[0]["user_input"]
    assert len(calls) == 1 and calls[0][1] is True
    assert "BOUND SOURCE" in calls[0][0]
    assert "explicit_user_id" in calls[0][0]


@pytest.mark.parametrize(
    "response",
    ["```json\n{}\n```", "null", '{"input":"查询用户0","expected_output":{}}'],
)
def test_input_only_never_discards_an_invented_oracle(suite, response):
    generator = DirectSlotSynthesizer(lambda *a, **k: (response, 0.0))
    with pytest.raises(ValueError):
        generator.generate("SOURCE", suite.coverage_plan["slots"][16], "{}")


def test_input_only_does_not_request_candidate_oracle(suite):
    prompts = []

    def complete(prompt, *, json_mode):
        prompts.append(prompt)
        return '{"input":"查询用户ID为0的信息"}', 0.0

    result = DirectSlotSynthesizer(complete).generate(
        "SOURCE", suite.coverage_plan["slots"][16], "CANDIDATE_SCHEMA_SENTINEL"
    )
    assert result[0].expected_output is None
    assert "CANDIDATE_SCHEMA_SENTINEL" not in prompts[0]


def test_exhausted_slot_does_not_bias_denominator_or_stop_later_slots(
    suite, seeds, tmp_path
):
    request = prepare_generation(suite, tmp_path)

    def generate(context, slot, schema):
        if slot["slot_id"] == seeds[0]["slot_id"]:
            raise ValueError("malformed output")
        c = next(c for c in seeds if c["slot_id"] == slot["slot_id"])
        return [sample(c, bool(slot["acceptance"].get("oracle_gaps")))]

    result = run_arm(suite, request, generate, tmp_path, max_slot_attempts=2)
    assert len(result["accepted"]) == 41
    assert len(result["failed_slots"]) == 1
    metrics = summarize_arm(result)
    assert metrics["first_pass_count"] == 41
    assert metrics["planned_slots"] == 42
    assert metrics["attempt_count"] == 43
    assert metrics["accepted_oracles"] == 24 and metrics["accepted_input_only"] == 17
    assert metrics["first_pass_rate"] == pytest.approx(41 / 42)
    with pytest.raises(FileExistsError):
        run_arm(suite, request, generate, tmp_path, max_slot_attempts=2)


def test_same_dedup_and_retry_policy_applies_to_both_inputs_and_oracles(
    suite, seeds, tmp_path
):
    request = prepare_generation(suite, tmp_path)
    count = {}

    def generate(context, slot, schema):
        sid = slot["slot_id"]
        count[sid] = count.get(sid, 0) + 1
        c = deepcopy(next(c for c in seeds if c["slot_id"] == sid))
        if sid == seeds[4]["slot_id"] and count[sid] == 1:
            c["user_input"] = seeds[0]["user_input"] + "！"
            c["expected_parameters_json"] = seeds[0]["expected_parameters_json"]
        if sid == seeds[16]["slot_id"] and count[sid] == 1:
            return [sample(c, False)]  # known gap must reject an oracle
        return [sample(c, bool(slot["acceptance"].get("oracle_gaps")))]

    result = run_arm(suite, request, generate, tmp_path, max_slot_attempts=2)
    m = summarize_arm(result)
    assert m["first_pass_count"] == 40 and m["attempt_count"] == 44
    assert m["accepted_oracles"] == 25 and m["accepted_input_only"] == 17
    assert len(result["rejected_attempts"]) == 2
    assert (
        result["rejected_attempts"][0]["samples"][0]["input"]
        == seeds[0]["user_input"] + "！"
    )
    assert result["accepted"][0]["sample"]["input"] == seeds[0]["user_input"]


def test_bad_sources_fail_before_model_call(suite, tmp_path):
    request = prepare_generation(suite, tmp_path)

    def forbidden(*args):
        pytest.fail("model called with stale source")

    with pytest.raises(ValueError):
        run_arm(
            suite,
            request.model_copy(update={"coverage_plan_sha256": "0" * 64}),
            forbidden,
            tmp_path,
        )


def test_provider_controls_every_wire_call_and_never_logs_credentials(tmp_path):
    import httpx

    from dataset_builder.comparison_provider import ControlledProvider, usage_summary

    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "test",
                "model": "same-model",
                "choices": [
                    {
                        "message": {"content": '{"input":"查用户"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "prompt_cache_hit_tokens": 40,
                    "prompt_cache_miss_tokens": 60,
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        provider = ControlledProvider(
            http, "deepseek-flash", "not-a-real-secret", tmp_path / "calls.jsonl"
        )
        for json_mode in (True, False):
            provider.complete("bounded context", json_mode=json_mode)
    assert all(
        p["temperature"] == 0.4
        and p["thinking"] == {"type": "disabled"}
        and p["max_tokens"] == 4096
        for p in seen
    )
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in seen[1]
    assert "not-a-real-secret" not in (tmp_path / "calls.jsonl").read_text()
    metrics = usage_summary(provider.calls)
    assert metrics["prompt_tokens"] == 200 and metrics["completion_tokens"] == 20
    assert metrics["prompt_cache_hit_tokens"] == 80
    assert metrics["api_calls"] == 2
    assert metrics["estimated_usd_peak"] == pytest.approx(0.00006048)


def test_provider_missing_usage_is_unavailable_not_free(tmp_path):
    import httpx

    from dataset_builder.comparison_provider import ControlledProvider, usage_summary

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]
                },
            )
        )
    ) as http:
        provider = ControlledProvider(http, "model", "dummy", tmp_path / "calls.jsonl")
        provider.complete("context", json_mode=True)
    summary = usage_summary(provider.calls)
    assert summary["missing_usage_calls"] == 1
    assert summary["estimated_usd_peak"] is None


def test_provider_no_hidden_retry_and_failed_call_remains_auditable(tmp_path):
    import httpx

    from dataset_builder.comparison_provider import ControlledProvider

    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(429, json={"error": "rate limit"})
        )
    ) as http:
        provider = ControlledProvider(http, "model", "dummy", tmp_path / "calls.jsonl")
        with pytest.raises(RuntimeError, match="429"):
            provider.complete("context", json_mode=True)
    assert len(provider.calls) == 1
    assert json.loads((tmp_path / "calls.jsonl").read_text())["status_code"] == 429


@pytest.mark.parametrize("failure", ["content", "transport"])
def test_provider_credential_echo_never_reaches_samples_or_attempt_errors(
    tmp_path, failure
):
    import httpx

    from dataset_builder.comparison_provider import ControlledProvider

    secret = "fake-credential-for-test"

    def respond(request):
        if failure == "transport":
            raise RuntimeError("transport echoed " + secret)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": secret}, "finish_reason": "stop"}]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        provider = ControlledProvider(http, "model", secret, tmp_path / "calls.jsonl")
        with pytest.raises(RuntimeError) as caught:
            provider.complete("source", json_mode=True)
    assert secret not in str(caught.value)
    assert secret not in json.dumps(provider.calls)
    assert secret not in (tmp_path / "calls.jsonl").read_text()


@pytest.mark.parametrize("container", [False, True])
def test_native_sdk_rejects_extra_oracles_before_pydantic_discards_them(container):
    import runpy
    from pathlib import Path

    pytest.importorskip("deepeval", reason="DeepEval optional dependency is not installed")
    from deepeval.synthesizer.schema import SyntheticData, SyntheticDataList

    namespace = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/compare_generators.py")
    )
    model = object.__new__(namespace["ControlledDeepSeek"])
    data = {"input": "查询用户0", "expected_output": {"status": "READY"}}
    model.provider = SimpleNamespace(
        complete=lambda *a, **k: (
            json.dumps({"data": [data]} if container else data),
            0,
        )
    )
    with pytest.raises(ValueError, match="Additional properties"):
        model.generate(
            "source", schema=SyntheticDataList if container else SyntheticData
        )
