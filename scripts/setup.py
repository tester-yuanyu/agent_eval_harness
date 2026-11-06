"""Install declared local packages in independently resolved environments."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def environment_python(name: str) -> Path:
    bindir = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return ROOT / ".venvs" / name / bindir / executable


def install(
    name: str, optional_metrics: bool, use_locks: bool, with_langfuse: bool = False
) -> None:
    environment_name = (
        f"{name}-optional" if optional_metrics and name != "core" else name
    )
    python = environment_python(environment_name)
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(python.parent.parent)
    packages = ["packages/contracts", "."]
    if name == "builder":
        extra = "dev,deepeval" if optional_metrics else "dev"
        packages.append(f"packages/dataset-builder[{extra}]")
    elif name == "evaluator":
        extra = "dev,langfuse" if with_langfuse else "dev"
        packages.extend(
            [
                "packages/agent-trace-sdk",
                "examples/mini_agent[dev]",
                f"packages/evaluator[{extra}]",
            ]
        )
    elif name == "core":
        extra = "dev,langfuse" if with_langfuse else "dev"
        packages.extend(["packages/agent-trace-sdk", f"packages/evaluator[{extra}]"])
    command = [str(python), "-m", "pip", "install", "--disable-pip-version-check"]
    lock = ROOT / "environments" / f"{environment_name}.txt"
    if use_locks and lock.is_file():
        command.extend(["-c", str(lock)])
    for package in packages:
        command.extend(["-e", package])
    subprocess.run(command, cwd=ROOT, check=True)
    subprocess.run([str(python), "-m", "pip", "check"], cwd=ROOT, check=True)
    print(f"{environment_name}: {python}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["builder", "evaluator", "core"])
    parser.add_argument("--optional-metrics", action="store_true")
    parser.add_argument(
        "--with-langfuse", action="store_true",
        help="Explicitly install the optional Langfuse display/export integration",
    )
    parser.add_argument(
        "--unlocked", action="store_true", help="Resolve without saved constraints"
    )
    args = parser.parse_args()
    if sys.version_info < (3, 11):  # noqa: UP036 - bootstrap may run before installation
        parser.error("Python 3.11 or newer is required")
    for name in [args.only] if args.only else ["builder", "evaluator"]:
        install(name, args.optional_metrics, not args.unlocked, args.with_langfuse)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
