"""根入口只编排独立解释器，不导入运行时。"""

from pathlib import Path
from unittest.mock import patch


def test_readiness_cli_routes_without_runtime_imports(tmp_path):
    from agent_eval_suite import readiness
    from agent_eval_suite.cli import main

    with (
        patch("agent_eval_suite.cli.interpreter", return_value=Path("isolated-python")),
        patch.object(readiness, "execute", return_value=0) as execute,
    ):
        assert (
            main(
                [
                    "readiness",
                    "run",
                    "--dataset",
                    "input.json",
                    "--workspace",
                    str(tmp_path / "out"),
                ]
            )
            == 0
        )
    assert execute.call_args.args[0].action == "run"


def test_readiness_check_requires_current_interpreter_identity(tmp_path):
    from argparse import Namespace

    from agent_eval_suite.readiness import execute

    work = tmp_path / "work"
    work.mkdir()
    dataset = tmp_path / "dataset.json"
    dataset.write_text("{}")
    (work / "evidence.json").write_text("{}")
    args = Namespace(
        action="check", workspace=work, dataset=dataset, review=None, output=None
    )
    calls = []

    def invoke(python, module, arguments):
        calls.append((module, arguments))
        if module == "eval_framework.benchmark.readiness":
            Path(arguments[arguments.index("--output") + 1]).write_text("{}")
        return 0

    assert execute(args, Path("builder-python"), Path("evaluator-python"), invoke) == 0
    assert calls[0][0] == "eval_framework.benchmark.readiness"
    assert "--identity" in calls[0][1]
    assert calls[1][1][0] == "assess-readiness"


def test_full_readiness_routes_source_and_current_identity(tmp_path):
    from argparse import Namespace

    from agent_eval_suite.readiness import execute

    args = Namespace(
        action="run",
        workspace=tmp_path / "work",
        delivery=tmp_path / "delivery",
        mini_agent_root=tmp_path / "mini",
        review=None,
        output=None,
    )
    calls = []

    def invoke(python, module, arguments):
        calls.append((module, arguments))
        return 0

    assert execute(args, Path("builder"), Path("evaluator"), invoke) == 0
    assert calls[0][1][0] == "prepare-full-readiness"
    assert calls[0][1][1] == "--delivery"
    assert calls[1][0] == "eval_framework.benchmark.full_readiness"
    assert "--mini-agent-root" in calls[1][1]
    assert "--identity" in calls[2][1]
    assert calls[3][1][0] == "assess-full-readiness"
