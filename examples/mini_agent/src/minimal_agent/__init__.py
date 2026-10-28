"""Narrow public interfaces for configured minimal Agent runtimes."""

from minimal_agent.capabilities import (
    build_capability_bundle,
    export_capability_bundle,
    validate_capability_bundle,
)
from minimal_agent.contracts import (
    AgentResult,
    IntentRegistry,
    IntentResult,
    ToolContract,
    ToolResult,
    build_default_intent_registry,
)
from minimal_agent.runtime import (
    MinimalAgent,
    ToolDefinition,
    ToolRegistry,
    run_intent_only,
)

__all__ = [
    "AgentResult",
    "IntentRegistry",
    "IntentResult",
    "MinimalAgent",
    "ToolContract",
    "ToolDefinition",
    "ToolRegistry",
    "ToolResult",
    "build_capability_bundle",
    "build_default_intent_registry",
    "export_capability_bundle",
    "run_intent_only",
    "validate_capability_bundle",
]
