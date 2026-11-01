"""Pinned, isolated integration with official τ-bench text simulations.

This suite preserves official task/reward semantics and is reported separately
from the file-tools DeepEval benchmark. Imports never require τ dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

TAU_REPOSITORY = "https://github.com/sierra-research/tau2-bench.git"
TAU_RELEASE = "v1.0.1"
TAU_COMMIT = "fc0055dc4e0a316c3f83133267fbd6faaa770992"
ADAPTER_VERSION = "tau-nanobot-rendezvous-v1"
DEPENDENCY_PINS = (
    "pydantic==2.13.4",
    "pydantic-settings==2.15.0",
    "openai==3.3.1",
    "filelock==3.32.3",
    "anthropic==0.125.0",
    "litellm==1.82.6",
)


def interpreter_path(value: str) -> Path:
    """Keep the venv executable symlink; resolving it silently escapes its venv."""
    return Path(value).expanduser().absolute()


def verify_imported_tau(module_file: str, source_root: str) -> str:
    actual = Path(module_file).resolve(strict=True)
    expected = (Path(source_root) / "src/tau2/__init__.py").resolve(strict=True)
    if actual != expected:
        raise ValueError(f"Imported τ code is outside the pinned source: {actual}")
    return str(actual)


def redact_secrets(value: Any, config: dict[str, Any]) -> Any:
    keys = [
        ("agent_api_key_env", "DEEPSEEK_API_KEY"),
        ("user_api_key_env", "DEEPSEEK_API_KEY"),
    ]
    if config.get("allow_official_judge"):
        keys.append(("official_judge_api_key_env", "OPENAI_API_KEY"))
    secrets = {
        os.environ.get(config.get(key, default), "") for key, default in keys
    } - {""}

    def clean(item: Any) -> Any:
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "[REDACTED]")
            return item
        if isinstance(item, list):
            return [clean(child) for child in item]
        if isinstance(item, dict):
            return {clean(key): clean(child) for key, child in item.items()}
        return item

    return clean(value)


def worker_environment(config: dict[str, Any]) -> dict[str, str]:
    """Pass only selected credentials; exclude ambient providers/startup hooks."""
    allowed = {
        "PATH",
        "LANG",
        "LC_ALL",
        "SYSTEMROOT",
        "TMPDIR",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    for key in ("agent_api_key_env", "user_api_key_env"):
        name = config.get(key, "DEEPSEEK_API_KEY")
        env[name] = os.environ.get(name, "")
    if config.get("allow_official_judge"):
        name = config.get("official_judge_api_key_env", "OPENAI_API_KEY")
        env[name] = os.environ.get(name, "")
        env["OPENAI_API_KEY"] = env[name]
    env.update(
        PYTHONDONTWRITEBYTECODE="1",
        PYTHON_DOTENV_DISABLED="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        PYTHONPATH=os.pathsep.join(
            [str(Path(config["source_root"]) / "src"), config["nanobot_root"]]
        ),
        TAU2_DATA_DIR=str(Path(config["source_root"]) / "data"),
        LITELLM_LOCAL_MODEL_COST_MAP="True",
    )
    return env


def validate_config(config: dict[str, Any]) -> None:
    """Reject moving source refs and accidental full-suite/model expansion."""
    if config.get("source_commit") != TAU_COMMIT:
        raise ValueError(
            f"source_commit must be the supported pinned commit {TAU_COMMIT}"
        )
    if config.get("domain") != "retail":
        raise ValueError("This adapter currently validates only English retail text")
    ids = config.get("task_ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        raise ValueError("Explicit nonempty task_ids are required")
    if len(set(ids)) != len(ids):
        raise ValueError("task_ids must be unique")
    if not 1 <= config.get("num_trials", 1) <= 10:
        raise ValueError("num_trials must be between 1 and 10")
    for key in ("api_key", "agent_api_key", "user_api_key"):
        if key in config:
            raise ValueError("Credentials must be supplied through environment names")


def verify_source(root: Path, commit: str = TAU_COMMIT) -> dict[str, str]:
    """Verify the resolved source commit and absence of tracked modifications."""
    root = Path(root).expanduser().resolve(strict=True)
    actual = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != commit:
        raise ValueError(f"τ source commit mismatch: {actual} != {commit}")
    changed = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
        text=True,
    )
    if changed:
        raise ValueError("τ source has modified tracked files")
    return {"repository": TAU_REPOSITORY, "commit": actual, "root": str(root)}


def prepare_tau(config: dict[str, Any], *, base_python: str = sys.executable) -> dict:
    """Explicit setup only: fetch the pinned source and install a separate venv."""
    import tomllib

    validate_config(config)
    root = Path(config["source_root"]).expanduser().resolve()
    if not root.exists():
        root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                TAU_RELEASE,
                TAU_REPOSITORY,
                str(root),
            ],
            check=True,
        )
    identity = verify_source(root)
    python = interpreter_path(config["python"])
    if not python.exists():
        subprocess.run(
            [base_python, "-m", "venv", str(python.parent.parent)], check=True
        )
    dependencies = tomllib.loads(
        (Path(config["nanobot_root"]) / "pyproject.toml").read_text()
    )["project"]["dependencies"]
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "-e",
            str(root),
            *dependencies,
            *DEPENDENCY_PINS,
        ],
        check=True,
    )
    return identity


def run_tau(config: dict[str, Any], output: Path, *, dry_run: bool = False) -> dict:
    """Execute the real nanobot/official τ worker, or validate it without calls."""
    validate_config(config)
    identity = verify_source(Path(config["source_root"]))
    normalized = dict(config)
    for key in ("source_root", "nanobot_root"):
        normalized[key] = str(Path(config[key]).expanduser().resolve(strict=True))
    normalized["python"] = str(interpreter_path(config["python"]))
    if not Path(normalized["python"]).exists():
        raise FileNotFoundError(normalized["python"])
    output = Path(output).expanduser().resolve()
    if not dry_run and output.exists() and any(output.iterdir()):
        raise ValueError("τ output directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    payload = {"config": normalized, "output": str(output), "dry_run": dry_run}
    env = worker_environment(normalized)
    completed = subprocess.run(
        [normalized["python"], str(Path(__file__).with_name("tau_worker.py"))],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        cwd=output,
        timeout=float(config.get("timeout_seconds", 300))
        * len(config["task_ids"])
        * config.get("num_trials", 1)
        + 60,
    )
    stderr = redact_secrets(completed.stderr, config)
    (output / "worker.log").write_text(stderr, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(f"τ worker failed; see {output / 'worker.log'}")
    result = redact_secrets(
        json.loads(completed.stdout.strip().splitlines()[-1]), config
    )
    result["source_identity"] = identity
    result["adapter_version"] = ADAPTER_VERSION
    result["config_sha256"] = hashlib.sha256(
        json.dumps(normalized, sort_keys=True).encode()
    ).hexdigest()
    (output / ("validation.json" if dry_run else "summary.json")).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "validate", "run"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/tau-pilot"))
    parser.add_argument("--base-python", default=sys.executable)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    result = (
        prepare_tau(config, base_python=args.base_python)
        if args.operation == "prepare"
        else run_tau(config, args.output, dry_run=args.operation == "validate")
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
