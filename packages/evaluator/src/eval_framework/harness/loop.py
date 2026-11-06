"""Inspect-owned execution lifecycle composed from Environment and Tracer.

Target Agent workers remain independent and retain their own AgentLoop.
"""

from __future__ import annotations

import json

from ..environments import InspectFileToolsEnvironment
from .tracer import (
    aggregate_usage,
    evidence_is_complete,
    model_evidence,
    read_file_events,
)
from .user_simulator import public_messages


async def execute_inspect_task(
    task: dict, *, config: dict, mode: str, identity: dict, harness_dir: str
) -> dict:
    import anyio
    from inspect_ai.util import sandbox

    environment = InspectFileToolsEnvironment(
        sandbox(), config=config, harness_dir=harness_dir, mode=mode
    )
    try:
        return await _execute(
            task, config=config, mode=mode, identity=identity, environment=environment
        )
    finally:
        with anyio.CancelScope(shield=True):
            await environment.teardown()


async def _execute(
    task: dict,
    *,
    config: dict,
    mode: str,
    identity: dict,
    environment: InspectFileToolsEnvironment,
) -> dict:
    import anyio
    from inspect_ai.agent import sandbox_agent_bridge
    from inspect_ai.event import ModelEvent, SandboxEvent
    from inspect_ai.log import transcript
    from inspect_ai.util import LimitExceededError, sample_limits

    native_start = len(transcript().events)
    await environment.reset(None)
    before = await environment.snapshot()
    docker = environment.docker
    root, harness, python = environment.root, environment.harness, environment.python
    workspace, runtime_dir = environment.workspace, environment.runtime_dir
    runtime_environment = environment.runtime_environment
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
    if mode == "agent":
        messages = public_messages(task["prompt"], task.get("followups", []))
        task = {**task, "prompt": messages[0], "followups": messages[1:]}
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
        completed = await environment.step(
            {
                "command": [python, harness + "/" + worker],
                "input": json.dumps(payload, ensure_ascii=False),
                "cwd": runtime_dir,
                "timeout": config.get("module_timeout_seconds", 30)
                if mode == "module"
                else config.get("timeout_seconds", 180),
            }
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
                environment.process_env["INSPECT_BRIDGE_API_KEY"] = "inspect"
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
                raw = await environment.sandbox.read_file(runtime_dir + "/events.jsonl")
                result["events"] = read_file_events(raw)
            except FileNotFoundError:
                result["errors"].append(
                    {
                        "kind": "evidence",
                        "code": "file_evidence_missing",
                        "message": "worker did not persist file evidence",
                    }
                )
            try:
                result["final_files"] = await environment.final_state()
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
