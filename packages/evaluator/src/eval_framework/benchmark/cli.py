"""Benchmark-first CLI. Live calls and remote exports are explicit commands."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        action="append",
        default=[],
        help="Explicit dotenv path; secrets stay in process environment",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "demo", "run"):
        child = sub.add_parser(name)
        child.add_argument(
            "--dataset",
            type=Path,
            default=Path("data/benchmarks/file-tools-v1/tasks.jsonl"),
        )
        if name != "validate":
            child.add_argument("--output", type=Path, required=True)
            child.add_argument("--limit", type=int)
            child.add_argument("--split", choices=["dev", "holdout"])
            child.add_argument("--repeats", type=int, default=1)
            child.add_argument("--concurrency", type=int, default=4)
            child.add_argument("--config", type=Path)
    compare = sub.add_parser("compare")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    regrade = sub.add_parser("regrade")
    regrade.add_argument("--source", type=Path, required=True)
    regrade.add_argument("--output", type=Path, required=True)
    regrade.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/benchmarks/file-tools-v1/tasks.jsonl"),
    )
    for name in ("export-langfuse", "verify-langfuse"):
        child = sub.add_parser(name)
        child.add_argument("--run", type=Path, required=True)
        child.add_argument(
            "--dataset",
            type=Path,
            default=Path("data/benchmarks/file-tools-v1/tasks.jsonl"),
        )
    report = sub.add_parser("report")
    report.add_argument("--run", type=Path, required=True)
    for child in sub.choices.values():
        child.add_argument(
            "--env-file",
            action="append",
            default=argparse.SUPPRESS,
            help="Explicit dotenv path; may follow the command",
        )
    args = parser.parse_args(argv)
    # Disable optional library telemetry; never disable benchmark evidence.
    os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    os.environ.setdefault("CONFIDENT_REGION", "US")
    if args.env_file:
        from dotenv import load_dotenv

        for path in args.env_file:
            if not Path(path).is_file():
                parser.error("env file not found")
            load_dotenv(path, override=False)
    from .runner import compare_runs, run_benchmark, save_json
    from .tasks import dataset_identity, load_tasks, select_tasks

    if args.command in ("validate", "demo", "run"):
        tasks = load_tasks(args.dataset)
        if args.command == "validate":
            from .oracle import evaluate_oracle, reference_observation

            bad = [
                t["id"]
                for t in tasks
                if not evaluate_oracle(t, reference_observation(t))["success"]
            ]
            result = {
                "tasks": len(tasks),
                "categories": dict(Counter(t["category"] for t in tasks)),
                "splits": dict(Counter(t["split"] for t in tasks)),
                "reference_failures": bad,
                "identity": dataset_identity(args.dataset),
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return bool(bad)
        if args.command == "run" and args.config is None:
            parser.error("run requires --config; demo is the offline reference smoke")
        config = json.loads(args.config.read_text()) if args.config else {}
        selected = select_tasks(tasks, limit=args.limit, split=args.split)
        result = run_benchmark(
            selected,
            dataset=dataset_identity(args.dataset),
            config=config,
            output=args.output,
            repeats=args.repeats,
            concurrency=args.concurrency,
            offline=args.command == "demo",
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    elif args.command == "compare":
        result = compare_runs(
            json.loads((args.baseline / "results.json").read_text()),
            json.loads((args.candidate / "results.json").read_text()),
        )
        save_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "regrade":
        from .regrade import regrade_run

        result = regrade_run(args.source, args.dataset, args.output)
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    elif args.command in ("export-langfuse", "verify-langfuse"):
        from .langfuse_export import export_run, verify_run

        result = (export_run if args.command == "export-langfuse" else verify_run)(
            args.run, args.dataset
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "verify-langfuse":
            return 0 if result["status"] == "VERIFIED" else 1
    elif args.command == "report":
        from .report import write_report

        print(write_report(args.run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
