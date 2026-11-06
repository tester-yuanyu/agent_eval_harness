"""Explicit opt-in entry point for mini_agent benchmark delivery."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .mini_dataset import build_dataset
from .provider_tasks import load_provider_tasks, provider_dataset_identity


def main():
    parser = argparse.ArgumentParser(
        description="mini_agent 真实模型评测；run/export 显式执行外部请求"
    )
    parser.add_argument(
        "command", choices=["build", "validate", "run", "report", "export", "verify"]
    )
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument(
        "--dataset", type=Path, default=Path("data/benchmarks/mini-agent-v1.0.1")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/mini-agent/full")
    )
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--pilot", action="store_true")
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv

        load_dotenv(args.env_file, override=False)
    if args.command == "build":
        build_dataset(args.dataset, args.repository)
    elif args.command == "run":
        from .mini_scoring import MiniAgentDomain
        from .runner import run_benchmark

        tasks = load_provider_tasks(args.dataset)
        if args.pilot:
            tasks = [tasks[0], tasks[42], tasks[65], tasks[93], tasks[94], tasks[100]]
        config = json.loads(args.config.read_text()) if args.config else {}
        config = {
            "provider": "mini_agent",
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"),
            "base_url": os.environ.get(
                "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
            ),
            "api_key_env": "DEEPSEEK_API_KEY",
            "temperature": 0,
            "max_tokens": 2048,
            "max_steps": 4,
            "timeout_seconds": 120,
            "token_limit": 16384,
            "sandbox": "docker",
            "extra_body": {"thinking": {"type": "disabled"}},
            **config,
            "repository_root": str(args.repository.resolve()),
            "capability_bundle": str((args.dataset / "capability_bundle").resolve()),
        }
        result = run_benchmark(
            tasks,
            dataset=provider_dataset_identity(args.dataset),
            config=config,
            output=args.output,
            concurrency=4,
            domain=MiniAgentDomain(args.dataset),
        )
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    elif args.command == "report":
        from .report import write_report

        print(write_report(args.output))
    elif args.command in {"export", "verify"}:
        from .langfuse_export import export_run, verify_run

        result = (export_run if args.command == "export" else verify_run)(
            args.output, args.dataset
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "tasks": len(load_provider_tasks(args.dataset)),
                    "identity": provider_dataset_identity(args.dataset),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
