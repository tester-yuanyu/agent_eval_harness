"""JSON CLI for intent-only and configured Agent execution."""

import argparse
from collections.abc import Callable

from minimal_agent.contracts.agent import CliErrorResult, ProtocolModel
from minimal_agent.runtime.agent import MinimalAgent
from minimal_agent.runtime.intent_router import run_intent_only
from minimal_agent.runtime.model_client import ModelClient
from minimal_agent.runtime.openai_client import OpenAIModelClient
from minimal_agent.runtime.tool_binding import load_tool_registry
from minimal_agent.runtime.tool_registry import ToolRegistry


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="minimal-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    intent_parser = subparsers.add_parser("intent")
    intent_parser.add_argument("user_input")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("user_input")
    run_parser.add_argument("--max-steps", type=int, default=4)
    run_parser.add_argument("--session-id")
    run_parser.add_argument(
        "--tool-registry-factory",
        help="Trusted local module:callable returning ToolRegistry (executes Python).",
    )
    return parser


def _build_model_client(
    openai_client_factory: Callable[[], ModelClient] | None,
) -> ModelClient:
    if openai_client_factory is not None:
        return openai_client_factory()
    return OpenAIModelClient.from_env()


def _print_json(result: ProtocolModel) -> None:
    print(result.model_dump_json(indent=2))


def main(
    argv: list[str] | None = None,
    *,
    openai_client_factory: Callable[[], ModelClient] | None = None,
    tool_registry_factory: Callable[[], ToolRegistry] | None = None,
) -> int:
    """Execute one command and print one protocol-backed JSON document."""

    args = _build_parser().parse_args(argv)
    try:
        client = _build_model_client(openai_client_factory)
        if args.command == "intent":
            result = run_intent_only(args.user_input, client)
        else:
            if args.tool_registry_factory and tool_registry_factory is not None:
                raise ValueError(
                    "choose either a CLI or injected tool registry factory"
                )
            registry = (
                load_tool_registry(args.tool_registry_factory)
                if args.tool_registry_factory
                else (
                    tool_registry_factory()
                    if tool_registry_factory is not None
                    else ToolRegistry()
                )
            )
            result = MinimalAgent(
                client,
                registry,
                max_steps=args.max_steps,
            ).run(args.user_input, session_id=args.session_id)
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        _print_json(
            CliErrorResult(
                error_type=type(exc).__name__,
                message=detail,
            )
        )
        return 1

    _print_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
