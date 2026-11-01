"""Inspect public APIs own sample execution; this module projects business evidence."""

from __future__ import annotations

import base64
import json
import os
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any


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


def apply_native_limits(observation: dict, events: Sequence[Any]) -> None:
    """Finalize cancellation provenance after Inspect publishes its limit event."""
    from inspect_ai.event import SampleLimitEvent

    for event in events:
        if isinstance(event, SampleLimitEvent) and event.type in {
            "token",
            "message",
            "time",
        }:
            observation["status"] = "timeout" if event.type == "time" else "error"
            observation["stop_reason"] = f"{event.type}_limit"
            observation["evidence_complete"] = False
            errors = observation.setdefault("errors", [])
            errors[:] = [
                error for error in errors if error.get("code") != "CancelledError"
            ]
            errors.append(
                {
                    "kind": "agent",
                    "code": observation["stop_reason"],
                    "message": event.message,
                    "native_event_id": event.uuid,
                }
            )


async def model_evidence(events: Sequence[Any], file_events: list[dict]) -> list[dict]:
    """Compatibility projection of native ModelEvent, not a second model logger."""
    from inspect_ai.event import ModelEvent
    from inspect_ai.model import messages_to_openai

    turns = [item for item in file_events if item.get("type") == "turn"]
    result = []
    for event in events:
        if not isinstance(event, ModelEvent):
            continue
        started = event.timestamp.isoformat()
        turn = next(
            (item for item in reversed(turns) if item["start_time"] <= started), {}
        )
        output = event.output
        message = output.message if output and output.choices else None
        usage = output.usage if output else None
        result.append(
            {
                "id": event.uuid,
                "type": "generation",
                "name": event.model,
                "model": event.model,
                "response_model": output.model if output else None,
                "source": "inspect_ai.ModelEvent",
                "native_event_id": event.uuid,
                "start_time": started,
                "end_time": event.completed.isoformat() if event.completed else None,
                "parent_id": turn.get("id"),
                "turn": turn.get("turn"),
                "input": {
                    "messages": [
                        {
                            key: value
                            for key, value in message.items()
                            if key
                            in {"role", "content", "tool_calls", "tool_call_id", "name"}
                        }
                        for message in await messages_to_openai(event.input)
                    ],
                    "tools": [
                        {
                            "type": "function",
                            "function": tool.model_dump(mode="json", exclude_none=True),
                        }
                        for tool in event.tools
                    ],
                    "model": event.model,
                },
                "output": {
                    "content": message.text if message else None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "name": call.function,
                            "arguments": call.arguments,
                        }
                        for call in (message.tool_calls or [])
                    ]
                    if message
                    else [],
                    "finish_reason": output.stop_reason if output else None,
                },
                "usage": {
                    "prompt_tokens": usage.input_tokens,
                    "completion_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens,
                }
                if usage
                else {},
                "error": event.error,
                "incomplete": event.pending is True or event.completed is None,
            }
        )
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


def aggregate_usage(generations: list[dict]) -> dict:
    if not generations:
        return {}
    return {
        key: sum(item["usage"][key] for item in generations)
        if all(isinstance(item["usage"].get(key), (int, float)) for item in generations)
        else None
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }


def evidence_is_complete(result: dict, task: dict, mode: str) -> bool:
    if result["status"] != "completed" or not isinstance(result["final_files"], dict):
        return False
    events = result["events"]
    if any(event.get("incomplete") for event in events):
        return False
    turns = [event for event in events if event["type"] == "turn"]
    tools = [event for event in events if event["type"] == "tool"]
    if len(turns) != len(result["turns"]) or not turns:
        return False
    if any(not isinstance(turn.get("snapshot"), dict) for turn in result["turns"]):
        return False
    for event in tools:
        if not isinstance(event.get("after_files"), dict):
            return False
        if event.get("execution_started", True) and not isinstance(
            event.get("before_files"), dict
        ):
            return False
    if mode == "module" and len(tools) != len(task["module_calls"]):
        return False
    if (
        mode == "decision"
        and sum(event["type"] == "generation" for event in events) != 1
    ):
        return False
    return True


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
        from .nanobot_runtime import snapshot_files

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

    from .nanobot_runtime import safe_path, snapshot_files

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
    import anyio
    from inspect_ai.agent import sandbox_agent_bridge
    from inspect_ai.event import ModelEvent, SandboxEvent
    from inspect_ai.log import transcript
    from inspect_ai.util import LimitExceededError, sample_limits, sandbox

    env = sandbox()
    native_start = len(transcript().events)
    docker = (
        config.get("sandbox", "docker" if mode != "module" else "local") == "docker"
    )
    root = (
        "/opt/nanobot"
        if docker
        else str(Path(config["nanobot_root"]).expanduser().resolve())
    )
    harness = "/opt/harness" if docker else str(Path(__file__).parent)
    python = (
        "python"
        if docker
        else str(config.get("python") or Path(root) / ".venv/bin/python")
    )
    # Inspect local.exec adds env to the host. POSIX env -i gives the worker
    # an allowlist without replacing Inspect's process/sandbox lifecycle.
    process_env = {
        key: value
        for key, value in os.environ.items()
        if not docker
        and key in {"PATH", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    }
    if docker:
        process_env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    process_env.update(
        PYTHONPATH=os.pathsep.join([root, harness]), PYTHONUNBUFFERED="1"
    )

    def command(args):
        return [
            "env",
            "-i",
            *[f"{key}={value}" for key, value in process_env.items()],
            *args,
        ]

    setup = await env.exec(
        command(
            [
                python,
                "-c",
                "import os,pathlib,json,platform,importlib.metadata as m; "
                "pathlib.Path('workspace').mkdir(exist_ok=True); "
                "pathlib.Path('runtime').mkdir(exist_ok=True); "
                "print(json.dumps({'cwd':os.getcwd(),'python':platform.python_version(),"
                "'packages':{d.metadata['Name']:d.version "
                "for d in m.distributions()}}))",
            ]
        ),
    )
    if not setup.success:
        raise RuntimeError(
            "Inspect could not initialize nanobot workspace: " + setup.stderr
        )
    runtime_environment = json.loads(setup.stdout)
    sample_root = runtime_environment.pop("cwd")
    if docker and config.get("_inspect_docker_compose"):
        from .inspect_docker import bind_docker_environment

        runtime_environment["docker_binding"] = bind_docker_environment(
            config["_inspect_docker_compose"], runtime_environment
        )
    workspace = sample_root + "/workspace"
    runtime_dir = sample_root + "/runtime"
    snapshot_command = [
        python,
        "-c",
        "import json,sys; from nanobot_runtime import snapshot_files; "
        "from pathlib import Path; "
        "print(json.dumps(snapshot_files(Path(sys.argv[1])),ensure_ascii=False))",
        workspace,
    ]

    async def snapshot():
        measured = await env.exec(command(snapshot_command))
        if not measured.success:
            raise ValueError("independent snapshot failed: " + measured.stderr)
        return json.loads(measured.stdout)

    before = await snapshot()
    result = {
        "status": "error",
        "turns": [],
        "events": [],
        "usage": {},
        "errors": [],
        "before_files": before,
        "final_files": None,
        "runtime_identity": identity,
        "runtime_environment": runtime_environment,
        "evidence_complete": False,
        "execution_backend": "inspect_ai",
        "execution_kind": {
            "module": "real_module",
            "decision": "real_model_decision",
            "agent": "real_agent",
        }[mode],
        "isolation": "docker" if docker else "local-no-os-isolation",
    }
    effective = {**config, "nanobot_root": root}
    if docker:
        effective["tokenizer_cache_dir"] = "/opt/tokenizer"
    worker = {
        "module": "module_worker.py",
        "decision": "decision_worker.py",
        "agent": "nanobot_worker.py",
    }[mode]

    async def call_worker():
        payload = {
            "task": task,
            "config": effective,
            "workspace": workspace,
            "runtime_dir": runtime_dir,
        }
        completed = await env.exec(
            command([python, harness + "/" + worker]),
            input=json.dumps(payload, ensure_ascii=False),
            cwd=runtime_dir,
            timeout=config.get("module_timeout_seconds", 30)
            if mode == "module"
            else config.get("timeout_seconds", 180),
        )
        if not completed.success:
            raise RuntimeError(
                f"{mode} worker exited {completed.returncode}: "
                f"{completed.stderr[-2000:]}"
            )
        result.update(json.loads(completed.stdout))

    pending_error = None
    try:
        if mode == "module":
            await call_worker()
        else:
            async with sandbox_agent_bridge(forward_generation_config=True) as bridge:
                effective.update(
                    model="inspect",
                    base_url=f"http://localhost:{bridge.port}/v1",
                    api_key_env="INSPECT_BRIDGE_API_KEY",
                )
                process_env["INSPECT_BRIDGE_API_KEY"] = "inspect"
                await call_worker()
    except BaseException as exc:
        # Read Inspect's accounting only to classify its cancellation. Inspect
        # remains the sole owner of enforcement and the native limit event.
        limits = sample_limits()
        exhausted = next(
            (
                name
                for name in ("token", "time")
                if (resource := getattr(limits, name)).remaining is not None
                and resource.remaining <= 0
            ),
            None,
        )
        if isinstance(exc, LimitExceededError):
            exhausted = exc.type
        is_limit = isinstance(exc, LimitExceededError) or exhausted is not None
        result.update(
            status="timeout"
            if isinstance(exc, TimeoutError) or exhausted == "time"
            else "error",
            stop_reason=f"{exhausted or 'sample'}_limit"
            if is_limit
            else type(exc).__name__,
        )
        result["errors"].append(
            {
                "kind": "agent"
                if is_limit or isinstance(exc, TimeoutError)
                else "execution",
                "code": result["stop_reason"],
                "message": str(exc),
            }
        )
        if isinstance(exc, LimitExceededError) or not isinstance(exc, Exception):
            pending_error = exc
    finally:
        with anyio.CancelScope(shield=True):
            result["events"] = []
            try:
                raw = await env.read_file(runtime_dir + "/events.jsonl")
                entries = {}
                for line in raw.splitlines():
                    try:
                        event = json.loads(line)
                        entries[event["id"]] = event
                    except (ValueError, KeyError):
                        continue
                result["events"] = list(entries.values())
                for event in result["events"]:
                    event["source"] = "nanobot.file_evidence"
                    if event.get("end_time") is None:
                        event["incomplete"] = True
            except FileNotFoundError:
                result["errors"].append(
                    {
                        "kind": "evidence",
                        "code": "file_evidence_missing",
                        "message": "worker did not persist file evidence",
                    }
                )
            try:
                result["final_files"] = await snapshot()
            except Exception as exc:
                result["errors"].append(
                    {"kind": "evidence", "code": "snapshot_failed", "message": str(exc)}
                )
    events = list(transcript().events)[native_start:]
    with anyio.CancelScope(shield=True):
        generations = await model_evidence(events, result["events"])
    for event in events:
        if isinstance(event, ModelEvent) and event.error:
            result["status"] = "error"
            result["errors"].append(
                {
                    "kind": "provider",
                    "code": "inspect_model_error",
                    "message": event.error,
                    "native_event_id": event.uuid,
                }
            )
    result["events"].extend(generations)
    result["events"].sort(key=lambda event: event.get("start_time", ""))
    result["usage"] = aggregate_usage(generations)
    result["native_events"] = {
        "model": sum(isinstance(event, ModelEvent) for event in events),
        "sandbox": sum(isinstance(event, SandboxEvent) for event in events),
    }
    result["evidence_complete"] = evidence_is_complete(result, task, mode)
    transcript().info(result, source="benchmark_evidence")
    if pending_error is not None:
        pending_error.benchmark_observation = result
        raise pending_error
    return result
