"""argparse CLI for frozen-dataset validation and benchmark execution."""

from __future__ import annotations

import argparse
import json
import tempfile
import warnings
import zipfile
from pathlib import Path
from uuid import uuid4

from .adjudication import import_reviews
from .comparison import compare_runs, write_comparison
from .compatibility import build_legacy_suite
from .compiled_execution import execute_compiled_suite
from .composition import default_plugin_catalog
from .contracts.compiler import (
    SuiteCompilationError,
    compile_suite,
    load_suite_definition,
)
from .contracts.store import ContractStore
from .dataset_loader import DatasetLoadError
from .evidence import atomic_json
from .gating import evaluate_gate, load_gate_policy, write_gate_result
from .judges.inspect import InspectJudgeClient
from .observability import export_run
from .phase2_schemas import ComparisonResult, JudgeRunConfig
from .provider import EvaluationPreflightError
from .reporting import write_invalid_run, write_report
from .result_loader import load_run_result
from .schemas import DatasetFilters, InvalidRunRecord, RunConfig
from .trace_analysis import analyze_run, write_run_analysis


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-evaluator")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--input")
    validate.add_argument("--agent-root")
    validate.add_argument("--binding")
    validate.add_argument("--output-dir")
    validate.add_argument("--suite")
    validate.add_argument("--dataset")
    validate.add_argument("--provider")
    validate.add_argument("--capability-bundle")
    run = commands.add_parser("run")
    run.add_argument("--input")
    run.add_argument("--agent-root")
    run.add_argument("--binding")
    run.add_argument("--suite")
    run.add_argument("--dataset")
    run.add_argument("--output-dir", required=True)
    run.add_argument("--provider")
    run.add_argument("--capability-bundle")
    run.add_argument(
        "--scope", action="append", choices=["module", "link", "end_to_end"]
    )
    run.add_argument("--task-id", action="append")
    run.add_argument("--label", action="append")
    run.add_argument("--case-id", action="append")
    run.add_argument("--run-mode", choices=["agent_benchmark"])
    run.add_argument("--pass-threshold", type=float)
    run.add_argument("--trials", type=int)
    run.add_argument("--judge-config")
    run.add_argument(
        "--conversation-completeness", action="store_true",
        help="opt-in diagnostic; requires the conversation extra and Judge env",
    )
    run.add_argument("--local-langfuse-config")
    run.add_argument(
        "--execution-type",
        choices=["auto", "full", "targeted_smoke", "filtered_subset"],
    )
    run.add_argument(
        "--allow-non-frozen-dataset",
        action="store_true",
        help="allow a provisional benchmark on a dataset that is not FROZEN",
    )
    export = commands.add_parser("export-langfuse")
    export.add_argument("--run-dir", required=True)
    export.add_argument("--include-content", action="store_true")
    sync_local = commands.add_parser("sync-local")
    sync_local.add_argument("--source", required=True)
    sync_local.add_argument("--local-langfuse-config")
    reviews = commands.add_parser("import-reviews")
    reviews.add_argument("--run-dir", required=True)
    analyze = commands.add_parser("analyze")
    analyze.add_argument("--run-dir", required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--candidate", required=True)
    compare.add_argument("--output-dir", required=True)
    gate = commands.add_parser("gate")
    gate.add_argument("--candidate", required=True)
    gate.add_argument("--comparison")
    gate.add_argument("--policy", required=True)
    gate.add_argument("--output-dir", required=True)
    return parser


def _legacy_run_options_used(args: argparse.Namespace) -> bool:
    value_names = (
        "scope",
        "task_id",
        "label",
        "case_id",
        "run_mode",
        "pass_threshold",
        "trials",
        "judge_config",
        "execution_type",
    )
    return (
        bool(getattr(args, "conversation_completeness", False))
        or any(getattr(args, name, None) is not None for name in value_names)
        or bool(getattr(args, "allow_non_frozen_dataset", False))
    )


def _compile_cli_suite(args: argparse.Namespace):
    if args.suite and args.dataset:
        raise ValueError("--suite cannot be combined with --dataset")
    if not args.suite and not args.dataset:
        raise ValueError("exactly one of --suite or --dataset is required")
    if args.suite:
        if (
            args.provider
            or args.capability_bundle
            or (args.command == "run" and _legacy_run_options_used(args))
        ):
            raise ValueError(
                "--suite cannot be combined with legacy dataset/provider/run flags"
            )
        loaded = load_suite_definition(args.suite)
    else:
        warnings.warn(
            "--dataset/--provider are deprecated; use --suite",
            DeprecationWarning,
            stacklevel=2,
        )
        filters = None
        if args.command == "run":
            filters = DatasetFilters(
                scopes=args.scope,
                task_ids=args.task_id,
                labels=args.label,
                case_ids=args.case_id,
            )
        config = RunConfig(
            conversation_completeness=(
                {} if getattr(args, "conversation_completeness", False) else None
            ),
            run_mode=(
                getattr(args, "run_mode", None)
                or (
                    "agent_benchmark"
                    if args.command == "run"
                    else "framework_self_test"
                )
            ),
            pass_threshold=(
                getattr(args, "pass_threshold", None)
                if getattr(args, "pass_threshold", None) is not None
                else 100.0
            ),
            execution_type=(getattr(args, "execution_type", None) or "auto"),
            filters=filters,
            allow_non_frozen_dataset=bool(
                getattr(args, "allow_non_frozen_dataset", False)
            ),
            trials_per_case=(
                getattr(args, "trials", None)
                if getattr(args, "trials", None) is not None
                else 1
            ),
            judge=(
                JudgeRunConfig(rubric_path=args.judge_config)
                if getattr(args, "judge_config", None)
                else None
            ),
        )
        loaded = build_legacy_suite(
            dataset=args.dataset,
            provider=args.provider or "mini_agent",
            capability_bundle=args.capability_bundle,
            filters=filters,
            run_config=config,
        )
    catalog = default_plugin_catalog()
    compiled = compile_suite(loaded, catalog, ContractStore(loaded.root))
    return loaded, catalog, compiled


def _input_kind(source: Path) -> tuple[str, Path]:
    """Route supported local inputs without importing or executing delivery code."""
    if source.is_dir():
        manifest = source / "manifest.json"
        if manifest.is_file():
            value = json.loads(manifest.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("dataset_format") in {
                "nanobot_candidate",
                "agent_candidate",
            }:
                return "candidate", source
        suites = sorted(
            set(source.glob("*.suite.json")) | set(source.glob("suite.json"))
        )
        if len(suites) > 1:
            raise ValueError("ambiguous Suite directory: select one Suite JSON file")
        return ("suite", suites[0]) if suites else ("candidate", source)
    if source.suffix.lower() == ".zip" or zipfile.is_zipfile(source):
        return "candidate", source
    if source.suffix.lower() == ".jsonl":
        return "dataset", source
    value = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        if {"dataset_loader", "dataset_sources", "provider"} <= value.keys():
            return "suite", source
        if {"case_id", "execution", "oracle"} <= value.keys():
            return "dataset", source
    raise ValueError(
        "--input requires a candidate directory/ZIP, Suite JSON or EvalCase JSONL"
    )


def _execution_exit_code(result) -> int:
    fatal = {"INITIALIZATION_ERROR", "EVALUATOR_ERROR"}
    return (
        3
        if any(
            case.execution_status in fatal or case.evaluation_validity == "INVALID"
            for case in result.cases
        )
        else 0
    )


def _finalize_local_delivery(source: str | Path, config_path: str | None) -> dict:
    """Keep display delivery failures separate from formal evaluation outcomes."""
    try:
        from .local_delivery import finalize_delivery

        return finalize_delivery(source, config_path=config_path)
    except Exception as exc:
        # Transport errors can contain credentials; never echo their raw text.
        return {
            "status": "PENDING",
            "error_type": type(exc).__name__,
            "message": "Local Langfuse delivery failed; saved results remain unchanged",
        }


def _with_local_delivery(
    payload: dict, source: str | Path, config_path: str | None
) -> dict:
    delivery = _finalize_local_delivery(source, config_path)
    if delivery.get("status") != "DISABLED":
        payload["delivery"] = delivery
    return payload


def _with_failure_delivery(payload: dict, args: argparse.Namespace) -> dict:
    """Save a status-only failure without replacing the original command error."""
    if args.command != "run":
        return payload
    error_code = (
        "EXECUTION_ERROR"
        if getattr(args, "_execution_started", False)
        else "ADMISSION_ERROR"
    )
    try:
        record = InvalidRunRecord(
            run_id=f"invalid_run_{uuid4().hex}",
            error_code=error_code,
            message=payload["message"],
            evidence_refs=[],
            provider_id=args.provider or "unknown",
            dataset_path=str(args.dataset or args.suite or args.input or "unknown"),
        )
        root = Path(args.output_dir).expanduser().resolve() / record.run_id
        root.mkdir(parents=True, exist_ok=False)
        record_path = root / "invalid_run.json"
        report_path = root / "report.md"
        atomic_json(record_path, record.model_dump(mode="json"))
        report_path.write_text(
            "\n".join(
                [
                    "# Agent 自动化评测报告",
                    "",
                    "> **评测结论：INVALID_RUN**",
                    ">",
                    "> 评测命令未完成。本失败记录不产生质量通过率；"
                    "如有已保存的正式结果，以正式结果为准。",
                    "",
                    f"- 错误阶段：`{error_code}`",
                    f"- 错误类型：`{payload['error_type']}`",
                    f"- 错误信息：{record.message}",
                    f"- 数据集：`{record.dataset_path}`",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        payload["failure_artifacts"] = {
            "status": "UNAVAILABLE",
            "error_type": type(exc).__name__,
            "message": "Failure report could not be saved; original error retained",
        }
        return payload
    payload.update(
        output_dir=str(root), record=str(record_path), report=str(report_path)
    )
    return _with_local_delivery(payload, root, args.local_langfuse_config)


def _candidate_input(args: argparse.Namespace, source: Path) -> int:
    from .onboarding import prepare_input

    if (
        args.provider
        or args.capability_bundle
        or (args.command == "run" and _legacy_run_options_used(args))
    ):
        raise ValueError("candidate --input cannot be combined with legacy run flags")
    binding = None
    if args.binding:
        binding = json.loads(
            Path(args.binding).expanduser().read_text(encoding="utf-8")
        )
        if not isinstance(binding, dict):
            raise ValueError("--binding must contain a trusted JSON object")
    output = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else Path(tempfile.mkdtemp(prefix="agent-evaluator-intake-"))
    )
    prepared = prepare_input(
        source,
        output,
        binding=binding,
        agent_root=Path(args.agent_root).expanduser().resolve()
        if args.agent_root
        else None,
    )
    catalog = default_plugin_catalog()
    compiled = []
    partitions = set()
    # Compile every partition before any Provider/Agent runtime can be created.
    for path in prepared.suite_paths:
        partition = path.stem.removeprefix("evaluator_").removesuffix(".suite")
        if not partition or partition in partitions:
            raise ValueError("duplicate or empty prepared Suite partition")
        partitions.add(partition)
        loaded = load_suite_definition(path)
        compiled.append(
            (partition, compile_suite(loaded, catalog, ContractStore(loaded.root)))
        )
    runs = []
    prepared.report["runs"] = runs
    exit_code = 5 if prepared.report["counts"]["blocked"] > 0 else 0
    if args.command == "run":
        for partition, suite in compiled:
            destination = output / "runs" / partition
            try:
                args._execution_started = True
                result = execute_compiled_suite(suite, catalog, output_dir=destination)
                paths = write_report(result, destination)
                runs.append(
                    {
                        "partition": partition,
                        "run_id": result.evaluator_run_id,
                        "paths": paths.model_dump(mode="json"),
                    }
                )
                if _execution_exit_code(result):
                    exit_code = 3
            except Exception as exc:
                # Retain each failure and continue independent already-compiled Suites.
                runs.append(
                    {
                        "partition": partition,
                        "error": {
                            "error_type": type(exc).__name__,
                            "message": str(exc),
                        },
                    }
                )
                exit_code = 3
            atomic_json(prepared.report_path, prepared.report)
    atomic_json(prepared.report_path, prepared.report)
    payload = {"valid": True, "intake": str(prepared.report_path), "runs": runs}
    if args.command == "run":
        _with_local_delivery(payload, prepared.report_path, args.local_langfuse_config)
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )
    return exit_code


def _route_input(args: argparse.Namespace) -> int | None:
    if args.agent_root and args.binding:
        raise ValueError("--agent-root cannot be combined with --binding")
    if not args.input:
        if args.agent_root or args.binding:
            raise ValueError("runtime binding flags require candidate --input")
        return None
    if args.suite or args.dataset:
        raise ValueError("--input cannot be combined with --suite or --dataset")
    source = Path(args.input).expanduser().resolve(strict=True)
    kind, path = _input_kind(source)
    if kind == "candidate":
        return _candidate_input(args, path)
    if args.agent_root or args.binding:
        raise ValueError(
            "--agent-root and --binding are only valid with candidate intake"
        )
    setattr(args, kind, str(path))
    return None


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "sync-local":
            delivery = _finalize_local_delivery(args.source, args.local_langfuse_config)
            print(json.dumps(delivery, ensure_ascii=False, indent=2))
            return 0 if delivery.get("status") == "ACCEPTED" else 3
        if args.command == "gate":
            comparison = None
            if args.comparison:
                comparison_path = Path(args.comparison).expanduser().resolve()
                if comparison_path.is_dir():
                    comparison_path = comparison_path / "comparison.json"
                comparison = ComparisonResult.model_validate_json(
                    comparison_path.read_bytes()
                )
            gate_result = evaluate_gate(
                load_run_result(args.candidate),
                load_gate_policy(args.policy),
                comparison,
            )
            paths = write_gate_result(gate_result, args.output_dir)
            print(paths.model_dump_json(indent=2))
            return {
                "PASS": 0,
                "INVALID_COMPARISON": 2,
                "FAIL": 4,
                "REVIEW_REQUIRED": 5,
            }[gate_result.conclusion]
        if args.command == "compare":
            comparison = compare_runs(
                load_run_result(args.baseline),
                load_run_result(args.candidate),
            )
            paths = write_comparison(comparison, args.output_dir)
            print(paths.model_dump_json(indent=2))
            return 0 if comparison.status == "COMPARABLE" else 2
        if args.command == "analyze":
            loaded = load_run_result(args.run_dir)
            analysis = analyze_run(
                loaded.result,
                source_results_sha256=loaded.sha256,
            )
            paths = write_run_analysis(analysis, Path(args.run_dir))
            print(paths.model_dump_json(indent=2))
            return 0
        if args.command == "export-langfuse":
            print(
                json.dumps(
                    export_run(args.run_dir, include_content=args.include_content),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "import-reviews":
            print(
                json.dumps(import_reviews(args.run_dir), ensure_ascii=False, indent=2)
            )
            return 0
        routed = _route_input(args)
        if routed is not None:
            return routed
        loaded, catalog, compiled = _compile_cli_suite(args)
        if args.command == "validate":
            print(
                json.dumps(
                    {
                        "valid": True,
                        "suite_id": compiled.suite_id,
                        "compiled_suite_sha256": compiled.compiled_suite_sha256,
                        "path": compiled.dataset.path,
                        "sha256": compiled.dataset.sha256,
                        "case_count": len(compiled.dataset.cases),
                    },
                    indent=2,
                )
            )
            return 0
        judge_client = (
            InspectJudgeClient.from_env(
                timeout_seconds=compiled.run_config.judge.timeout_seconds
            )
            if loaded.origin == "legacy_compatibility"
            and compiled.run_config.judge is not None
            else None
        )
        args._execution_started = True
        result = execute_compiled_suite(
            compiled,
            catalog,
            legacy_judge_client=judge_client,
            output_dir=args.output_dir,
        )
        paths = write_report(
            result,
            Path(args.output_dir),
        )
        payload = _with_local_delivery(
            paths.model_dump(mode="json"), paths.output_dir, args.local_langfuse_config
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return _execution_exit_code(result)
    except (EvaluationPreflightError, SuiteCompilationError) as exc:
        if getattr(args, "command", None) == "run":
            record = InvalidRunRecord(
                run_id=f"invalid_run_{uuid4().hex}",
                error_code=exc.code,
                message=str(exc),
                evidence_refs=exc.evidence_refs,
                provider_id=getattr(args, "provider", None) or "unknown",
                dataset_path=str(
                    getattr(args, "dataset", None)
                    or getattr(args, "suite", None)
                    or getattr(args, "input", None)
                    or "unknown"
                ),
                issues=(
                    [item.model_dump(mode="json") for item in exc.issues]
                    if isinstance(exc, SuiteCompilationError)
                    else []
                ),
            )
            paths = write_invalid_run(exc, record, Path(args.output_dir))
            payload = _with_local_delivery(
                paths.model_dump(mode="json"),
                paths.output_dir,
                args.local_langfuse_config,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            payload = {
                "error_type": type(exc).__name__,
                "error_code": exc.code,
                "message": str(exc),
                "evidence_refs": exc.evidence_refs,
            }
            if isinstance(exc, SuiteCompilationError):
                payload["issues"] = [
                    item.model_dump(mode="json") for item in exc.issues
                ]
            print(json.dumps(payload))
        return 2
    except (DatasetLoadError, OSError, ValueError) as exc:
        payload = _with_failure_delivery(
            {"error_type": type(exc).__name__, "message": str(exc)}, args
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    except Exception as exc:
        message = (
            "Langfuse request failed; automatic results remain unchanged"
            if args.command in {"export-langfuse", "import-reviews"}
            else str(exc)
        )
        payload = _with_failure_delivery(
            {"error_type": type(exc).__name__, "message": message}, args
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
