"""Single-step integration; autonomous runtimes retain AgentAdapter.execute."""

from dataclasses import dataclass
from typing import Protocol

from inspect_ai.model import ChatMessageAssistant, ModelOutput

from ...core.session_state import SessionState


@dataclass(frozen=True)
class AgentAction:
    message: ChatMessageAssistant
    finish_reason: str = "stop"
    output: ModelOutput | None = None


class BaseAgent(Protocol):
    async def step(self, state: SessionState) -> AgentAction: ...

    async def close(self) -> None: ...
