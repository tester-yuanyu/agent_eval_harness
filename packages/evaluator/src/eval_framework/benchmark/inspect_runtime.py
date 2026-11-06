"""Inspect public APIs own sample execution; this module projects business evidence."""

from __future__ import annotations

import base64
import os
import sys
import uuid
from pathlib import Path, PurePosixPath

from ..harness.tracer import (
    aggregate_usage as aggregate_usage,
)
from ..harness.tracer import (
    apply_native_limits as apply_native_limits,
)
from ..harness.tracer import (
    evidence_is_complete as evidence_is_complete,
)
from ..harness.tracer import (
    model_evidence as model_evidence,
)


def sample_files(fixtures: dict[str, str]) -> dict[str, str]:
    """Literal fixture bytes, never an Inspect source-file/URL interpretation."""
    result = {}
    for name, contents in fixtures.items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("fixture path must be inside the sample workspace")
        result[f"workspace/{path}"] = "data:text/plain;base64," + base64.b64encode(
            contents.encode("utf-8")
        ).decode("ascii")
    return result


def inspect_model(config: dict):
    """Only Inspect receives provider credentials; workers receive a proxy token."""
    from inspect_ai.model import GenerateConfig, get_model

    name = str(config.get("inspect_model") or config.get("model", "mockllm/model"))
    if "/" not in name:
        name = "openai/" + name
    key = os.environ.get(config.get("api_key_env", "DEEPSEEK_API_KEY"))
    if not name.startswith("mockllm/") and not key:
        raise ValueError(f"missing {config.get('api_key_env', 'DEEPSEEK_API_KEY')}")
    return get_model(
        name,
        base_url=config.get("base_url"),
        api_key=key,
        config=GenerateConfig(
            temperature=config.get("temperature", 0),
            max_tokens=config.get("max_tokens", 2048),
            extra_body=config.get("extra_body"),
            max_retries=0,
        ),
    )


def sandbox_spec(config: dict, output: Path, *, needs_model: bool):
    kind = config.get("sandbox", "docker" if needs_model else "local")
    if kind not in {"local", "docker"}:
        raise ValueError("sandbox must be local or docker")
    if kind == "local":
        if needs_model and sys.platform != "linux":
            raise ValueError(
                "Inspect sandbox_agent_bridge requires Linux; "
                "use sandbox=docker on macOS"
            )
        return "local"
    from .inspect_docker import prepare_docker_sandbox

    return prepare_docker_sandbox(config, output)


async def execute_boundary(
    task: dict, *, config: dict, workspace: Path | None, mode: str, identity: dict
) -> dict:
    """Use the active sample, or create one for the historical direct Python API."""
    from inspect_ai.util import sandbox

    model_name = str(config.get("inspect_model") or config.get("model", ""))
    key_name = config.get("api_key_env", "DEEPSEEK_API_KEY")
    if (
        mode != "module"
        and not model_name.startswith("mockllm/")
        and not os.environ.get(key_name)
    ):
        from ..environments.local_files import snapshot_files

        before = snapshot_files(workspace) if workspace else None
        return {
            "status": "error",
            "errors": [
                {
                    "kind": "environment",
                    "code": "missing_api_key",
                    "message": f"missing {key_name}",
                }
            ],
            "events": [],
            "turns": [],
            "usage": {},
            "before_files": before,
            "final_files": before,
            "runtime_identity": identity,
            "evidence_complete": False,
        }
    try:
        environment = sandbox()
    except ProcessLookupError:
        environment = None
    if environment is None:
        if workspace is None:
            raise ValueError("workspace is required outside an Inspect sample")
        return await _standalone(
            task, config=config, workspace=workspace, mode=mode, identity=identity
        )
    return await _execute(task, config=config, mode=mode, identity=identity)


async def _standalone(
    task: dict, *, config: dict, workspace: Path, mode: str, identity: dict
) -> dict:
    from inspect_ai import Task, eval_async
    from inspect_ai.dataset import Sample
    from inspect_ai.solver import solver

    from ..environments.local_files import safe_path, snapshot_files

    workspace = workspace.resolve(strict=True)
    captured = {}
    model = inspect_model(config) if mode != "module" else "mockllm/model"
    run_dir = workspace.parent / ".inspect-runtime" / uuid.uuid4().hex
    spec = sandbox_spec(config, run_dir / "docker", needs_model=mode != "module")
    effective = {**config, "sandbox": "docker" if isinstance(spec, tuple) else spec}
    if isinstance(spec, tuple):
        effective["_inspect_docker_compose"] = spec[1]

    @solver
    def execute():
        async def solve(state, generate):
            try:
                captured.update(
                    await _execute(task, config=effective, mode=mode, identity=identity)
                )
            except BaseException as exc:
                captured.update(getattr(exc, "benchmark_observation", {}))
                raise
            return state

        return solve

    logs = await eval_async(
        Task(
            name="nanobot_boundary",
            dataset=[
                Sample(
                    input=task["prompt"], files=sample_files(snapshot_files(workspace))
                )
            ],
            solver=execute(),
            sandbox=spec,
            token_limit=config.get("token_limit"),
            message_limit=config.get("message_limit"),
            time_limit=int(config.get("timeout_seconds", 180)),
        ),
        model=model,
        log_dir=str(run_dir / "logs"),
        notification=False,
        ctl_server=False,
        fail_on_error=False,
    )
    if not captured:
        error = (
            logs[0].error.message
            if logs and logs[0].error
            else "Inspect sample did not produce evidence"
        )
        raise RuntimeError(error)
    for log in logs:
        for sample in log.samples or []:
            apply_native_limits(captured, sample.events)
    if isinstance(captured.get("final_files"), dict):
        for name in snapshot_files(workspace).keys() - captured["final_files"].keys():
            safe_path(workspace, name).unlink()
        for name, content in captured["final_files"].items():
            path = safe_path(workspace, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="")
    return captured


async def _execute(task: dict, *, config: dict, mode: str, identity: dict) -> dict:
    """Historical entrypoint; the nanobot integration owns its worker bridge."""
    from ..integrations.nanobot.inspect_bridge import execute_inspect_task

    return await execute_inspect_task(
        task,
        config=config,
        mode=mode,
        identity=identity,
        harness_dir=str(Path(__file__).parent),
    )
