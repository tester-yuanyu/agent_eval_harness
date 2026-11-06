"""离线分析命令装配，旧评测入口无需导入分析实现。"""

from pathlib import Path


def add_commands(sub):
    for name in ("annotations-build", "annotations-validate"):
        child = sub.add_parser(name, help="构建 proposed 或只读校验独立注释资产")
        child.add_argument("--dataset", type=Path, required=True)
        child.add_argument("--annotation-registry", type=Path)
        child.add_argument(
            "--output" if name == "annotations-build" else "--annotations",
            type=Path,
            required=True,
        )
        if name == "annotations-build":
            child.add_argument("--version", default="1.0.0")

    parser = sub.add_parser("analyze", help="只读保存结果，生成独立本地分析")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-artifact", type=Path, action="append", default=[])
    parser.add_argument("--judge-source", type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--annotation-registry", type=Path)
    parser.add_argument("--k", type=int, nargs="+", default=[1, 3, 5])
    parser.add_argument("--repeat-protocol", type=Path)
    parser.add_argument("--compare-with", type=Path)
    parser.add_argument("--comparison-dataset", type=Path)
    parser.add_argument("--experiment-spec", type=Path)


def execute(args):
    if args.command in {"annotations-build", "annotations-validate"}:
        from .datasets.annotations import build_annotations, load_annotations
        from .datasets.binding import build_dataset_binding
        from .datasets.loader import load_dataset

        if args.command == "annotations-build":
            result = build_annotations(
                args.dataset,
                args.output,
                version=args.version,
                registry_path=args.annotation_registry,
            )
        else:
            result = load_annotations(
                args.annotations,
                registry_path=args.annotation_registry,
                dataset_binding=build_dataset_binding(args.dataset),
                case_ids={t["id"] for t in load_dataset(args.dataset)["tasks"]},
            )
        return {
            "records": len(result.records),
            "missing_case_ids": result.missing_case_ids,
            "content_sha256": result.content_sha256,
            "review_status": result.manifest["review_status"],
            "registration_status": result.registration_status,
        }

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
            annotation_registry_path=args.annotation_registry,
            output=args.output,
            policy=policy,
            source_artifacts=tuple(args.source_artifact),
            judge_dir=args.judge_source,
            compare_with=args.compare_with,
            comparison_dataset_path=args.comparison_dataset,
            experiment_spec=read_json(args.experiment_spec)[0]
            if args.experiment_spec
            else None,
        ).items()
    }
