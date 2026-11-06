"""One native Inspect generation; orchestration stays in the Harness loop."""

from inspect_ai.model import get_model

from ...core.session_state import SessionState
from .base import AgentAction


class RawModelAgentAdapter:
    async def step(self, state: SessionState) -> AgentAction:
        output = await get_model().generate(input=state.messages, tools=state.tools)
        if not output.choices:
            raise RuntimeError("model returned no choices")
        return AgentAction(output.message, output.stop_reason, output)

    async def close(self) -> None:
        # Inspect owns model connections; adapters hold no process-global state.
        pass
