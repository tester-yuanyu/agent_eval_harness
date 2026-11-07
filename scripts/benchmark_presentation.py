#!/usr/bin/env python3
"""离线诊断与可选 Langfuse 展示；不会调用模型或重评分。"""

import argparse
import json
import os
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--sync-langfuse", action="store_true")
    parser.add_argument("--dashboard", action="store_true")
    parser.add_argument("--trend", action="store_true", help="生成同口径运行趋势")
    parser.add_argument("--trend-run", action="append", default=[], type=Path)
    parser.add_argument("--refresh-dashboard", action="store_true")
    args = parser.parse_args()
    if args.trend_run and not args.trend:
        parser.error("--trend-run requires --trend")
    if args.refresh_dashboard and not args.dashboard:
        parser.error("--refresh-dashboard requires --dashboard")
    trend = None
    if args.trend:
        from eval_framework.benchmark.report_trends import load_trend

        trend = load_trend([args.run, *args.trend_run])
        (args.run / "trend.json").write_text(
            json.dumps(trend, ensure_ascii=False, indent=2) + "\n"
        )
    if args.profile:
        target = args.run / "report-diagnostics.json"
        if target.exists() and target.read_bytes() != args.profile.read_bytes():
            raise ValueError(
                "existing diagnostic profile differs; archive it explicitly"
            )
        shutil.copyfile(args.profile, target)
    from eval_framework.benchmark.report import write_domain_report

    if args.sync_langfuse:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        from eval_framework.benchmark.langfuse_presentation import (
            create_dashboard,
            sync_diagnostics,
        )

        status = sync_diagnostics(args.run, base_url=os.environ["LANGFUSE_BASE_URL"])
        print(
            json.dumps(
                {
                    k: status[k]
                    for k in ("status", "annotation_count", "trace_count")
                    if k in status
                }
            )
        )
        trend_verified = True
        if args.trend:
            from eval_framework.benchmark.langfuse_trends import sync_trends

            trend_status = sync_trends(args.run, [args.run, *args.trend_run])
            trend_verified = trend_status["status"] == "VERIFIED"
            print(json.dumps({"trend_status": trend_status["status"]}))
        if args.dashboard and status["status"] == "VERIFIED" and trend_verified:
            print(
                create_dashboard(
                    args.run,
                    base_url=os.environ["LANGFUSE_BASE_URL"],
                    refresh=args.refresh_dashboard,
                    trend=trend,
                )["url"]
            )
    elif args.dashboard:
        parser.error("--dashboard requires --sync-langfuse")
    print(write_domain_report(args.run))


if __name__ == "__main__":
    main()
