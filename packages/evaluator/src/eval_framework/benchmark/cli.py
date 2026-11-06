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
    from .analysis_cli import add_commands

    add_commands(sub)
    for name in ("core-validate", "core-run"):
        child = sub.add_parser(name, help="离线 nanobot 核心组件基准（不调用模型）")
        child.add_argument(
            "--dataset", type=Path, default=Path("data/benchmarks/nanobot-core-v1")
        )
        if name == "core-run":
            child.add_argument("--config", type=Path, required=True)
            child.add_argument("--output", type=Path, required=True)
            child.add_argument("--repeats", type=int, default=3)
            child.add_argument("--concurrency", type=int, default=4)
    coverage = sub.add_parser(
        "coverage", help="按源码、profile、冻结数据和执行证据生成覆盖矩阵"
    )
    coverage.add_argument("--config", type=Path, required=True)
    coverage.add_argument(
        "--catalog", type=Path, default=Path("data/coverage/nanobot-v1/catalog.json")
    )
    coverage.add_argument("--core-dataset", type=Path, action="append", default=[])
    coverage.add_argument("--file-dataset", type=Path, action="append", default=[])
    coverage.add_argument("--run", type=Path, action="append", default=[])
    coverage.add_argument("--legacy-run", type=Path, action="append", default=[])
    coverage.add_argument("--output", type=Path, required=True)
    for name in ("validate", "demo", "run"):
        child = sub.add_parser(name)
        child.add_argument(
            "--dataset",
            type=Path,
            default=(
                Path("data/benchmarks/file-tools-v1/tasks.jsonl")
                if name == "validate" else None
            ),
        )
        child.add_argument("--level", choices=["module", "chain", "e2e"])
        if name != "validate":
            child.add_argument("--output", type=Path, required=True)
            child.add_argument("--limit", type=int)
            child.add_argument("--split", choices=["dev", "holdout"])
            child.add_argument("--repeats", type=int)
            child.add_argument("--concurrency", type=int)
            child.add_argument("--config", type=Path)
    judge = sub.add_parser(
        "judge", help="DeepEval native metrics and GEval on saved execution evidence"
    )
    judge.add_argument("--source", type=Path, required=True)
    judge.add_argument("--dataset", type=Path, required=True)
    judge.add_argument("--output", type=Path, required=True)
    judge.add_argument("--config", type=Path, required=True)
    judge.add_argument("--repeats", type=int, default=1)
    judge.add_argument("--concurrency", type=int, default=2)
    judge.add_argument("--limit", type=int)
    calibration = sub.add_parser("calibration-sheet")
    calibration.add_argument("--run", type=Path, required=True)
    calibration.add_argument("--output", type=Path, required=True)
    annotation = sub.add_parser(
        "calibration-page", help="Render a blank offline annotation page"
    )
    annotation.add_argument("--worksheet", type=Path, required=True)
    annotation.add_argument("--output", type=Path, required=True)
    calibrate = sub.add_parser("calibration-check")
    calibrate.add_argument("--run", type=Path, required=True)
    calibrate.add_argument("--labels", type=Path, required=True)
    calibrate.add_argument("--threshold", type=float, required=True)
    calibrate.add_argument("--threshold-version", required=True)
    calibrate.add_argument("--output", type=Path, required=True)
    calibrate.add_argument(
        "--report", type=Path, help="Optional Markdown diagnostic report"
    )
    audit = sub.add_parser(
        "quality-audit", help="Diagnose saved file-tool evidence offline"
    )
    audit.add_argument("--run", type=Path, action="append", required=True)
    audit.add_argument("--dataset", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    audit.add_argument("--baseline", type=Path)
    audit.add_argument("--candidate", type=Path)
    compare = sub.add_parser("compare")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument(
        "--view-dir",
        type=Path,
        help="Also bundle both saved runs in the native Inspect comparison viewer",
    )
    regrade = sub.add_parser("regrade")
    regrade.add_argument("--source", type=Path, required=True)
    regrade.add_argument("--output", type=Path, required=True)
    regrade.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/benchmarks/file-tools-v1/tasks.jsonl"),
    )
    for name in ("export-langfuse", "export-langfuse-evidence", "verify-langfuse"):
        child = sub.add_parser(name)
        child.add_argument("--run", type=Path, required=True)
        child.add_argument(
            "--dataset",
            type=Path,
            default=Path("data/benchmarks/file-tools-v1/tasks.jsonl"),
        )
    report = sub.add_parser("report")
    report.add_argument("--run", type=Path, required=True)
    report.add_argument(
        "--format",
        choices=["auto", "inspect", "domain"],
        default="auto",
        help="Prefer native Inspect View; domain retains the historical report",
    )
    for child in sub.choices.values():
        child.add_argument(
            "--env-file",
            action="append",
            default=argparse.SUPPRESS,
            help="Explicit dotenv path; may follow the command",
        )
    args = parser.parse_args(argv)
    if args.command == "analyze":
        from .analysis_cli import execute

        print(json.dumps(execute(args), ensure_ascii=False, indent=2))
        return 0
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

    def legacy_command_config(path: Path) -> dict:
        from ..orchestration.config import is_run_request, read_config_json

        value = read_config_json(path)
        if is_run_request(value):
            parser.error("composed RunRequest configuration supports run/demo only")
        return value

    if args.command in ("core-validate", "core-run"):
        from .core_tasks import core_dataset_identity, load_core_tasks

        if args.command == "core-validate":
            tasks = load_core_tasks(args.dataset)
            result = {
                "tasks": len(tasks),
                "splits": dict(Counter(t["split"] for t in tasks)),
                "components": dict(Counter(t["component"] for t in tasks)),
                "executed": False,
                "identity": core_dataset_identity(args.dataset),
            }
        else:
            from .core_runner import run_core_benchmark

            result = run_core_benchmark(
                args.dataset,
                legacy_command_config(args.config),
                args.output,
                repeats=args.repeats,
                concurrency=args.concurrency,
            )["summary"]
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "coverage":
        import hashlib

        from .capability_coverage import build_coverage_report, snapshot_nanobot
        from .core_tasks import core_dataset_identity
        from .runner import digest

        if args.output.exists():
            parser.error("coverage output already exists")
        datasets = []
        for kind, paths, identity_fn, profile in (
            ("core", args.core_dataset, core_dataset_identity, "core_modules"),
            ("file_tools", args.file_dataset, dataset_identity, "file_tools"),
        ):
            for path in paths:
                identity = identity_fn(path)
                datasets.append(
                    {
                        "path": path,
                        "kind": kind,
                        "identity": identity,
                        "identity_hash": digest(identity),
                        "profile": profile,
                    }
                )
        runs = []
        for kind, paths in (("current", args.run), ("legacy", args.legacy_run)):
            for path in paths:
                source = path / "results.json" if path.is_dir() else path
                runs.append(
                    {
                        "path": source,
                        "kind": kind,
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    }
                )
        snapshot = snapshot_nanobot(legacy_command_config(args.config))
        result = build_coverage_report(
            snapshot, json.loads(args.catalog.read_text()), datasets, runs
        )
        save_json(args.output / "snapshot.json", snapshot)
        save_json(args.output / "coverage.json", result)
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "snapshot_hash": snapshot["snapshot_hash"],
                },
                ensure_ascii=False,
            )
        )
    elif args.command in ("validate", "demo", "run"):
        config = {}
        if args.command != "validate":
            from ..orchestration import BenchmarkSpec, ExecutionSpec, load_run_request
            from ..orchestration.config import legacy_run_request

            if args.command == "run" and args.config is None:
                parser.error(
                    "run requires --config; demo is the offline reference smoke"
                )
            try:
                request = (
                    load_run_request(args.config)
                    if args.config else legacy_run_request({})
                )
                # Explicit flags override configured values, then historical defaults.
                selection = request.benchmark.model_dump()
                execution = request.execution.model_dump()
                for key in selection:
                    value = getattr(args, key)
                    if value is not None:
                        selection[key] = str(value) if key == "dataset" else value
                for key in execution:
                    if getattr(args, key) is not None:
                        execution[key] = getattr(args, key)
                selection = BenchmarkSpec.model_validate(selection).model_dump()
                execution = ExecutionSpec.model_validate(execution).model_dump()
            except (OSError, ValueError) as exc:
                parser.error(str(exc))
            for key, value in {**selection, **execution}.items():
                setattr(args, key, Path(value) if key == "dataset" else value)
            config = request.runtime_config()
        tasks = load_tasks(args.dataset)
        if args.level:
            tasks = [t for t in tasks if t.get("evaluation_level", "e2e") == args.level]
        if args.command == "validate":
            from .oracle import evaluate_oracle, reference_observation

            bad = [
                t["id"]
                for t in tasks
                if t.get("execution_mode", "agent") == "agent"
                and not evaluate_oracle(t, reference_observation(t))["success"]
            ]
            result = {
                "tasks": len(tasks),
                "categories": dict(Counter(t["category"] for t in tasks)),
                "splits": dict(Counter(t["split"] for t in tasks)),
                "reference_failures": bad,
                "module_execution_not_performed": sum(
                    t.get("execution_mode") in ("module", "decision") for t in tasks
                ),
                "identity": dataset_identity(args.dataset),
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return bool(bad)
        if args.command == "demo" and any(
            t.get("execution_mode", "agent") != "agent" for t in tasks
        ):
            parser.error(
                "reference demo supports Agent tasks; select --level chain or e2e"
            )
        selected = select_tasks(
            [
                t
                for t in tasks
                if not args.level or t.get("evaluation_level", "e2e") == args.level
            ],
            limit=args.limit,
            split=args.split,
        )
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
    elif args.command == "judge":
        from .judge_run import judge_run

        result = judge_run(
            args.source,
            args.dataset,
            args.output,
            legacy_command_config(args.config),
            repeats=args.repeats,
            concurrency=args.concurrency,
            limit=args.limit,
        )
        print(json.dumps(result["judge_summary"], ensure_ascii=False, indent=2))
    elif args.command == "calibration-sheet":
        from .judge_calibration import create_calibration_worksheet

        result = create_calibration_worksheet(
            json.loads((args.run / "results.json").read_text())
        )
        if args.output.exists():
            parser.error("calibration output already exists")
        save_json(args.output, result)
    elif args.command == "calibration-page":
        from .calibration_reporting import render_annotation_html

        if args.output.exists():
            parser.error("annotation output already exists")
        page = render_annotation_html(json.loads(args.worksheet.read_text()))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(page)
    elif args.command == "calibration-check":
        from .calibration_reporting import render_calibration_report
        from .judge_calibration import compare_human_labels

        if args.output.exists() or (args.report and args.report.exists()):
            parser.error("calibration output already exists")
        if args.report and args.report.resolve() == args.output.resolve():
            parser.error("calibration JSON and Markdown output must be different")

        result = compare_human_labels(
            json.loads((args.run / "results.json").read_text()),
            json.loads(args.labels.read_text()),
            threshold=args.threshold,
            threshold_version=args.threshold_version,
        )
        report = render_calibration_report(result) if args.report else None
        save_json(args.output, result)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(report)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "quality-audit":
        from .quality_audit import build_quality_audit

        result = build_quality_audit(
            args.run,
            args.dataset,
            args.output,
            baseline=args.baseline,
            candidate=args.candidate,
        )
        print(json.dumps(result["repetition"], ensure_ascii=False, indent=2))
    elif args.command == "compare":
        result = compare_runs(
            json.loads((args.baseline / "results.json").read_text()),
            json.loads((args.candidate / "results.json").read_text()),
        )
        if args.view_dir:
            from .native_reporting import write_comparison_report

            result["inspect_view"] = str(
                write_comparison_report(args.baseline, args.candidate, args.view_dir)
            )
        save_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "regrade":
        from .regrade import regrade_run

        result = regrade_run(args.source, args.dataset, args.output)
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    elif args.command in (
        "export-langfuse",
        "export-langfuse-evidence",
        "verify-langfuse",
    ):
        from ..optional_dependencies import (
            MissingOptionalDependencyError,
            require_langfuse,
        )

        try:
            require_langfuse()
        except MissingOptionalDependencyError as exc:
            print(json.dumps({"error_type": type(exc).__name__, "message": str(exc)}))
            return 2
        from .langfuse_export import export_metadata_evidence, export_run, verify_run

        operation = {
            "export-langfuse": export_run,
            "export-langfuse-evidence": export_metadata_evidence,
            "verify-langfuse": verify_run,
        }[args.command]
        result = operation(args.run, args.dataset)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "verify-langfuse":
            return 0 if result["status"] == "VERIFIED" else 1
    elif args.command == "report":
        from .report import write_report

        print(write_report(args.run, format=args.format))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
