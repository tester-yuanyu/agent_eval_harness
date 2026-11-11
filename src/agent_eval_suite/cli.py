"""Thin root CLI: runtime imports only occur in the selected child interpreter."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .registry import BundleRegistry, SuiteError

BUILDER_COMMANDS = (
    "prepare",
    "generate",
    "ingest",
    "validate",
    "review",
    "freeze",
    "generate-full",
    "validate-full",
    "generate-nanobot",
    "validate-nanobot",
)
EVAL_COMMANDS = (
    "validate",
    "run",
    "compare",
    "gate",
    "analyze",
    "export-langfuse",
    "sync-local",
    "import-reviews",
)
BENCHMARK_COMMANDS = (
    "analyze",
    "annotations-build",
    "annotations-validate",
    "core-validate",
    "core-run",
    "coverage",
    "validate",
    "demo",
    "run",
    "compare",
    "report",
    "regrade",
    "judge",
    "calibration-sheet",
    "calibration-page",
    "calibration-check",
    "quality-audit",
    "export-langfuse",
    "export-langfuse-evidence",
    "verify-langfuse",
)


def discover_root() -> Path:
    for anchor in (Path.cwd(), Path(__file__).resolve().parent):
        for path in (anchor, *anchor.parents):
            if (path / "packages/dataset-builder").is_dir() and (
                path / "packages/evaluator"
            ).is_dir():
                return path
    return Path.cwd()


def interpreter(root: Path, configured: str | None, kind: str) -> Path:
    path = Path(configured) if configured else root / ".venvs" / kind / "bin/python"
    if not path.is_absolute():
        path = root / path
    if not path.is_file() or not os.access(path, os.X_OK):
        raise SuiteError(
            f"missing {kind} Python: {path}; run make setup or pass --{kind}-python PATH before the command"
        )
    return path


def invoke(python: Path, module: str, args: list[str], *, capture=False):
    result = subprocess.run(
        [str(python), "-m", module, *args],
        text=True,
        capture_output=capture,
        check=False,
    )
    if capture:
        if result.returncode:
            raise SuiteError(
                result.stderr.strip()
                or result.stdout.strip()
                or f"{module} failed ({result.returncode})"
            )
        return json.loads(result.stdout)
    return result.returncode


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="eval-suite",
        description="Pinned assets and subprocess orchestration. No .env loading, implicit source sync, or latest-version selection.",
    )
    root.add_argument(
        "--root",
        type=Path,
        default=discover_root(),
        help="suite checkout root (default: discover checkout)",
    )
    root.add_argument(
        "--builder-python",
        help="installed Builder/contracts interpreter; default .venvs/builder/bin/python",
    )
    root.add_argument(
        "--evaluator-python",
        help="installed evaluator interpreter; default .venvs/evaluator/bin/python",
    )
    groups = root.add_subparsers(dest="group", required=True)
    readiness = groups.add_parser(
        "readiness", help="Offline Builder release readiness gate"
    )
    actions = readiness.add_subparsers(dest="action", required=True)
    for action in ("run", "check", "freeze"):
        child = actions.add_parser(action)
        source = child.add_mutually_exclusive_group(required=True)
        source.add_argument("--dataset", type=Path)
        source.add_argument("--delivery", type=Path)
        child.add_argument("--mini-agent-root", type=Path)
        child.add_argument("--workspace", type=Path, required=True)
        child.add_argument("--review", type=Path, required=action == "freeze")
        child.add_argument("--output", type=Path, required=action == "freeze")
    for name, aliases, commands, description in (
        (
            "benchmark",
            [],
            BENCHMARK_COMMANDS,
            "Fixed task datasets + Inspect Harness + DeepEval scoring. Live calls and Langfuse exports are explicit.",
        ),
        (
            "dataset",
            ["builder"],
            BUILDER_COMMANDS,
            "Delegate existing Builder stages: prepare, generate or ingest, validate, review, then explicitly freeze. No automatic build/freeze shorthand. Commands preserve upstream arguments.",
        ),
        (
            "eval",
            [],
            EVAL_COMMANDS,
            "Delegate evaluator commands. compare accepts --baseline-run DIR as an alias for --baseline DIR. Reference dataset/contracts stay fixed; legacy --capability-bundle must match the dataset Hash. Runtime configuration belongs to the Provider or trusted binding. Pass COMMAND --help for upstream arguments.",
        ),
    ):
        group = groups.add_parser(
            name, aliases=aliases, description=description, help=description
        )
        subcommands = group.add_subparsers(dest="command", required=True)
        for command in commands:
            child = subcommands.add_parser(
                command, add_help=False, help="upstream arguments; use --help"
            )
            child.add_argument("forwarded", nargs=argparse.REMAINDER)
    bundle = groups.add_parser(
        "bundle",
        aliases=["cap"],
        help="publish, discover, verify and diff fixed v3 bundles",
    )
    actions = bundle.add_subparsers(dest="command", required=True)
    publish = actions.add_parser("publish")
    publish.add_argument("--input", type=Path, required=True)
    publish.add_argument("--agent", required=True)
    publish.add_argument(
        "--version",
        required=True,
        help="immutable publication version beginning with a digit",
    )
    resolve = actions.add_parser("resolve")
    resolve.add_argument("--agent", required=True)
    resolve.add_argument("--version", required=True)
    actions.add_parser(
        "list", help="discovery only; resolve validates before formal use"
    )
    validate = actions.add_parser("validate")
    validate.add_argument("--input", type=Path, required=True)
    diff = actions.add_parser("diff")
    diff.add_argument("--old", type=Path, required=True)
    diff.add_argument("--new", type=Path, required=True)
    agent = groups.add_parser(
        "agent",
        aliases=["source"],
        help="explicit Git source sync and immutable commit resolution",
    )
    actions = agent.add_subparsers(dest="command", required=True)
    sync = actions.add_parser(
        "sync",
        help="fetch only on this explicit command, checkout detached commit and save provenance",
    )
    sync.add_argument("--name", required=True)
    sync.add_argument("--repository", required=True)
    sync.add_argument("--ref", required=True)
    resolve = actions.add_parser("resolve")
    resolve.add_argument("--name", required=True)
    resolve.add_argument(
        "--commit",
        required=True,
        help="full pinned commit returned by sync; never a mutable alias",
    )
    return root


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    # A passthrough must preserve argument order, including flags argparse would
    # otherwise classify as unknown before the REMAINDER positional starts.
    root_parser = parser()
    args, unknown = root_parser.parse_known_args(arguments)
    try:
        root = args.root.resolve()
        if args.group in ("dataset", "builder", "eval", "benchmark"):
            # Find the selected namespace after global options, then retain its tail.
            global_parser = argparse.ArgumentParser(add_help=False)
            global_parser.add_argument("--root")
            global_parser.add_argument("--builder-python")
            global_parser.add_argument("--evaluator-python")
            global_parser.add_argument("group")
            global_parser.add_argument("command")
            global_parser.add_argument("tail", nargs=argparse.REMAINDER)
            forward = global_parser.parse_args(arguments).tail
            if forward[:1] == ["--"]:
                forward = forward[1:]
            kind = "evaluator" if args.group in ("eval", "benchmark") else "builder"
            command = args.command
            if kind == "evaluator" and command == "compare":
                flags = [value.split("=", 1)[0] for value in forward]
                if "--baseline-run" in flags and "--baseline" in flags:
                    raise SuiteError("use only one of --baseline-run and --baseline")
                forward = [
                    value.replace("--baseline-run", "--baseline", 1)
                    if value == "--baseline-run" or value.startswith("--baseline-run=")
                    else value
                    for value in forward
                ]
            python = interpreter(root, getattr(args, f"{kind}_python"), kind)
            module = (
                "eval_framework.cli" if kind == "evaluator" else "dataset_builder.cli"
            )
            if args.group == "benchmark":
                module = "eval_framework.benchmark.cli"
            return invoke(python, module, [command, *forward])
        if unknown:
            root_parser.error("unrecognized arguments: " + " ".join(unknown))
        if args.group == "readiness":
            from .readiness import execute

            args.mini_agent_root = args.mini_agent_root or root / "examples/mini_agent"
            return execute(
                args,
                interpreter(root, args.builder_python, "builder"),
                interpreter(root, args.evaluator_python, "evaluator"),
                invoke,
            )
        if args.group in ("bundle", "cap"):

            def validate(path):
                from .registry import tree_hash

                tree_hash(path)
                result = invoke(
                    interpreter(root, args.builder_python, "builder"),
                    "capability_snapshot_kit",
                    ["validate", "--input", str(path)],
                    capture=True,
                )
                if result.get("valid") is not True:
                    raise SuiteError("canonical protocol validation did not succeed")
                return result

            registry = BundleRegistry(root, validate)
            if args.command == "publish":
                result = registry.publish(args.input, args.agent, args.version)
            elif args.command == "resolve":
                result = registry.resolve(args.agent, args.version)
            elif args.command == "list":
                result = registry.list()
            elif args.command == "validate":
                result = validate(args.input)
            else:
                validate(args.old)
                validate(args.new)
                result = invoke(
                    interpreter(root, args.builder_python, "builder"),
                    "capability_snapshot_kit",
                    ["diff", "--old", str(args.old), "--new", str(args.new)],
                    capture=True,
                )
        else:
            from .sources import SourceRegistry

            registry = SourceRegistry(root)
            result = (
                registry.sync(args.name, args.repository, args.ref)
                if args.command == "sync"
                else registry.resolve(args.name, args.commit)
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (SuiteError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"eval-suite: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
