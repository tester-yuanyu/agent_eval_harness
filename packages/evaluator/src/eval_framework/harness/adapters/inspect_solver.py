"""Inspect Solver bridge: public task assembly, execution and evidence extraction."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

import anyio
from eval_contracts.benchmark import TaskInput
from inspect_ai.log import transcript
from inspect_ai.model import ChatMessageSystem
from inspect_ai.solver import Generate, Solver, TaskState, solver

from ...environments import SandboxFilesEnvironment
from ...environments.base.protocol import Environment
from ..core.agent_loop import run_agent_loop
from ..core.session_state import SessionState
from ..core.tool_router import ToolRouter, business_info
from ..prompts import render_prompt
from ..trace.timeline_extractor import extract_timeline
from ..user_simulator import FixedFollowupUserSimulator
from .agent.base import BaseAgent
from .agent.raw_model_adapter import RawModelAgentAdapter


async def execute_native_task(
    task: TaskInput,
    *,
    agent: BaseAgent | None = None,
    environment: Environment | None = None,
    max_steps: int | None = None,
    max_tool_calls: int = 40,
    timeout_seconds: float | None = None,
    max_consecutive_errors: int | None = None,
    prompt_version: str = "harness-v1",
    instructions: str = "",
    task_state: TaskState | None = None,
    execution_kind: str = "harness_raw_model",
) -> dict[str, Any]:
    # Re-validate public-only fields; TaskSpec subclasses cannot sneak in Oracle.
    task = TaskInput.model_validate(
        {name: deepcopy(getattr(task, name)) for name in TaskInput.model_fields}
    )
    start = len(transcript().events)
    environment = environment or SandboxFilesEnvironment(task.tools)
    prompt, prompt_identity = render_prompt(prompt_version, instructions)
    if task.policy:
        prompt += "\n\n" + task.policy
    prompt_identity["rendered_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
    session = SessionState(
        task_id=task.task_id, messages=[ChatMessageSystem(content=prompt)]
    )
    if task_state is not None:
        task_state.messages = session.messages
        session.messages = task_state.messages
    error = None
    active_agent = agent or RawModelAgentAdapter()
    entered_loop = False
    phase = "environment"

    def record_failure(exc: BaseException, kind: str) -> None:
        nonlocal error
        error = error or exc
        business_info(
            "execution_error",
            kind_of_error=kind,
            code=type(exc).__name__,
            message=str(exc),
        )
        if session.stop_reason in {None, "completed"}:
            session.stop_reason = kind + "_error"
            business_info("stop", reason=session.stop_reason)

    try:
        phase = "provider"
        if prepare := getattr(active_agent, "prepare_prompt", None):
            prompt, identity = prepare(prompt)
            prompt_identity.update(identity)
            session.messages[0] = ChatMessageSystem(content=prompt)
        phase = "environment"
        await environment.reset(task.initial_state)
        business_info("initial_state", snapshot=await environment.snapshot())
        business_info("prompt", **prompt_identity)
        phase = "harness"
        router = ToolRouter(environment.tool_schemas())
        simulator = FixedFollowupUserSimulator(task.prompt, task.followups)
        entered_loop = True
        await run_agent_loop(
            active_agent,
            session,
            router=router,
            environment=environment,
            simulator=simulator,
            max_steps=min(task.max_steps, max_steps or task.max_steps),
            max_tool_calls=max_tool_calls,
            timeout_seconds=timeout_seconds,
            max_consecutive_errors=max_consecutive_errors,
        )
    except BaseException as exc:
        error = exc
        if session.stop_reason in {None, "completed"}:
            record_failure(exc, phase)
    finally:
        with anyio.CancelScope(shield=True):
            if not entered_loop:
                try:
                    await active_agent.close()
                except Exception as exc:
                    record_failure(exc, "harness")
            try:
                business_info("final_state", snapshot=await environment.snapshot())
            except Exception as exc:
                record_failure(exc, "environment")
            try:
                await environment.teardown()
            except Exception as exc:
                record_failure(exc, "environment")
    with anyio.CancelScope(shield=True):
        observation = await extract_timeline(
            task.task_id, list(transcript().events[start:])
        )
    observation["prompt_identity"] = prompt_identity
    observation["execution_kind"] = execution_kind
    if task_state is not None:
        task_state.messages = session.messages
        if session.last_output is not None:
            task_state.output = session.last_output
        task_state.metadata["harness_observation"] = observation
        task_state.completed = True
    if error is not None:
        error.benchmark_observation = observation
        raise error
    return observation


@solver
def harness_solver(
    tasks: dict[str, TaskInput],
    *,
    max_steps: int | None = None,
    max_tool_calls: int = 40,
    timeout_seconds: float | None = None,
    max_consecutive_errors: int | None = None,
    prompt_version: str = "harness-v1",
    instructions: str = "",
) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        await execute_native_task(
            tasks[str(state.sample_id)],
            max_steps=max_steps,
            max_tool_calls=max_tool_calls,
            timeout_seconds=timeout_seconds,
            max_consecutive_errors=max_consecutive_errors,
            prompt_version=prompt_version,
            instructions=instructions,
            task_state=state,
        )
        return state

    return solve
