"""Content-addressed Docker inputs for Inspect's native sandbox provider."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path


class SandboxEnvironmentChanged(RuntimeError):
    """An existing run cannot mix different immutable Docker environments."""


def docker_image_id(image: str) -> str:
    result = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode or not result.stdout.strip():
        raise SandboxEnvironmentChanged(
            "bound Docker image is unavailable; restore it or use a new run directory"
        )
    return result.stdout.strip()


def bind_docker_environment(
    compose: str, environment: dict | None = None
) -> dict | None:
    """Bind after Inspect builds; check before resume and every worker invocation."""
    path = Path(compose)
    binding = path.parents[2] / "sandbox-environment.json"
    if environment is None and not binding.exists():
        if list((binding.parent / "inspect").glob("*.eval")):
            raise SandboxEnvironmentChanged(
                "saved Inspect samples have no Docker environment binding; "
                "use a new run directory"
            )
        return None
    image = json.loads(path.read_text())["services"]["default"]["image"]
    identity = {"image": image, "image_id": docker_image_id(image)}
    if environment is not None:
        identity["runtime_environment_sha256"] = hashlib.sha256(
            json.dumps(environment, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    if binding.exists():
        bound = json.loads(binding.read_text())
        if any(bound.get(key) != value for key, value in identity.items()):
            raise SandboxEnvironmentChanged(
                "Docker image or dependencies changed; use a new run directory"
            )
        return bound
    # The run lock excludes other processes; this synchronous section cannot
    # interleave with other sample coroutines in the same Inspect event loop.
    with binding.open("x") as stream:
        json.dump(identity, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return identity


def source_files(root: Path) -> dict[str, bytes]:
    paths = subprocess.check_output(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ]
    ).split(b"\0")
    result = {}
    for raw in sorted(set(paths)):
        if not raw:
            continue
        name = os.fsdecode(raw)
        path = root / name
        if any(part.startswith(".") for part in Path(name).parts):
            continue
        if not (name.startswith("nanobot/") or name in {"pyproject.toml", "uv.lock"}):
            continue
        if (
            any(parent.is_symlink() for parent in (path, *path.parents))
            or not path.is_file()
            or path.suffix
            not in {".py", ".md", ".json", ".toml", ".lock", ".yaml", ".yml", ".j2"}
        ):
            continue
        if path.name in {"credentials.json", "secrets.json", "auth.json"}:
            continue
        result[name] = path.read_bytes()
    return result


def source_digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(os.fsencode(name) + b"\0" + content + b"\0")
    return digest.hexdigest()


def prepare_docker_sandbox(config: dict, output: Path) -> tuple[str, str]:
    """Inspect builds/starts/stops this compose project; no host home mounts."""
    from .nanobot_runtime import TOKENIZER_SHA256, TOKENIZER_URL

    root = Path(config["nanobot_root"]).expanduser().resolve(strict=True)
    files = source_files(root)
    source_hash = source_digest(files)
    harness = Path(__file__).parent
    workers = {
        name: (harness / name).read_bytes()
        for name in [
            "nanobot_runtime.py",
            "nanobot_worker.py",
            "module_worker.py",
            "decision_worker.py",
        ]
    }
    worker_hash = source_digest(workers)
    recipe_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    build_hash = hashlib.sha256(
        (
            source_hash
            + worker_hash
            + recipe_hash
            + config.get("docker_base_image", "python:3.11-slim")
        ).encode()
    ).hexdigest()
    context = output / build_hash
    context.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = context / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    for name, content in workers.items():
        target = context / "harness" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    cache_dir = context / "tokenizer"
    cache_dir.mkdir(exist_ok=True)
    if config.get("tokenizer_mode", "cl100k_base") != "byte_fallback":
        import tempfile

        cache_name = hashlib.sha1(TOKENIZER_URL.encode()).hexdigest()
        cache = (
            Path(
                config.get("tokenizer_cache_dir")
                or Path(tempfile.gettempdir()) / "data-gym-cache"
            )
            / cache_name
        )
        if (
            not cache.is_file()
            or hashlib.sha256(cache.read_bytes()).hexdigest() != TOKENIZER_SHA256
        ):
            raise ValueError(
                "verified tokenizer cache missing; "
                "run prepare_tokenizer or select byte_fallback"
            )
        (cache_dir / cache_name).write_bytes(cache.read_bytes())
    (context / "Dockerfile").write_text(
        f"FROM {config.get('docker_base_image', 'python:3.11-slim')}\n"
        "COPY source/pyproject.toml /opt/nanobot/pyproject.toml\n"
        'RUN python -c "import tomllib; '
        "d=tomllib.load(open('/opt/nanobot/pyproject.toml','rb')); "
        "open('/tmp/requirements.txt','w').write('\\n'.join("
        "d['project'].get('dependencies',[])))\" "
        "&& pip install --no-cache-dir -r /tmp/requirements.txt\n"
        "COPY source/ /opt/nanobot/\nCOPY harness/ /opt/harness/\n"
        "COPY tokenizer/ /opt/tokenizer/\n"
        "ENV PYTHONPATH=/opt/nanobot PYTHONUNBUFFERED=1\n"
        "RUN mkdir -p /sample/workspace /sample/runtime\nWORKDIR /sample\n"
    )
    compose = {
        "services": {
            "default": {
                "image": f"agent-eval-nanobot:{build_hash[:24]}",
                "build": {"context": "."},
                "command": ["sleep", "infinity"],
                "working_dir": "/sample",
                "init": True,
            }
        }
    }
    path = context / "compose.json"
    path.write_text(json.dumps(compose, indent=2) + "\n")
    (context / "source-manifest.json").write_text(
        json.dumps(
            {
                "source_sha256": source_hash,
                "worker_sha256": worker_hash,
                "files": {
                    name: hashlib.sha256(content).hexdigest()
                    for name, content in files.items()
                },
            },
            indent=2,
        )
        + "\n"
    )
    bind_docker_environment(str(path))
    return "docker", str(path)
