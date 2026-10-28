"""Stable Agent, Intent, and Tool protocol definitions."""

from minimal_agent.contracts.agent import AgentResult, IntentResult
from minimal_agent.contracts.intents import (
    IntentRegistry,
    build_default_intent_registry,
)
from minimal_agent.contracts.tools import ToolContract, ToolResult

__all__ = [
    "AgentResult",
    "IntentRegistry",
    "IntentResult",
    "ToolContract",
    "ToolResult",
    "build_default_intent_registry",
]
