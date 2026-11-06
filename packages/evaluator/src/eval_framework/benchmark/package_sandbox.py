"""Build isolated Provider workers from explicit local package source inputs."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from .inspect_docker import bind_docker_environment, source_digest


def package_inputs(packages: dict[str, Path], bundle: Path) -> dict[str, bytes]:
    files = {}
    projects = [
        tomllib.loads((root / "pyproject.toml").read_text())["project"]
        for root in packages.values()
    ]
    local = {p["name"].lower().replace("_", "-") for p in projects}
    dependencies = sorted(
        {
            d
            for p in projects
            for d in p.get("dependencies", [])
            if re.split(r"[<>=!~\[; ]", d)[0].lower().replace("_", "-") not in local
        }
    )
    files["requirements.txt"] = ("\n".join(dependencies) + "\n").encode()
    for name, root in packages.items():
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            if path.is_symlink() or not path.is_file():
                continue
            if rel.as_posix() not in {"pyproject.toml", "README.md"} and not (
                rel.parts[0] == "src"
                and path.suffix in {".py", ".md", ".json", ".yaml", ".yml"}
                and not any(
                    p.startswith(".") or p in {"__pycache__", "tests"}
                    for p in rel.parts
                )
            ):
                continue
            # The worker cannot see benchmark datasets, generators or trusted scorers.
            if "benchmark" in rel.parts and path.name not in {
                "__init__.py",
                "mini_worker.py",
            }:
                continue
            files[f"packages/{name}/{rel.as_posix()}"] = path.read_bytes()
    for path in sorted(bundle.rglob("*")):
        if path.is_file() and not path.is_symlink():
            files["reference/" + path.relative_to(bundle).as_posix()] = (
                path.read_bytes()
            )
    return files


def prepare_package_sandbox(
    packages: dict[str, Path],
    bundle: Path,
    output: Path,
    *,
    base_image: str = "python:3.11-slim",
) -> tuple[str, str]:
    files = package_inputs(packages, bundle)
    recipe = (
        f"FROM {base_image}\nWORKDIR /opt/runtime\n"
        "COPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\n"
        "COPY packages packages\nRUN pip install --no-deps "
        + " ".join("./packages/" + n for n in packages)
        + "\n"
        "COPY reference /opt/reference\nWORKDIR /sample\n"
    )
    files["Dockerfile"] = recipe.encode()
    build_hash = source_digest(files)
    context = output / build_hash
    context.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = context / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    compose = context / "compose.json"
    compose.write_text(
        json.dumps(
            {
                "services": {
                    "default": {
                        "image": f"agent-eval-provider:{build_hash}",
                        "build": {"context": str(context)},
                        "init": True,
                        "command": ["sleep", "infinity"],
                        "working_dir": "/sample",
                    }
                }
            }
        )
    )
    bind_docker_environment(str(compose))
    return ("docker", str(compose))
