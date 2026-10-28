"""MiniAgent entrypoint for the portable Capability Protocol v3 CLI."""

import argparse
import sys
from collections.abc import Sequence

from capability_snapshot_kit.cli import main as portable_main
from minimal_agent.capabilities.v3.bundle import DEFAULT_CAPABILITY_SPEC_ROOT
from minimal_agent.capability_adapter import MiniAgentCapabilityAdapter
from minimal_agent.contracts.intents import build_default_intent_registry
from minimal_agent.runtime.tool_binding import (
    load_tool_registry,
    require_complete_tools,
)
from minimal_agent.runtime.tool_registry import ToolRegistry


def _default_adapter() -> MiniAgentCapabilityAdapter:
    return MiniAgentCapabilityAdapter(build_default_intent_registry(), ToolRegistry())


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    adapter_factory = _default_adapter
    if arguments and arguments[0] == "export":
        parser = argparse.ArgumentParser(
            prog="minimal-agent-capabilities export",
            add_help=False,
            allow_abbrev=False,
        )
        parser.add_argument(
            "--tool-registry-factory",
            help="Trusted module:callable returning ToolRegistry (executes Python).",
        )
        parser.add_argument("--require-complete-tools", action="store_true")
        if "--help" in arguments or "-h" in arguments:
            parser.print_help()
        options, remaining = parser.parse_known_args(arguments[1:])
        arguments = ["export", *remaining]

        def configured_adapter() -> MiniAgentCapabilityAdapter:
            intents = build_default_intent_registry()
            registry = (
                load_tool_registry(options.tool_registry_factory)
                if options.tool_registry_factory
                else ToolRegistry()
            )
            if options.require_complete_tools:
                require_complete_tools(intents, registry)
            if not registry.definitions:
                print(
                    "warning: tool_count=0; select --tool-registry-factory "
                    "to export executable tool contracts.",
                    file=sys.stderr,
                )
            return MiniAgentCapabilityAdapter(intents, registry)

        adapter_factory = configured_adapter
    return portable_main(
        arguments,
        adapter_factory=adapter_factory,
        default_spec_root=DEFAULT_CAPABILITY_SPEC_ROOT,
    )


if __name__ == "__main__":
    raise SystemExit(main())
