"""离线分析命令装配，旧评测入口无需导入分析实现。"""

from pathlib import Path


def add_commands(sub):
    parser = sub.add_parser("analyze", help="只读保存结果，生成独立本地分析")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-artifact", type=Path, action="append", default=[])
    parser.add_argument("--judge-source", type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--k", type=int, nargs="+", default=[1, 3, 5])
    parser.add_argument("--repeat-protocol", type=Path)


def execute(args):
    from eval_contracts.benchmark_analysis import AnalysisPolicy

    from .analysis_report import write_analysis
    from .analysis_sources import read_json

    policy = AnalysisPolicy(
        ks=tuple(args.k),
        repeat_protocol=read_json(args.repeat_protocol)[0]
        if args.repeat_protocol
        else None,
    )
    return {
        k: str(v)
        for k, v in write_analysis(
            args.run,
            dataset_path=args.dataset,
            annotations_path=args.annotations,
            output=args.output,
            policy=policy,
            source_artifacts=tuple(args.source_artifact),
            judge_dir=args.judge_source,
        ).items()
    }
