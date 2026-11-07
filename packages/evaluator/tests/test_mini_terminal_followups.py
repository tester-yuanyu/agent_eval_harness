"""Explicit continuation must deliver post-success turns without changing defaults."""

from types import SimpleNamespace

import pytest

from eval_framework.mini_agent_adapter import MiniAgentAdapter
from eval_framework.schemas import ExecutionSpec


class _Agent:
    def __init__(self):
        self.inputs = []

    def run(self, user_input, **kwargs):
        self.inputs.append(user_input)
        return SimpleNamespace(
            status="SUCCESS", model_dump=lambda **_: {"status": "SUCCESS"}
        )


@pytest.mark.parametrize(
    "continue_all,expected", [(False, ["first"]), (True, ["first", "second", "third"])]
)
def test_terminal_continuation_is_explicit(continue_all, expected):
    agent = _Agent()
    adapter = MiniAgentAdapter(SimpleNamespace(agent=agent, session_id="local"))
    execution = ExecutionSpec(
        user_input="first",
        user_responses=["second", "third"],
        tool_profile="benchmark",
        adapter_input={"continue_after_terminal": continue_all},
    )
    output = adapter.run_full(execution, "end_to_end")
    assert agent.inputs == expected
    assert len(output.turns) == len(expected)


def test_terminal_continuation_rejects_non_boolean_control():
    agent = _Agent()
    adapter = MiniAgentAdapter(SimpleNamespace(agent=agent, session_id="local"))
    execution = ExecutionSpec(
        user_input="first",
        tool_profile="benchmark",
        adapter_input={"continue_after_terminal": "false"},
    )
    with pytest.raises(ValueError, match="continue_after_terminal"):
        adapter.run_full(execution, "end_to_end")
    assert agent.inputs == []
