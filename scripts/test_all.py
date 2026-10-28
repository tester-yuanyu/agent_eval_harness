"""Run each package's offline checks using its own environment and configuration."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "contracts": ("builder", "packages/contracts"),
    "builder": ("builder", "packages/dataset-builder"),
    "agent": ("evaluator", "examples/mini_agent"),
    "sdk": ("evaluator", "packages/agent-trace-sdk"),
    "evaluator": ("evaluator", "packages/evaluator"),
    "integration": ("evaluator", "."),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=GROUPS)
    parser.add_argument("--optional-metrics", action="store_true")
    args = parser.parse_args()
    output = ROOT / "artifacts" / "verification"
    output.mkdir(parents=True, exist_ok=True)
    # The offline test harness must not inherit credentials or live-smoke opt-ins.
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(
            word in k.upper()
            for word in ("API_KEY", "SECRET", "TOKEN", "LANGFUSE", "SMOKE")
        )
    }
    env.pop("PYTHONPATH", None)
    env.update(
        PYTHONDONTWRITEBYTECODE="1",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        DEEPEVAL_TELEMETRY_OPT_OUT="YES",
    )
    failed = []
    for name in [args.only] if args.only else GROUPS:
        environment, relative = GROUPS[name]
        if args.optional_metrics:
            environment += "-optional"
        python = (
            ROOT
            / ".venvs"
            / environment
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        if not python.is_file():
            print(f"Missing {environment} environment; run make setup", file=sys.stderr)
            return 2
        project = ROOT / relative
        tests = "tests/integration" if name == "integration" else "tests"
        if not (project / tests).is_dir():
            print(f"{name}: no standalone tests; validated by consumers")
            continue
        log = output / f"{name}.log"
        with log.open("w") as stream:
            result = subprocess.run(
                [
                    str(python),
                    "-m",
                    "pytest",
                    "-c",
                    "pyproject.toml",
                    tests,
                    "-q",
                    "-p",
                    "no:cacheprovider",
                ],
                cwd=project,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        tail = log.read_text(errors="replace").splitlines()[-8:]
        print(f"{name}: exit={result.returncode}; {log}", flush=True)
        print("\n".join(tail), flush=True)
        if result.returncode:
            failed.append(name)
    if failed:
        print("Failed groups: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
