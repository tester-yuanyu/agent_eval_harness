"""Agent execution runtime with no built-in business Tools."""

from importlib import import_module
from typing import Any

__all__ = [
    "DeepSeekModelClient",
    "MinimalAgent",
    "OpenAIModelClient",
    "ToolDefinition",
    "ToolRegistry",
    "run_intent_only",
]

_EXPORTS = {
    "DeepSeekModelClient": (
        "minimal_agent.runtime.deepseek_client",
        "DeepSeekModelClient",
    ),
    "MinimalAgent": ("minimal_agent.runtime.agent", "MinimalAgent"),
    "OpenAIModelClient": (
        "minimal_agent.runtime.openai_client",
        "OpenAIModelClient",
    ),
    "ToolDefinition": (
        "minimal_agent.runtime.tool_registry",
        "ToolDefinition",
    ),
    "ToolRegistry": ("minimal_agent.runtime.tool_registry", "ToolRegistry"),
    "run_intent_only": (
        "minimal_agent.runtime.intent_router",
        "run_intent_only",
    ),
}


def __getattr__(name: str) -> Any:
    """Resolve public runtime interfaces without eager import cycles."""

    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
