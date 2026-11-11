"""P0 编排仅用 subprocess；每次检查/冻结都重新获取执行环境身份。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory


def execute(args, builder: Path, evaluator: Path, invoke) -> int:
    workspace = args.workspace.resolve()
    full = getattr(args, "delivery", None) is not None
    dataset = (args.delivery if full else args.dataset).resolve()
    source_flag = "--delivery" if full else "--dataset"
    suffix = "full-readiness" if full else "readiness"
    worker = "eval_framework.benchmark." + ("full_readiness" if full else "readiness")
    worker_args = (
        ["--mini-agent-root", str(args.mini_agent_root.resolve())] if full else []
    )
    evidence = workspace / "evidence.json"
    if args.action == "run":
        workspace.mkdir(parents=True, exist_ok=False)
        request = workspace / "dataset.json"
        code = invoke(
            builder,
            "dataset_builder.cli",
            [
                "prepare-" + suffix,
                source_flag,
                str(dataset),
                "--output",
                str(request),
            ],
        )
        if code:
            return code
        code = invoke(
            evaluator,
            worker,
            [
                "--dataset",
                str(request),
                "--output",
                str(evidence),
                "--log-dir",
                str(workspace / "logs"),
            ]
            + worker_args,
        )
        if code:
            return code
    if not workspace.is_dir():
        raise ValueError("readiness workspace does not exist")
    with TemporaryDirectory(prefix=".current-runner-", dir=workspace) as directory:
        identity = Path(directory) / "identity.json"
        code = invoke(
            evaluator,
            worker,
            [
                "--identity",
                "--output",
                str(identity),
            ]
            + worker_args,
        )
        if code:
            return code
        command = ("freeze-" if args.action == "freeze" else "assess-") + suffix
        forwarded = [
            command,
            source_flag,
            str(dataset),
            "--evidence",
            str(evidence),
            "--identity",
            str(identity),
        ]
        if args.review:
            forwarded += ["--review", str(args.review.resolve())]
        if args.action == "freeze":
            forwarded += ["--output", str(args.output.resolve())]
        else:
            forwarded += ["--report", str(workspace / "report.json")]
        return invoke(builder, "dataset_builder.cli", forwarded)
