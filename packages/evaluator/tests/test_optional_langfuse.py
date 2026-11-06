"""Core imports, local execution and reports must not require the display SDK."""

import os
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BLOCK = """
import importlib.abc
import sys
class MissingLangfuse(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "langfuse" or fullname.startswith("langfuse."):
            raise ModuleNotFoundError("optional SDK unavailable", name=fullname)
sys.meta_path.insert(0, MissingLangfuse())
"""


def run_without_sdk(script, tmp_path):
    env = {
        key: value
        for key, value in os.environ.items()
        if not any(
            word in key.upper()
            for word in ("API_KEY", "SECRET", "TOKEN", "LANGFUSE", "SMOKE")
        )
    }
    env.update(DEEPEVAL_TELEMETRY_OPT_OUT="YES", OTEL_SDK_DISABLED="true")
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            BLOCK + textwrap.dedent(script),
            str(ROOT),
            str(tmp_path),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=90,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_no_langfuse_core_cli_demo_and_report(tmp_path):
    run_without_sdk(
        """
        from pathlib import Path
        import eval_framework
        import eval_framework.cli as legacy
        from eval_framework.benchmark.cli import main
        root, output = map(Path, sys.argv[1:])
        assert legacy._finalize_local_delivery(output, None) == {"status": "DISABLED"}
        assert main(["demo", "--dataset", str(root / "data/benchmarks/file-tools-v1"),
                     "--limit", "1", "--output", str(output / "run")]) == 0
        assert main(["report", "--run", str(output / "run")]) == 0
        assert (output / "run/inspect-view/index.html").is_file()
        assert "langfuse" not in sys.modules
    """,
        tmp_path,
    )


def test_explicit_export_without_sdk_has_actionable_error(tmp_path):
    run_without_sdk(
        """
        from contextlib import redirect_stdout
        from io import StringIO
        from eval_framework.benchmark.cli import main
        from eval_framework.cli import main as legacy
        for command in (
            lambda: main(["export-langfuse", "--run", "missing",
                          "--dataset", "missing"]),
            lambda: legacy(["export-langfuse", "--run-dir", "missing"]),
            lambda: legacy(["import-reviews", "--run-dir", "missing"]),
        ):
            text = StringIO()
            with redirect_stdout(text):
                assert command() == 2
            assert "agent-evaluator[langfuse]" in text.getvalue()
    """,
        tmp_path,
    )


def test_packaging_keeps_scoring_required_and_display_optional():
    project = tomllib.loads((ROOT / "packages/evaluator/pyproject.toml").read_text())[
        "project"
    ]
    assert not any(dep.startswith("langfuse") for dep in project["dependencies"])
    assert "deepeval==4.2.9" in project["dependencies"]
    assert project["optional-dependencies"]["langfuse"] == ["langfuse==5.0.2"]
    assert "conversation" not in project["optional-dependencies"]
