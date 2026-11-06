"""Inspect-owned asynchronous environment for existing isolated workers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .file_tools import validate_fixtures


class InspectFileToolsEnvironment:
    """Adapt the active Inspect sample without taking over sandbox cleanup."""

    def __init__(
        self, sandbox: Any, *, config: dict, harness_dir: str, mode: str
    ) -> None:
        self.sandbox = sandbox
        self.config = config
        self.docker = (
            config.get("sandbox", "docker" if mode != "module" else "local") == "docker"
        )
        self.root = (
            "/opt/nanobot"
            if self.docker
            else str(Path(config["nanobot_root"]).expanduser().resolve())
        )
        self.harness = "/opt/harness" if self.docker else harness_dir
        self.python = (
            "python"
            if self.docker
            else str(config.get("python") or Path(self.root) / ".venv/bin/python")
        )
        self.process_env = {
            key: value
            for key, value in os.environ.items()
            if not self.docker
            and key
            in {"PATH", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR"}
        }
        if self.docker:
            self.process_env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
        self.process_env.update(
            PYTHONPATH=os.pathsep.join(
                [self.root, self.harness]
                + ([] if self.docker else [str(Path(__file__).parent)])
            ),
            PYTHONUNBUFFERED="1",
        )
        self.workspace: str | None = None
        self.runtime_dir: str | None = None
        self.runtime_environment: dict = {}

    def command(self, args: list[str]) -> list[str]:
        return [
            "env",
            "-i",
            *[f"{key}={value}" for key, value in self.process_env.items()],
            *args,
        ]

    async def step(self, action: dict[str, Any]) -> Any:
        return await self.sandbox.exec(
            self.command(action["command"]),
            **{
                key: action[key] for key in ("input", "cwd", "timeout") if key in action
            },
        )

    async def reset(self, initial_state: dict[str, str] | None) -> None:
        fixtures = (
            validate_fixtures(initial_state) if initial_state is not None else None
        )
        setup = await self.step(
            {
                "command": [
                    self.python,
                    "-c",
                    "import os,pathlib,json,platform,importlib.metadata as m; "
                    "pathlib.Path('workspace').mkdir(exist_ok=True); "
                    "pathlib.Path('runtime').mkdir(exist_ok=True); "
                    "print(json.dumps({'cwd':os.getcwd(),'python':platform.python_version(),"
                    "'packages':{d.metadata['Name']:d.version "
                    "for d in m.distributions()}}))",
                ]
            }
        )
        if not setup.success:
            raise RuntimeError(
                "Inspect could not initialize nanobot workspace: " + setup.stderr
            )
        runtime = json.loads(setup.stdout)
        root = runtime.pop("cwd")
        self.workspace, self.runtime_dir = root + "/workspace", root + "/runtime"
        if self.docker and self.config.get("_inspect_docker_compose"):
            from ..benchmark.inspect_docker import bind_docker_environment

            runtime["docker_binding"] = bind_docker_environment(
                self.config["_inspect_docker_compose"], runtime
            )
        self.runtime_environment = runtime
        if fixtures is not None:
            # Keep all path decisions in the worker interpreter's containment
            # helper; the payload is JSON data, never interpolated source code.
            seeded = await self.step(
                {
                    "command": [self.python, "-c", _RESET_SCRIPT, self.workspace],
                    "input": json.dumps(fixtures, ensure_ascii=False),
                }
            )
            if not seeded.success:
                raise ValueError("fixture initialization failed: " + seeded.stderr)

    async def snapshot(self) -> dict[str, str]:
        if self.workspace is None:
            raise RuntimeError("reset the environment before use")
        measured = await self.step(
            {
                "command": [
                    self.python,
                    "-c",
                    "import json,sys; from local_files import snapshot_files; "
                    "from pathlib import Path; "
                    "print(json.dumps(snapshot_files(Path(sys.argv[1])),ensure_ascii=False))",
                    self.workspace,
                ]
            }
        )
        if not measured.success:
            raise ValueError("independent snapshot failed: " + measured.stderr)
        return json.loads(measured.stdout)

    async def final_state(self) -> dict[str, str]:
        return await self.snapshot()

    async def teardown(self) -> None:
        # Inspect owns deletion of sample files, cancellation and process groups.
        # Do not remove retained evidence before Inspect has written its log.
        self.workspace = self.runtime_dir = None


_RESET_SCRIPT = """import json,sys,shutil
from pathlib import Path
from local_files import safe_path
root = Path(sys.argv[1])
fixtures = json.load(sys.stdin)
for name in fixtures:
    safe_path(root, name)
for child in root.iterdir():
    if child.is_dir() and not child.is_symlink():
        shutil.rmtree(child)
    else:
        child.unlink()
for name, content in fixtures.items():
    path = safe_path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8', newline='')
"""
