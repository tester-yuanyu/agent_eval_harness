"""Inspect 本地 operation executor；只接受剥离 Oracle 后的执行计划。"""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from eval_contracts.agent_readiness import AgentPlan, binding_for, reference_context
from eval_contracts.full_readiness import FullEvidence, FullRequest, ToolEvidence
from eval_contracts.operation_readiness import OperationPlan, schema_validator
from eval_contracts.readiness import RunnerIdentity


def execute_plan(
    case_id: str, plan: OperationPlan, factory: Callable[[], Any] | None = None
) -> ToolEvidence:
    row = ToolEvidence(
        case_id=case_id,
        status="error",
        evidence_complete=False,
        before_state={},
        after_state={},
        tool_calls=[],
        tool_result={},
        errors=[],
        execution=plan.model_dump(mode="json"),
    )
    try:
        if plan.operation == "validate_arguments":
            errors = list(
                schema_validator(plan.contract_schema).iter_errors(plan.arguments)
            )
            row.observations = {
                "schema_valid": not errors,
                "validation_errors": [e.message for e in errors],
            }
        else:
            _execute_tool(plan, factory, row)
        row.status = "completed"
        row.evidence_complete = True
    except Exception as exc:
        row.errors.append(f"{type(exc).__name__}: {exc}")
    return row


def _snapshot(env: Any) -> dict[str, Any]:
    # Authorization is execution control, not business data; recorded separately.
    return json.loads(
        json.dumps(
            {
                name: deepcopy(getattr(env, name))
                for name in (
                    "users",
                    "gifts",
                    "pools",
                    "resources",
                    "requests",
                    "grants",
                )
            }
        )
    )


def _execute_tool(
    plan: OperationPlan, factory: Callable[[], Any] | None, row: ToolEvidence
) -> None:
    from pydantic import ValidationError

    from .full_readiness import function_schema

    if factory is None:
        raise ValueError("tool fixture factory missing")
    env = factory()
    for field, key in [
        ("users", "user_id"),
        ("gifts", "gift_id"),
        ("pools", "pool_id"),
    ]:
        records = deepcopy(plan.records.get(field, []))
        values = {r[key]: r for r in records}
        if len(records) != len(values):
            raise ValueError("duplicate fixture primary key")
        setattr(env, field, values)
    env.resources = deepcopy(plan.records.get("resources", []))
    env.grants = deepcopy(plan.records.get("grants", []))
    env.requests = {}
    env._grant_approved = False
    registry = env.registry()
    definition = registry.get(plan.tool_name)
    if function_schema(definition.schema()) != function_schema(plan.contract_schema):
        raise ValueError("runtime tool schema differs from reference bundle")
    initial_state = _snapshot(env)
    if plan.operation == "validate_selection_modes":
        row.before_state = _snapshot(env)
        try:
            definition.arguments_model.model_validate(plan.arguments)
            row.observations = {"accepted": True, "validation_errors": []}
        except ValidationError as exc:
            row.observations = {"accepted": False, "validation_errors": [str(exc)]}
        row.after_state = _snapshot(env)
        row.observations["initial_state"] = initial_state
        return
    row.observations = {
        "initial_state": initial_state,
        "setup_calls": [],
        "setup_results": [],
        "setup_states": [],
        "steps": [],
        "states": [],
        "authorization_after_step": [],
    }
    for call in plan.setup_calls:
        result = registry.invoke(
            call["name"],
            deepcopy(call["arguments"]),
            allowed_tools=frozenset({plan.tool_name}),
        )
        row.observations["setup_calls"].append(deepcopy(call))
        row.observations["setup_results"].append(result.model_dump(mode="json"))
        row.observations["setup_states"].append(_snapshot(env))
        if not result.success:
            raise ValueError("fixture prerequisite invocation failed")
    if plan.authorized:
        env.approve_next_grant()
    row.before_state = _snapshot(env)
    row.observations["authorization_before"] = env._grant_approved
    for step in plan.steps:
        if step["action"] == "owner_authorize_one_attempt":
            env.approve_next_grant()
            result = {}
        else:
            call = {"name": plan.tool_name, "arguments": deepcopy(step["arguments"])}
            row.tool_calls.append(call)
            result = registry.invoke(
                plan.tool_name,
                deepcopy(step["arguments"]),
                allowed_tools=frozenset({plan.tool_name}),
            ).model_dump(mode="json")
            row.tool_result = result
        # Historical sequence selectors expose resources as a direct step member.
        row.observations["steps"].append({**result, **result.get("data", {})})
        row.observations["states"].append(_snapshot(env))
        row.observations["authorization_after_step"].append(env._grant_approved)
    row.after_state = _snapshot(env)


def run_operations(
    request: FullRequest, log_dir: Path, mini_root: Path, binding: RunnerIdentity
) -> FullEvidence:
    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.solver import Generate, Solver, TaskState, solver

    from .full_readiness import fixture_class, identity

    plans = {
        c.case_id: plan
        for c in request.cases
        if (plan := binding_for(c, request)) is not None
    }
    factory = (
        fixture_class(mini_root) if any(p.tool_name for p in plans.values()) else None
    )

    agent_executor = None
    if any(isinstance(p, AgentPlan) for p in plans.values()):
        from .agent_readiness import AgentReferenceExecutor

        agent_executor = AgentReferenceExecutor(
            reference_context(request), mini_root, log_dir / "business"
        )

    @solver
    def operation_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            plan = plans[str(state.sample_id)]
            # The actual validation / handler call occurs inside Inspect's solver.
            row = (
                agent_executor.execute(str(state.sample_id), plan)
                if isinstance(plan, AgentPlan)
                else execute_plan(str(state.sample_id), plan, factory)
            )
            state.metadata["reference_observation"] = row.model_dump(mode="json")
            state.metadata["execution_kind"] = (
                "scripted_model_real_agent"
                if isinstance(plan, AgentPlan)
                else "deterministic_reference_not_agent"
            )
            state.completed = True
            return state

        return solve

    if not plans:
        return FullEvidence(dataset_sha256=request.sha256(), runner=binding, results=[])
    log = inspect_eval(
        Task(
            dataset=[
                Sample(id=key, input="执行隔离契约验证。", target="") for key in plans
            ],
            solver=operation_solver(),
        ),
        model="mockllm/model",
        log_dir=str(log_dir),
        display="none",
        notification=False,
        ctl_server=False,
        max_samples=1,
        fail_on_error=False,
    )[0]
    results = []
    for sample in log.samples or []:
        data = (sample.metadata or {}).get("reference_observation")
        if data is None:
            row = ToolEvidence(
                case_id=str(sample.id),
                status="error",
                evidence_complete=False,
                before_state={},
                after_state={},
                tool_calls=[],
                tool_result={},
                errors=["Inspect observation missing"],
            )
        else:
            row = ToolEvidence.model_validate(data)
        if sample.error or log.status != "success":
            row.errors.append(str(sample.error or "Inspect run incomplete"))
            row.evidence_complete = False
        results.append(row)
    if (
        identity(
            mini_root,
            operations=True,
            agent=request.schema_version == "builder-full-readiness-v3",
        )
        != binding
    ):
        raise ValueError("runner implementation changed during verification")
    return FullEvidence(
        dataset_sha256=request.sha256(), runner=binding, results=results
    )
