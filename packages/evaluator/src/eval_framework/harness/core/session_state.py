"""Sample-local session state. Only the public conversation reaches the agent."""

from dataclasses import dataclass, field
from time import monotonic

from inspect_ai.model import ChatMessage, ModelOutput
from inspect_ai.tool import ToolInfo


@dataclass
class SessionState:
    task_id: str
    messages: list[ChatMessage] = field(default_factory=list)
    tools: list[ToolInfo] = field(default_factory=list)
    started_at: float = field(default_factory=monotonic)
    consecutive_errors: int = 0
    steps: int = 0
    tool_calls: int = 0
    turn: int = 0
    last_output: ModelOutput | None = None
    stop_reason: str | None = None
