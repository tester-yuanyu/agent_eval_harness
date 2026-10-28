"""Installation choices must select a compatible dependency constraint set."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("suite_setup", ROOT / "scripts/setup.py")
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def test_optional_evaluator_uses_its_own_resolved_constraints(tmp_path):
    python = tmp_path / "python"
    python.touch()
    constraints = tmp_path / "environments"
    constraints.mkdir()
    (constraints / "evaluator.txt").touch()
    (constraints / "evaluator-optional.txt").touch()
    with (
        patch.object(setup, "ROOT", tmp_path),
        patch.object(setup, "environment_python", return_value=python),
        patch.object(setup.subprocess, "run") as run,
    ):
        setup.install("evaluator", optional_metrics=True, use_locks=True)
    command = run.call_args_list[0].args[0]
    assert command[command.index("-c") + 1] == str(
        constraints / "evaluator-optional.txt"
    )
    assert "packages/evaluator[dev,conversation]" in command


def test_default_evaluator_keeps_default_constraints(tmp_path):
    python = tmp_path / "python"
    python.touch()
    constraints = tmp_path / "environments"
    constraints.mkdir()
    (constraints / "evaluator.txt").touch()
    with (
        patch.object(setup, "ROOT", tmp_path),
        patch.object(setup, "environment_python", return_value=python),
        patch.object(setup.subprocess, "run") as run,
    ):
        setup.install("evaluator", optional_metrics=False, use_locks=True)
    command = run.call_args_list[0].args[0]
    assert command[command.index("-c") + 1] == str(constraints / "evaluator.txt")
    assert "packages/evaluator[dev]" in command
