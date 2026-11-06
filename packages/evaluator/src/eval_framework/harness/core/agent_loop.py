"""Harness-owned async loop inside an Inspect Solver, with no event storage."""

from copy import deepcopy

import anyio
from inspect_ai.model import ChatMessageUser

from ..adapters.agent.base import BaseAgent
from ..user_simulator import FixedFollowupUserSimulator
from .session_state import SessionState
from .stop_conditions import (
    ErrorStop,
    StepLimit,
    StopCondition,
    TimeoutStop,
    ToolCallLimit,
    first_stop,
)
from .tool_router import Environment, ToolRouter, business_info


async def run_agent_loop(
    agent: BaseAgent,
    state: SessionState,
    *,
    router: ToolRouter,
    environment: Environment | None,
    simulator: FixedFollowupUserSimulator,
    max_steps: int = 12,
    max_tool_calls: int = 40,
    timeout_seconds: float | None = None,
    max_consecutive_errors: int | None = None,
    stop_conditions: tuple[StopCondition, ...] = (),
) -> None:
    phase = "harness"
    try:
        if max_steps < 1 or max_tool_calls < 1:
            raise ValueError("budgets must be positive")
        conditions = (
            StepLimit(max_steps),
            ToolCallLimit(max_tool_calls),
            *stop_conditions,
        )
        if timeout_seconds is not None:
            conditions += (TimeoutStop(timeout_seconds),)
        if max_consecutive_errors is not None:
            conditions += (ErrorStop(max_consecutive_errors),)
        remaining = min(
            (c.remaining(state) for c in conditions if isinstance(c, TimeoutStop)),
            default=float("inf"),
        )
        state.tools = router.tool_infos()
        needs_user = True
        with anyio.move_on_after(remaining) as deadline:
            while state.stop_reason is None:
                if needs_user:
                    history = [m.model_dump(mode="json") for m in state.messages]
                    message = simulator.next_message(history)
                    if message is None:
                        state.stop_reason = "completed"
                        break
                    state.turn += 1
                    state.messages.append(ChatMessageUser(content=message["content"]))
                    business_info(
                        "turn_start", turn=state.turn, input=message["content"]
                    )
                    needs_user = False
                if reason := first_stop(conditions, state, "model"):
                    state.stop_reason = reason
                    break
                phase = "provider"
                state.steps += 1
                action = await agent.step(deepcopy(state))
                state.last_output = action.output
                state.messages.append(action.message)
                phase = "harness"
                if action.finish_reason not in {"stop", "tool_calls"}:
                    state.stop_reason = (
                        "model_length"
                        if action.finish_reason in {"max_tokens", "model_length"}
                        else "model_" + action.finish_reason
                    )
                    break
                calls = action.message.tool_calls or []
                if calls:
                    ids = [call.id for call in calls]
                    if len(set(ids)) != len(ids) or any(not value for value in ids):
                        state.stop_reason = "invalid_tool_call_ids"
                        break
                    for call in calls:
                        if reason := first_stop(conditions, state, "tool"):
                            state.stop_reason = reason
                            break
                        state.tool_calls += 1
                        phase = "environment"
                        if environment is None:
                            raise RuntimeError("tool calls require an environment")
                        results = await router.dispatch(
                            call, environment, turn=state.turn
                        )
                        state.messages.extend(results)
                        state.consecutive_errors = (
                            state.consecutive_errors + 1
                            if any(m.error for m in results)
                            else 0
                        )
                        phase = "harness"
                        # Check the error policy immediately, including the last call
                        # in a batch. Tool/step budgets remain pre-operation checks.
                        errors = tuple(
                            c for c in conditions if isinstance(c, ErrorStop)
                        )
                        if reason := first_stop(errors, state, "tool"):
                            state.stop_reason = reason
                            break
                else:
                    phase = "environment"
                    snapshot = await environment.snapshot() if environment else {}
                    phase = "harness"
                    business_info(
                        "turn_end",
                        turn=state.turn,
                        output=action.message.text,
                        snapshot=snapshot,
                    )
                    needs_user = True
        if deadline.cancel_called:
            state.stop_reason = "time_limit"
    except BaseException as exc:
        from inspect_ai.util import LimitExceededError

        if isinstance(exc, LimitExceededError):
            state.stop_reason = exc.type + "_limit"
            phase = "agent"
        elif not isinstance(exc, Exception):
            state.stop_reason = "cancelled"
        else:
            state.stop_reason = phase + "_error"
        business_info(
            "execution_error",
            kind_of_error=phase,
            code=type(exc).__name__,
            message=str(exc),
        )
        raise
    finally:
        business_info(
            "stop",
            reason=state.stop_reason,
            steps=state.steps,
            tool_calls=state.tool_calls,
            consecutive_errors=state.consecutive_errors,
        )
        with anyio.CancelScope(shield=True):
            await agent.close()
