#!/usr/bin/env python3
"""Provision the official Langfuse Compose stack locally; never export evaluations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path

import yaml

TEMPLATE = Path(__file__).resolve().parent / "langfuse/docker-compose.upstream.yml"
SOURCE = "https://raw.githubusercontent.com/langfuse/langfuse/main/docker-compose.yml"


def _write_private(path: Path, value: dict) -> None:
    with open(
        path, "w", opener=lambda name, flags: os.open(name, flags, 0o600)
    ) as file:
        json.dump(value, file, indent=2)
        file.write("\n")
    path.chmod(0o600)


def initialize(state: Path, config: Path, port: int, media_port: int) -> None:
    """Create once and reuse secrets; reject conflicting configuration."""
    state, config = state.resolve(), config.resolve()
    if not (1024 <= port <= 65535 and 1024 <= media_port <= 65535):
        raise ValueError("Ports must be between 1024 and 65535")
    if port == media_port:
        raise ValueError("Web and media ports must differ")
    manifest_path = state / "deployment.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        expected = {"port": port, "media_port": media_port, "config": str(config)}
        if any(existing.get(key) != value for key, value in expected.items()):
            raise ValueError(
                "Conflicts with existing deployment; preserve its credentials"
            )
        if not config.exists() or not (state / "compose.json").exists():
            raise ValueError(
                "Incomplete existing deployment; restore its configuration backup"
            )
        return
    if config.exists() or (state / "compose.json").exists():
        raise ValueError("Refusing to overwrite existing local configuration")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    config.parent.mkdir(parents=True, exist_ok=True)
    postgres, clickhouse, redis, minio = (secrets.token_hex(24) for _ in range(4))
    public_key, secret_key = (
        "pk-lf-" + secrets.token_hex(16),
        "sk-lf-" + secrets.token_hex(24),
    )
    admin_password = secrets.token_urlsafe(24)
    base_url = f"http://127.0.0.1:{port}"
    values = {
        "NEXTAUTH_URL": base_url,
        "DATABASE_URL": f"postgresql://postgres:{postgres}@postgres:5432/postgres",
        "POSTGRES_PASSWORD": postgres,
        "CLICKHOUSE_PASSWORD": clickhouse,
        "REDIS_AUTH": redis,
        "MINIO_ROOT_PASSWORD": minio,
        "SALT": secrets.token_hex(32),
        "ENCRYPTION_KEY": secrets.token_hex(32),
        "NEXTAUTH_SECRET": secrets.token_hex(32),
        "TELEMETRY_ENABLED": "false",
        "LANGFUSE_IN_APP_AGENT_ENABLED": "false",
        "LANGFUSE_INIT_ORG_ID": "agent-evaluator-local",
        "LANGFUSE_INIT_ORG_NAME": "Agent Evaluator Local",
        "LANGFUSE_INIT_PROJECT_ID": "agent-evaluator",
        "LANGFUSE_INIT_PROJECT_NAME": "Agent Evaluator",
        "LANGFUSE_INIT_PROJECT_PUBLIC_KEY": public_key,
        "LANGFUSE_INIT_PROJECT_SECRET_KEY": secret_key,
        "LANGFUSE_INIT_USER_EMAIL": "evaluator@localhost.test",
        "LANGFUSE_INIT_USER_NAME": "Local Evaluator",
        "LANGFUSE_INIT_USER_PASSWORD": admin_password,
        "LANGFUSE_DISABLE_SIGNUP_ONBOARDING": "true",
    }
    for kind in ("EVENT", "MEDIA", "BATCH_EXPORT"):
        values[
            f"LANGFUSE_S3_{kind}_UPLOAD_SECRET_ACCESS_KEY"
            if kind != "BATCH_EXPORT"
            else "LANGFUSE_S3_BATCH_EXPORT_SECRET_ACCESS_KEY"
        ] = minio

    def expand(value):
        if isinstance(value, dict):
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, str):
            return re.sub(
                r"\$\{([A-Z0-9_]+):-([^}]*)\}",
                lambda match: values.get(match[1], match[2]),
                value,
            )
        return value

    # Expand controlled settings and defaults; never inherit shell/cloud keys.
    compose = expand(yaml.safe_load(TEMPLATE.read_text()))
    compose["name"] = "agent-evaluator-langfuse"
    for service in compose["services"].values():
        service.pop("ports", None)
        service["restart"] = "unless-stopped"
    web = compose["services"]["langfuse-web"]
    web["ports"] = [f"127.0.0.1:{port}:3000"]
    web["environment"]["LANGFUSE_S3_MEDIA_UPLOAD_ENDPOINT"] = (
        f"http://127.0.0.1:{media_port}"
    )
    web["environment"]["AUTH_DISABLE_SIGNUP"] = "true"
    compose["services"]["minio"]["ports"] = [f"127.0.0.1:{media_port}:9000"]
    for name in ("langfuse-web", "langfuse-worker"):
        compose["services"][name]["environment"][
            "LANGFUSE_S3_BATCH_EXPORT_EXTERNAL_ENDPOINT"
        ] = f"http://127.0.0.1:{media_port}"
    _write_private(state / "compose.json", compose)
    _write_private(
        state / "login.json",
        {
            "url": base_url,
            "email": values["LANGFUSE_INIT_USER_EMAIL"],
            "password": admin_password,
        },
    )
    _write_private(
        config,
        {
            "enabled": True,
            "base_url": base_url,
            "project_id": values["LANGFUSE_INIT_PROJECT_ID"],
            "public_key": public_key,
            "secret_key": secret_key,
            "include_content": False,
            "state_dir": str(state / "delivery"),
        },
    )
    _write_private(
        manifest_path,
        {
            "port": port,
            "media_port": media_port,
            "config": str(config),
            "upstream_url": SOURCE,
            "upstream_sha256": hashlib.sha256(TEMPLATE.read_bytes()).hexdigest(),
            "images": {
                name: service["image"] for name, service in compose["services"].items()
            },
            "image_digests_locked": False,
        },
    )


def docker_binary() -> str:
    binary = shutil.which("docker")
    if binary:
        return binary
    bundled = Path("/Applications/Docker.app/Contents/Resources/bin/docker")
    if bundled.exists():
        return str(bundled)
    raise RuntimeError("Install and start Docker Desktop first")


def reuse(
    output: Path,
    *,
    base_url: str,
    project_id: str,
    public_key_env: str = "LOCAL_LANGFUSE_PUBLIC_KEY",
    secret_key_env: str = "LOCAL_LANGFUSE_SECRET_KEY",
) -> None:
    """Create a profile for an existing local instance without starting Docker."""
    from eval_framework.benchmark.langfuse_delivery import load_profile

    output = Path(output)
    if output.exists():
        raise ValueError("Refusing to overwrite existing profile")
    values = {
        "profile": "local",
        "base_url": base_url,
        "project_id": project_id,
        "public_key_env": public_key_env,
        "secret_key_env": secret_key_env,
        "intervals": {"dataset": 0.25, "tracing": 0.2, "read": 0.2},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x") as file:
            json.dump(values, file, indent=2)
            file.write("\n")
        load_profile(output)
    except Exception:
        output.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("init", "up", "status", "stop", "lock", "reuse")
    )
    parser.add_argument(
        "--state-dir", type=Path, default=Path("artifacts/local_langfuse")
    )
    parser.add_argument("--config", type=Path, default=Path(".env.langfuse.local.json"))
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--media-port", type=int, default=9090)
    parser.add_argument("--base-url")
    parser.add_argument("--project-id")
    parser.add_argument("--profile-output", type=Path)
    parser.add_argument("--public-key-env", default="LOCAL_LANGFUSE_PUBLIC_KEY")
    parser.add_argument("--secret-key-env", default="LOCAL_LANGFUSE_SECRET_KEY")
    args = parser.parse_args()
    if args.action == "reuse":
        if not args.base_url or not args.project_id or not args.profile_output:
            parser.error("reuse requires --base-url, --project-id and --profile-output")
        reuse(
            args.profile_output,
            base_url=args.base_url,
            project_id=args.project_id,
            public_key_env=args.public_key_env,
            secret_key_env=args.secret_key_env,
        )
        print(
            json.dumps({"profile": str(args.profile_output), "service_started": False})
        )
        return 0
    state = args.state_dir.resolve()
    if args.action == "init":
        initialize(state, args.config, args.port, args.media_port)
        print(
            json.dumps(
                {
                    "state_dir": str(state),
                    "config": str(args.config.resolve()),
                    "url": f"http://127.0.0.1:{args.port}",
                }
            )
        )
        return 0
    compose_path = state / "compose.json"
    if not compose_path.exists():
        parser.error("Run init first")
    docker = docker_binary()
    child_env = dict(os.environ)
    child_env["PATH"] = (
        str(Path(docker).parent) + os.pathsep + child_env.get("PATH", "")
    )
    command = [docker, "compose", "-f", str(compose_path)]
    if args.action == "lock":
        compose = json.loads(compose_path.read_text())
        for service in compose["services"].values():
            digests = json.loads(
                subprocess.check_output(
                    [
                        docker,
                        "image",
                        "inspect",
                        service["image"],
                        "--format",
                        "{{json .RepoDigests}}",
                    ],
                    text=True,
                    env=child_env,
                )
            )
            if not digests:
                raise RuntimeError("Pull all images before locking")
            service["image"] = digests[0]
        _write_private(compose_path, compose)
        manifest_path = state / "deployment.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["images"] = {
            name: service["image"] for name, service in compose["services"].items()
        }
        manifest["image_digests_locked"] = True
        _write_private(manifest_path, manifest)
        print("Image digests pinned; persistent data and credentials unchanged")
        return 0
    command.extend(
        {"up": ["up", "-d"], "status": ["ps"], "stop": ["stop"]}[args.action]
    )
    return subprocess.call(command, env=child_env)


if __name__ == "__main__":
    raise SystemExit(main())
