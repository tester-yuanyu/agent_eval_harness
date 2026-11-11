#!/usr/bin/env python3
"""v4正式评测：显式运行真实模型、G-Eval、报告及Langfuse交付。"""

import argparse
import json
import os
from pathlib import Path


def main():
    from dotenv import load_dotenv
    from eval_framework.benchmark.full_adapter import FullBenchmarkFactory
    from eval_framework.benchmark.full_benchmark import (
        FullBenchmarkDomain,
        dataset_identity,
        load_tasks,
    )
    from eval_framework.benchmark.judge_run import judge_run
    from eval_framework.benchmark.langfuse_export import (
        export_metadata_evidence,
        export_run,
        verify_run,
    )
    from eval_framework.benchmark.report import write_report
    from eval_framework.benchmark.runner import run_benchmark
    from eval_framework.provider_registry import ProviderRegistry

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "command",
        choices=[
            "validate",
            "run",
            "resume",
            "retry",
            "judge",
            "report",
            "export",
            "verify",
            "sync",
            "report-view",
            "dashboard",
        ],
    )
    p.add_argument(
        "--dataset",
        type=Path,
        default=Path("output/mini_agent_full_eval_20261111_v4/dataset"),
    )
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--env-file", type=Path, default=Path(".env"))
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument(
        "--source",
        type=Path,
        help="retry/judge的原始执行目录，或report-view/dashboard的保存结果目录",
    )
    p.add_argument(
        "--reuse-judge", type=Path, help="同一执行/配置的已评分目录；保留有效项"
    )
    p.add_argument("--metric-concurrency", type=int, default=1)
    p.add_argument("--request-retries", type=int, default=1, choices=range(4))
    p.add_argument(
        "--profile", type=Path, help="sync/dashboard必须显式选择local/cloud profile"
    )
    p.add_argument("--log-realtime", action="store_true")
    args = p.parse_args()
    load_dotenv(args.env_file, override=False)
    root = Path(__file__).resolve().parents[1]
    dataset = args.dataset.resolve()
    output = args.output.resolve()
    execution = output / "execution"
    judged = output / "judged"
    model = os.environ.get("OPENCODE_MODEL")
    base = os.environ.get("OPENCODE_BASE_URL")
    if args.command == "validate":
        tasks = load_tasks(dataset)
        print(
            json.dumps(
                {
                    "identity": dataset_identity(dataset),
                    "real_model_cases": sum(t["live"] for t in tasks),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command in {"run", "resume", "retry"}:
        if args.command == "run" and execution.exists():
            raise ValueError(
                "Use a new execution directory; no implicit paid rerun/resume"
            )
        if args.command == "retry":
            from eval_framework.benchmark.execution_recovery import prepare_recovery

            if args.source is None:
                p.error("retry requires --source original-execution-directory")
            prepare_recovery(args.source, execution)
        if args.command == "run" and (not model or not base):
            p.error("run requires OPENCODE_MODEL and OPENCODE_BASE_URL")
        config = dict(
            provider="mini_agent_full",
            model=model,
            base_url=base,
            api_key_env="OPENCODE_API_KEY",
            inspect_model="openai-api/opencode/" + (model or ""),
            temperature=0,
            max_tokens=2048,
            max_steps=4,
            timeout_seconds=240,
            token_limit=16384,
            max_model_requests=400,
            sandbox="docker",
            extra_body={"thinking": {"type": "disabled"}},
            repository_root=str(root),
            capability_bundle=str(dataset / "source_delivery/bundle"),
            dataset_path=str(dataset),
            preflight=True,
            log_realtime=args.log_realtime,
        )
        if args.command in {"resume", "retry"}:
            config = json.loads((execution / "run.json").read_text())["config"]
        registry = ProviderRegistry()
        registry.register("mini_agent_full", FullBenchmarkFactory())
        result = run_benchmark(
            load_tasks(dataset),
            dataset=dataset_identity(dataset),
            config=config,
            output=execution,
            repeats=1,
            concurrency=args.concurrency,
            provider_registry=registry,
            domain=FullBenchmarkDomain(dataset),
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    elif args.command == "judge":
        execution = args.source.resolve() if args.source else execution
        config = dict(
            model=model,
            base_url=base,
            api_key_env="OPENCODE_API_KEY",
            max_tokens=2048,
            timeout=60,
            dimensions=[
                "action_appropriateness",
                "recovery_appropriateness",
                "response_groundedness",
            ],
            max_evaluations=16,
            extra_body={"thinking": {"type": "disabled"}},
        )
        result = judge_run(
            execution,
            dataset,
            judged,
            config,
            repeats=1,
            concurrency=args.concurrency,
            options={
                "metric_checkpoints": True,
                "metric_concurrency": args.metric_concurrency,
                "request_retries": args.request_retries,
                "preflight": True,
                "retry_failed": bool(args.reuse_judge),
                **({"reuse_from": str(args.reuse_judge)} if args.reuse_judge else {}),
            },
        )
        print(json.dumps(result["judge_summary"], ensure_ascii=False, indent=2))
    elif args.command == "report-view":
        from eval_framework.benchmark.report_view import create_report_view

        if args.source is None:
            p.error("report-view requires --source saved-judged-directory")
        print(create_report_view(args.source, output))
    elif args.command == "dashboard":
        from eval_framework.benchmark.dashboard_delivery import deliver_dashboard
        from eval_framework.benchmark.langfuse_delivery import load_profile

        if args.source is None or args.profile is None:
            p.error("dashboard requires --source saved-judged-directory and --profile")
        status = deliver_dashboard(
            args.source, profile=load_profile(args.profile), output=output
        )
        print(json.dumps(status, ensure_ascii=False))
        if status["delivery_status"] != "COMPLETE":
            raise SystemExit(1)
    elif args.command == "sync":
        from eval_framework.benchmark.langfuse_delivery import load_profile, sync_run

        if args.profile is None:
            p.error("sync requires explicit --profile")
        status = sync_run(
            judged, dataset, profile=load_profile(args.profile), dashboard=True
        )
        print(json.dumps(status, ensure_ascii=False))
        if status.get("delivery_status") != "COMPLETE":
            raise SystemExit(1)
    elif args.command == "report":
        print(write_report(judged, format="domain"))
        print(write_report(execution, format="inspect"))
    elif args.command == "export":
        print(json.dumps(export_run(judged, dataset), ensure_ascii=False))
        print(json.dumps(export_metadata_evidence(judged, dataset), ensure_ascii=False))
    else:
        print(json.dumps(verify_run(judged, dataset), ensure_ascii=False))


if __name__ == "__main__":
    main()
