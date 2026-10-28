"""Opt-in complete tool configuration for local integration testing."""

from minimal_agent.runtime.tool_registry import ToolRegistry

from .environment import FixtureEnvironment


def create_registry() -> ToolRegistry:
    """Create six real fixture handlers, each factory call with fresh state."""
    return FixtureEnvironment().registry()


__all__ = ["FixtureEnvironment", "create_registry"]
