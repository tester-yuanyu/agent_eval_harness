"""Explicit, caller-owned Tool bindings shared by execution and export."""

from collections.abc import Iterable, Mapping
from importlib import import_module

from minimal_agent.contracts.intents import IntentRegistry
from minimal_agent.contracts.tools import ToolContract
from minimal_agent.runtime.tool_registry import (
    ToolDefinition,
    ToolHandler,
    ToolRegistry,
)


def bind_tools(
    contracts: Iterable[ToolContract],
    handlers: Mapping[str, ToolHandler],
) -> ToolRegistry:
    """Bind every declared contract; reject accidental partial configurations."""

    definitions = tuple(contracts)
    names = [contract.name for contract in definitions]
    if len(names) != len(set(names)):
        raise ValueError("duplicate tool contracts")
    missing = set(names) - handlers.keys()
    unknown = handlers.keys() - set(names)
    if missing or unknown:
        raise ValueError(
            f"tool bindings: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    if any(not callable(handlers[name]) for name in names):
        raise ValueError("every tool handler must be callable")
    registry = ToolRegistry()
    for contract in definitions:
        registry.register(
            ToolDefinition(contract=contract, handler=handlers[contract.name])
        )
    return registry


def require_complete_tools(intents: IntentRegistry, tools: ToolRegistry) -> None:
    required = {
        definition.tool_name
        for definition in intents.definitions
        if definition.tool_name is not None
    }
    missing = required - {definition.name for definition in tools.definitions}
    if missing:
        raise ValueError(f"missing required tool bindings: {sorted(missing)}")


def load_tool_registry(factory_path: str) -> ToolRegistry:
    """Load only an explicitly requested trusted local module:factory.

    Importing and invoking this factory executes caller-supplied Python. Never
    obtain this path from an untrusted capability bundle or evaluation case.
    """

    module_name, separator, attribute = factory_path.partition(":")
    if (
        not separator
        or not module_name
        or not attribute.isidentifier()
        or not all(part.isidentifier() for part in module_name.split("."))
    ):
        raise ValueError("tool registry factory must be module:callable")
    try:
        factory = getattr(import_module(module_name), attribute)
        if not callable(factory):
            raise ValueError("tool registry factory must be callable")
        registry = factory()
    except Exception as exc:
        raise ValueError(
            f"cannot load tool registry factory {factory_path}: {exc}"
        ) from exc
    if not isinstance(registry, ToolRegistry):
        raise ValueError("tool registry factory must return ToolRegistry")
    return registry
