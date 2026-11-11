"""显式离线 operation 协议：执行计划不含 Oracle，判定在执行后进行。"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import Field
from referencing import Registry
from referencing.exceptions import NoSuchResource

from .readiness import StrictRecord

TOOLS = frozenset(
    {
        "query_information",
        "prepare_resource",
        "query_user_info",
        "query_gift_info",
        "query_pool_config",
        "add_gift_to_backpack",
    }
)


def _no_remote(uri):
    raise NoSuchResource(ref=uri)


def schema_validator(schema):
    """离线验证，既不下载外部 Schema，也不执行任何数据中的代码。"""

    def check(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"$ref", "$dynamicRef"} and (
                    not isinstance(value, str) or not value.startswith("#")
                ):
                    raise ValueError("external schema references are forbidden")
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(schema)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=Registry(retrieve=_no_remote))


class OperationPlan(StrictRecord):
    operation: Literal[
        "validate_arguments",
        "validate_selection_modes",
        "invoke_tool",
        "authorization_sequence",
        "idempotency_sequence",
    ]
    target_id: str
    tool_name: str = ""
    contract_schema: dict[str, Any]
    arguments: dict[str, Any] = Field(default_factory=dict)
    records: dict[str, Any] = Field(default_factory=dict)
    authorized: bool = False
    setup_calls: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)


def matching_records(name, args):
    """两个已有文本前置模板的固定解释，只根据输入构造数据。"""
    if name == "query_user_info":
        user = {
            "user_id": 1,
            "room_id": 1,
            "email": "fixture@example.test",
            "phone": "15000000200",
        }
        user.update({k: v for k, v in args.items() if v is not None})
        return {"users": [user]}
    if name == "query_information":
        return {"resources": [{"resource_id": 1, **args}]}
    if name == "query_gift_info":
        ids = args.get("gift_ids") or [args.get("gift_id") or 1]
        return {
            "gifts": [
                {"gift_id": i, "gift_name": args.get("gift_name") or "x"} for i in ids
            ]
        }
    if name == "query_pool_config":
        return {
            "pools": [
                {
                    "pool_id": args.get("pool_id") or 1,
                    "gift_ids": [args.get("gift_id") or 1],
                }
            ]
        }
    if name == "add_gift_to_backpack":
        users = args.get("user_ids") or [args.get("user_id")]
        gifts = args.get("gift_ids") or (
            [g["gift_id"] for g in args["gift_nums"]]
            if args.get("gift_nums")
            else [args.get("gift_id")]
        )
        return {
            "users": [{"user_id": i} for i in set(users)],
            "gifts": [{"gift_id": i} for i in set(gifts)],
            "grants": [],
        }
    raise ValueError("no matching-record recipe")


def plan_for(case, schemas) -> OperationPlan | None:
    p = case.payload
    if p.get("dataset_format") != "capability_contract_case":
        return None
    inp, pre, target = p.get("input"), p.get("preconditions"), p.get("target_id")
    if (
        not isinstance(inp, dict)
        or not isinstance(pre, list)
        or not isinstance(target, str)
        or target not in schemas
        or not all(isinstance(item, dict) for item in pre)
    ):
        return None
    op = inp.get("operation")
    schema = schemas[target]
    if op == "validate_arguments":
        if (
            set(inp) != {"operation", "arguments", "parameter", "dimension"}
            or not isinstance(inp["arguments"], dict)
            or len(pre) != 1
            or pre[0].get("kind") != "validation_only"
            or pre[0].get("invoke_handler") is not False
            or set(pre[0]) - {"kind", "invoke_handler", "note"}
        ):
            return None
        parameters = schema.get("parameters", schema)
        schema_validator(parameters)
        return OperationPlan(
            operation=op,
            target_id=target,
            contract_schema=parameters,
            arguments=deepcopy(inp["arguments"]),
        )
    name = target.removeprefix("tool.")
    if target != "tool." + name or name not in TOOLS:
        return None
    if op == "validate_selection_modes":
        if (
            set(inp) != {"operation", "arguments", "modes"}
            or not isinstance(inp["arguments"], dict)
            or pre != [{"kind": "validation_only", "invoke_handler": False}]
        ):
            return None
        return OperationPlan(
            operation=op,
            target_id=target,
            tool_name=name,
            contract_schema=schema,
            arguments=deepcopy(inp["arguments"]),
        )
    if op not in {"invoke_tool", "authorization_sequence", "idempotency_sequence"}:
        return None
    if inp.get("tool_name") != name or set(inp) != {
        "operation",
        "tool_name",
        "arguments" if op == "invoke_tool" else "steps",
    }:
        return None
    if op == "invoke_tool":
        if not isinstance(inp["arguments"], dict):
            return None
        steps = [{"action": "invoke", "arguments": deepcopy(inp["arguments"])}]
    else:
        raw = inp["steps"]
        if (
            not isinstance(raw, list)
            or len(raw) != 3
            or not all(isinstance(item, dict) for item in raw)
        ):
            return None
        if op == "authorization_sequence":
            if (
                name != "add_gift_to_backpack"
                or raw[0] != {"action": "owner_authorize_one_attempt"}
                or any(
                    set(s) != {"action", "arguments"}
                    or s["action"] != "invoke"
                    or not isinstance(s["arguments"], dict)
                    for s in raw[1:]
                )
            ):
                return None
            steps = deepcopy(raw)
        else:
            if name != "prepare_resource" or any(
                set(s) != {"arguments"} or not isinstance(s["arguments"], dict)
                for s in raw
            ):
                return None
            steps = [{"action": "invoke", **deepcopy(s)} for s in raw]
    args = next(s["arguments"] for s in steps if s["action"] == "invoke")
    records, authorized, setup_calls = {}, False, []
    if op == "idempotency_sequence":
        if pre != [{"kind": "fresh_fixture", "share_instance_within_case": True}]:
            return None
    elif op == "authorization_sequence":
        if pre != [
            {
                "kind": "fixture_setup",
                "required": "All selected IDs exist; no authorization initially.",
            }
        ]:
            return None
        records = matching_records(name, args)
    else:
        if len(pre) not in {1, 2} or pre[0].get("kind") != "fixture_setup":
            return None
        setup = pre[0]
        if setup == {
            "kind": "fixture_setup",
            "required": "Provide matching isolated records.",
        }:
            if not name.startswith("query_"):
                return None
            records = matching_records(name, args)
        else:
            if (
                set(setup)
                - {
                    "kind",
                    "records",
                    "result_branch",
                    "fresh_instance",
                    "owner_authorized_attempts",
                    "steps",
                }
                or setup.get("fresh_instance") is not True
                or not isinstance(setup.get("records"), dict)
                or type(setup.get("owner_authorized_attempts", 0)) is not int
                or setup.get("owner_authorized_attempts", 0) not in (0, 1)
            ):
                return None
            records = deepcopy(setup["records"])
            authorized = setup.get("owner_authorized_attempts", 0) == 1
            setup_steps = setup.get("steps", [])
            if not isinstance(setup_steps, list) or not all(
                isinstance(item, dict) for item in setup_steps
            ):
                return None
            for s in setup_steps:
                if (
                    set(s) != {"invoke", "arguments"}
                    or s["invoke"] != name
                    or not isinstance(s["arguments"], dict)
                ):
                    return None
                setup_calls.append(
                    {"name": name, "arguments": deepcopy(s["arguments"])}
                )
        if len(pre) == 2:
            if pre[1] != {"kind": "external_owner_authorization", "attempts": 1}:
                return None
            # This repeats the same one-attempt setup declaration, not a second grant.
            authorized = True
    if set(records) - {"user", "users", "gifts", "pools", "resources", "grants"}:
        return None
    if "user" in records:
        if "users" in records or not isinstance(records["user"], dict):
            return None
        records["users"] = [records.pop("user")]
    if any(
        not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows)
        for rows in records.values()
    ):
        return None
    for field, key in [
        ("users", "user_id"),
        ("gifts", "gift_id"),
        ("pools", "pool_id"),
    ]:
        rows = records.get(field, [])
        if any(type(r.get(key)) is not int or r[key] <= 0 for r in rows):
            return None
        if len({r[key] for r in rows}) != len(rows):
            return None
    return OperationPlan(
        operation=op,
        target_id=target,
        tool_name=name,
        contract_schema=schema,
        records=records,
        authorized=authorized,
        setup_calls=setup_calls,
        steps=steps,
    )


def _value(context, path):
    if not isinstance(path, str) or not re.fullmatch(
        r"[a-zA-Z_][\w]*(?:\[\d+\]|\.[a-zA-Z_]\w*)*", path
    ):
        raise ValueError("unsupported assertion path")
    value = context
    for key, index in re.findall(r"([a-zA-Z_]\w*)|\[(\d+)\]", path):
        value = value[key] if key else value[int(index)]
    return value


def initial_state_for(plan):
    state = {name: {} for name in ("users", "gifts", "pools", "requests")}
    for name, key in [("users", "user_id"), ("gifts", "gift_id"), ("pools", "pool_id")]:
        state[name] = {str(r[key]): r for r in plan.records.get(name, [])}
    state["resources"] = plan.records.get("resources", [])
    state["grants"] = plan.records.get("grants", [])
    return state


def complete_state(value):
    if not isinstance(value, dict) or set(value) != {
        "users",
        "gifts",
        "pools",
        "resources",
        "requests",
        "grants",
    }:
        return False
    return (
        all(isinstance(value[k], dict) for k in ("users", "gifts", "pools", "requests"))
        and all(
            isinstance(value[k], list) and all(isinstance(r, dict) for r in value[k])
            for k in ("resources", "grants")
        )
        and all(
            all(isinstance(r, dict) for r in value[k].values())
            for k in ("users", "gifts", "pools")
        )
    )


def operation_checks(case, plan, row) -> dict[str, bool]:
    expected_calls = [
        {"name": plan.tool_name, "arguments": s["arguments"]}
        for s in plan.steps
        if s["action"] == "invoke"
    ]
    checks = {
        "harness_binding": row.execution == plan.model_dump(mode="json")
        and row.tool_calls == expected_calls
        and row.evidence_complete
        and not row.errors,
        "execution_completed": row.status == "completed",
    }
    obs = row.observations
    if plan.tool_name:
        checks["fixture_initialized"] = obs.get("initial_state") == initial_state_for(
            plan
        )
    context = {
        "tool_result": row.tool_result,
        "input": {"arguments": plan.arguments},
        "argument_validator": {"accepted": obs.get("accepted")},
        "fixture": {"before": row.before_state, "after": row.after_state},
        "step": obs.get("steps", []),
        "state": {"after_step": obs.get("states", [])},
    }
    oracle = case.payload.get("oracle", {})
    assertions = oracle.get("checks", [])
    checks["assertions_present"] = isinstance(assertions, list) and bool(assertions)
    for i, c in enumerate(assertions if isinstance(assertions, list) else []):
        passed = False
        try:
            if set(c) != {"op", "actual", "expected"}:
                raise ValueError("invalid assertion")
            actual = _value(context, c["actual"])
            expected = c["expected"]
            if isinstance(expected, dict) and set(expected) == {"ref"}:
                expected = _value(context, expected["ref"])
            if c["op"] == "schema_valid":
                if c["actual"] == "input.arguments" and type(expected) is bool:
                    passed = obs.get("schema_valid") is expected
                elif isinstance(expected, dict):
                    passed = schema_validator(expected).is_valid(actual)
            elif c["op"] in {"equals", "unchanged"}:
                # bool must never compare equal to integers or absent observations.
                passed = type(actual) is type(expected) and actual == expected
            elif c["op"] == "count" and isinstance(actual, (list, dict)):
                passed = type(expected) is int and len(actual) == expected
        except (ValueError, TypeError, KeyError, IndexError, SchemaError):
            passed = False
        checks[f"oracle_{i}"] = passed
    terminal = oracle.get("declared_terminal_status")
    if terminal is not None:
        checks["declared_terminal_status"] = terminal in {
            "success",
            "business_failure",
        } and row.tool_result.get("success") is (terminal == "success")
    if plan.operation in {"validate_arguments", "validate_selection_modes"}:
        checks["no_handler_invocation"] = (
            not row.tool_calls
            and row.before_state == row.after_state
            and (not plan.tool_name or row.before_state == obs.get("initial_state"))
        )
    else:
        states, setup_states = obs.get("states", []), obs.get("setup_states", [])
        states_valid = (
            isinstance(states, list)
            and isinstance(setup_states, list)
            and len(states) == len(plan.steps)
            and len(setup_states) == len(plan.setup_calls)
            and all(
                complete_state(state)
                for state in [row.before_state, row.after_state, *states, *setup_states]
            )
        )
        checks["state_evidence_complete"] = states_valid
        checks["state_evidence_connected"] = bool(
            states_valid
            and row.before_state
            == (setup_states[-1] if setup_states else obs.get("initial_state"))
            and row.after_state == states[-1]
        )
        checks["authorization_initialized"] = (
            obs.get("authorization_before") is plan.authorized
        )
        checks["setup_bound"] = (
            obs.get("setup_calls") == plan.setup_calls
            and len(obs.get("setup_results", [])) == len(plan.setup_calls)
            and all(r.get("success") is True for r in obs.get("setup_results", []))
        )
        checks["steps_complete"] = (
            len(obs.get("steps", [])) == len(plan.steps) == len(obs.get("states", []))
        )
        if plan.tool_name.startswith("query_"):
            checks["read_only"] = row.before_state == row.after_state
        if plan.operation == "authorization_sequence":
            checks["authorization_consumed"] = obs.get("authorization_after_step") == [
                True,
                False,
                False,
            ]
        if plan.operation == "idempotency_sequence":
            states = obs.get("states", [])
            checks["retry_without_mutation"] = (
                len(states) == 3 and states[0] == states[1] == states[2]
            )
    return checks
