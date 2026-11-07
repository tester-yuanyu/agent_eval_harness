#!/usr/bin/env python3
"""显式运行已冻结代表集；不自动 Judge 或上传。"""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=Path("data/benchmarks/mini-agent-v1.1.1")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--max-model-requests", type=int, default=60)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    args = parser.parse_args()
    if not 1 <= args.max_model_requests <= 60:
        parser.error("max-model-requests must be within 1..60")
    if args.output.exists():
        raise ValueError("Use a fresh run directory; budget cannot reset by resuming")
    from dotenv import load_dotenv
    from eval_framework.benchmark.mini_scoring import MiniAgentDomain
    from eval_framework.benchmark.provider_tasks import (
        load_provider_tasks,
        provider_dataset_identity,
    )
    from eval_framework.benchmark.report import write_report
    from eval_framework.benchmark.runner import run_benchmark

    load_dotenv(args.env_file, override=False)
    dataset = args.dataset.resolve()
    coverage = json.loads((dataset / "coverage.json").read_text())
    tasks = {t["id"]: t for t in load_provider_tasks(dataset)}
    ids = args.case or coverage["smoke_case_ids"]
    if len(ids) != len(set(ids)) or not set(ids) <= set(coverage["smoke_case_ids"]):
        parser.error("case selection must be unique representative case IDs")
    selected = [tasks[i] for i in ids]
    model = os.environ["OPENCODE_MODEL"]
    config = {
        "provider": "mini_agent",
        "model": model,
        "base_url": os.environ["OPENCODE_BASE_URL"],
        "api_key_env": "OPENCODE_API_KEY",
        "inspect_model": "openai-api/opencode/" + model,
        "temperature": 0,
        "max_tokens": 2048,
        "max_steps": 4,
        "timeout_seconds": args.timeout_seconds,
        "token_limit": 16384,
        "max_model_requests": args.max_model_requests,
        "sandbox": "docker",
        "extra_body": {"thinking": {"type": "disabled"}},
        "repository_root": str(Path(__file__).resolve().parents[1]),
        "capability_bundle": str(dataset / "capability_bundle"),
    }
    result = run_benchmark(
        selected,
        dataset=provider_dataset_identity(dataset),
        config=config,
        output=args.output,
        repeats=1,
        concurrency=2,
        domain=MiniAgentDomain(dataset),
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(write_report(args.output, format="domain"))


if __name__ == "__main__":
    main()
