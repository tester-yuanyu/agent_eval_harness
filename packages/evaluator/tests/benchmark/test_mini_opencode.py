"""OpenCode routing metadata must stay stable within each mini_agent trial."""

import asyncio

from inspect_ai.model import ChatMessageUser, GenerateConfig

from eval_framework.benchmark import mini_adapter


def test_opencode_bridge_headers_isolate_conversations_without_changing_input():
    async def run():
        filters = [
            mini_adapter.opencode_bridge_filter(
                {"base_url": "https://opencode.ai/zen/go/v1"}
            )
            for _ in range(2)
        ]
        messages = [ChatMessageUser(content="test")]
        config = GenerateConfig(max_tokens=32, extra_headers={"x-existing": "keep"})
        sessions = []
        for filter_ in filters:
            ids = []
            for _ in range(2):
                result = await filter_(None, messages, [], "none", config)
                assert result.input == messages
                assert result.tools == []
                assert result.tool_choice == "none"
                assert result.config.max_tokens == 32
                headers = result.config.extra_headers
                assert headers["x-existing"] == "keep"
                assert headers["User-Agent"].startswith("agent-eval-suite/")
                ids.append(headers["x-opencode-session"])
            assert ids[0] == ids[1] and ids[0]
            sessions.append(ids[0])
        assert sessions[0] != sessions[1]
        assert config.extra_headers == {"x-existing": "keep"}

    asyncio.run(run())


def test_opencode_headers_are_not_added_to_other_providers():
    for url in (None, "https://api.example.com/v1", "https://opencode.ai.example/v1"):
        assert mini_adapter.opencode_bridge_filter({"base_url": url}) is None


def test_shared_request_budget_stops_before_forwarding_across_trials():
    import pytest

    from eval_framework.benchmark.request_budget import RequestBudget

    async def run():
        budget = RequestBudget(2)
        filters = [
            mini_adapter.opencode_bridge_filter(
                {"base_url": "https://opencode.ai/zen/go/v1"}, budget=budget
            )
            for _ in range(3)
        ]
        for filter_ in filters[:2]:
            await filter_(
                None, [ChatMessageUser(content="test")], [], "none", GenerateConfig()
            )
        with pytest.raises(RuntimeError, match="MODEL_REQUEST_BUDGET_EXHAUSTED"):
            await filters[2](None, [], [], "none", GenerateConfig())
        assert budget.used == 2

    asyncio.run(run())
