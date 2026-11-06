"""Explicit stop policies use local async fakes, never a remote model."""

import asyncio

import anyio
import pytest
from inspect_ai.model import ChatMessageAssistant
from inspect_ai.tool import ToolCall

from eval_framework.harness.adapters.agent.base import AgentAction
from eval_framework.harness.core.agent_loop import run_agent_loop
from eval_framework.harness.core.session_state import SessionState
from eval_framework.harness.core.tool_router import ToolRouter
from eval_framework.harness.user_simulator import FixedFollowupUserSimulator


class Environment:
    def __init__(self, *, slow=False):
        self.executed = []
        self.slow = slow

    async def snapshot(self):
        return {}

    async def step(self, name, arguments):
        if self.slow:
            await anyio.sleep(10)
        self.executed.append(arguments)
        return "ok"


class Agent:
    def __init__(self, calls=(), *, slow=False):
        self.calls = list(calls)
        self.slow = slow
        self.closed = False
        self.steps = 0

    async def step(self, state):
        self.steps += 1
        if self.slow:
            await anyio.sleep(10)
        return AgentAction(
            ChatMessageAssistant(content="done", tool_calls=self.calls or None)
        )

    async def close(self):
        self.closed = True


def invoke(agent, environment, **kwargs):
    state = SessionState(task_id="stop-test")
    asyncio.run(
        run_agent_loop(
            agent,
            state,
            router=ToolRouter(
                [
                    {
                        "name": "ok",
                        "description": "ok",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ]
            ),
            environment=environment,
            simulator=FixedFollowupUserSimulator("go", []),
            **kwargs,
        )
    )
    return state


@pytest.mark.parametrize("slow_model", [True, False])
def test_timeout_cancels_inflight_operation_and_closes_agent(slow_model):
    agent = Agent([ToolCall(id="a", function="ok", arguments={})], slow=slow_model)
    environment = Environment(slow=not slow_model)
    state = invoke(agent, environment, timeout_seconds=0.02)
    assert state.stop_reason == "time_limit"
    assert agent.closed
    assert environment.executed == []


def test_error_budget_stops_inside_batch_before_later_side_effects():
    agent = Agent(
        [
            ToolCall(id="bad", function="missing", arguments={}),
            ToolCall(id="good", function="ok", arguments={}),
        ]
    )
    environment = Environment()
    state = invoke(agent, environment, max_consecutive_errors=1)
    assert state.stop_reason == "error_limit"
    assert state.consecutive_errors == 1
    assert environment.executed == []
    assert agent.closed


def test_success_resets_consecutive_error_budget():
    agent = Agent(
        [
            ToolCall(id="bad", function="missing", arguments={}),
            ToolCall(id="good", function="ok", arguments={}),
            ToolCall(id="bad2", function="missing", arguments={}),
        ]
    )
    state = invoke(agent, Environment(), max_steps=1, max_consecutive_errors=2)
    assert state.stop_reason == "step_limit"
    assert state.consecutive_errors == 1


def test_policies_are_composable_and_deadline_uses_session_start():
    from eval_framework.harness.core.stop_conditions import ErrorStop, TimeoutStop

    state = SessionState(task_id="clock", started_at=0, consecutive_errors=2)
    assert TimeoutStop(1)(state, "model") == "time_limit"
    assert ErrorStop(2)(state, "model") == "error_limit"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": float("nan")},
        {"max_consecutive_errors": 0},
        {"max_consecutive_errors": True},
    ],
)
def test_invalid_policy_budget_rejected(kwargs):
    with pytest.raises(ValueError):
        invoke(Agent(), Environment(), **kwargs)


def test_invalid_budget_still_closes_owned_agent():
    agent = Agent()
    with pytest.raises(ValueError):
        invoke(agent, Environment(), timeout_seconds=0)
    assert agent.closed


def test_infrastructure_error_remains_an_exception_with_error_policy():
    class Broken(Agent):
        async def step(self, state):
            raise OSError("provider unavailable")

    agent = Broken()
    with pytest.raises(OSError, match="provider unavailable"):
        invoke(agent, Environment(), max_consecutive_errors=1)
    assert agent.closed
