"""Agent reference 的公开输入绑定与独立后置断言。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import Field

from .agent_reference_inputs import INTENT_TO_TOOL, decode
from .operation_readiness import complete_state, initial_state_for, schema_validator
from .readiness import StrictRecord


class AgentPlan(StrictRecord):
    category: Literal["intent_module", "early_stop", "module_event", "agent_chain"]
    scope: Literal["module", "link", "end_to_end"]
    user_input: str
    candidate: dict[str, Any]
    allowed_tools: list[str]
    max_steps: int = Field(default=4, ge=1, le=8)
    tool_name: str = ""
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    records: dict[str, Any] = Field(default_factory=dict)
    fault: Literal["none", "tool_error", "tool_timeout", "model_error", "repeat"] = (
        "none"
    )
    chain_id: str = ""
    branch: str = ""
    stimulus: dict[str, Any] = Field(default_factory=dict)


class AgentReferenceContext(StrictRecord):
    bundle_sha256: str
    target_schemas: dict[str, dict[str, Any]]
    capability_documents: list[dict[str, Any]]


def reference_context(request) -> AgentReferenceContext:
    return AgentReferenceContext(
        bundle_sha256=request.bundle_sha256,
        target_schemas=deepcopy(request.target_schemas),
        capability_documents=deepcopy(request.capability_documents),
    )


def agent_plan_for(case, request) -> AgentPlan | None:
    try:
        return _agent_plan_for(case, request)
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def _agent_plan_for(case, request) -> AgentPlan | None:
    p = case.payload
    execution = p.get("execution")
    if not isinstance(execution, dict):
        try:
            return _contract_plan(case, request)
        except (ValueError, TypeError, KeyError, AttributeError):
            return None
    scope = p.get("test_scope")
    if scope not in {"module", "link", "end_to_end"} or (
        scope == "module" and p.get("target") != "intent_router"
    ):
        return None
    if (
        execution.get("tool_profile") != "full_fixture"
        or execution.get("allowed_tools") != []
        or execution.get("user_responses") != []
        or execution.get("fault_injection") != {}
        or execution.get("adapter_input") is not None
        or execution.get("max_steps") != 4
        or execution.get("timeout_seconds") != 30.0
    ):
        return None
    try:
        raw = decode(execution["user_input"])
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    return AgentPlan(
        category="intent_module" if scope == "module" else "early_stop",
        scope=scope,
        user_input=execution["user_input"],
        candidate=raw,
        allowed_tools=[],
        chain_id="" if scope == "module" else "chain." + p["target"],
        branch="" if scope == "module" else "early_stop",
    )


def agent_checks(case, plan, row, request) -> dict[str, bool]:
    try:
        return _agent_checks(case, plan, row, request)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return {"harness_binding": False, "evidence_parse": False}


def _agent_checks(case, plan, row, request) -> dict[str, bool]:
    obs = row.observations
    events = obs.get("events", [])
    types = [e.get("event_type") for e in events if isinstance(e, dict)]
    checks = {
        "harness_binding": row.execution == plan.model_dump(mode="json")
        and row.evidence_complete
        and not row.errors,
        "execution_completed": row.status == "completed",
        "trace_complete": bool(events)
        and all(e.get("validation_status") == "VALID" for e in events),
        "model_input_bound": obs.get("model_interactions", [{}])[0].get("input")
        == plan.user_input,
        "candidate_bound": obs.get("model_interactions", [{}])[0].get("output")
        == plan.candidate,
    }
    manifest = obs.get("evidence_manifest", {})
    checks["trace_integrity"] = (
        manifest.get("status") == "COMPLETE"
        and manifest.get("execution_completed") is True
        and manifest.get("collection_closed") is True
        and manifest.get("issues") == []
        and manifest.get("attempted_count")
        == manifest.get("written_count")
        == manifest.get("last_sequence")
        == len(events)
        and [e.get("sequence") for e in events] == list(range(1, len(events) + 1))
        and len({e.get("event_id") for e in events}) == len(events)
        and len({e.get("run_id") for e in events}) == 1
        and all(e.get("trace_id") == manifest.get("trace_id") for e in events)
    )
    checks["fixture_initialized"] = complete_state(
        row.before_state
    ) and row.before_state == initial_state_for(plan)
    checks["fixture_observed"] = complete_state(row.after_state)
    result = obs.get("agent_result") or {}
    checks["calls_bound_to_result"] = row.tool_calls == result.get("tool_calls", [])
    if not plan.tool_name or plan.scope == "module":
        checks["no_handler_execution"] = (
            row.tool_calls == [] and obs.get("handler_calls") == []
        )
        checks["no_mutation"] = row.before_state == row.after_state
    elif plan.fault == "model_error":
        checks["controlled_model_failure"] = (
            not row.tool_calls
            and not obs.get("handler_calls")
            and "model_failed" in types
            and result.get("status") == "FAILED"
            and obs["model_interactions"][-1].get("error") == "REFERENCE_MODEL_FAILURE"
        )
        checks["no_mutation"] = row.before_state == row.after_state
    else:
        wanted = [{"name": plan.tool_name, "arguments": plan.tool_arguments}]
        actual = [
            {"name": c.get("name"), "arguments": c.get("arguments")}
            for c in row.tool_calls
        ]
        checks["tool_execution_bound"] = actual == wanted
        forbidden = plan.stimulus.get("action") == "request_disallowed_tool"
        checks["handler_execution_bound"] = obs.get("handler_calls") == (
            [] if forbidden else wanted
        )
        call = row.tool_calls[0] if row.tool_calls else {}
        terminals = [
            e
            for e in events
            if e.get("event_type") in {"tool_succeeded", "tool_failed", "tool_timeout"}
        ]
        requests = [e for e in events if e.get("event_type") == "tool_requested"]
        starts = [e for e in events if e.get("event_type") == "tool_started"]
        checks["tool_trace_correlated"] = (
            len(requests) == len(starts) == len(terminals) == 1
            and all(
                e["payload"].get("call_id") == call.get("call_id")
                and e["payload"].get("name") == plan.tool_name
                for e in [*requests, *starts, *terminals]
            )
            and requests[0]["payload"].get("arguments") == plan.tool_arguments
            and requests[0]["sequence"]
            < starts[0]["sequence"]
            < terminals[0]["sequence"]
        )
        if plan.fault in {"tool_error", "tool_timeout"} or forbidden:
            marker = (
                "TOOL_NOT_ALLOWED"
                if forbidden
                else (
                    "REFERENCE_TOOL_TIMEOUT"
                    if plan.fault == "tool_timeout"
                    else "REFERENCE_TOOL_FAILURE"
                )
            )
            checks["controlled_tool_failure"] = (
                call.get("status")
                == ("TIMEOUT" if plan.fault == "tool_timeout" else "FAILED")
                and marker in str(call.get("error"))
                and result.get("status") == "FAILED"
            )
            checks["no_mutation"] = row.before_state == row.after_state
        else:
            output = call.get("output") or {}
            checks["actual_tool_success"] = (
                call.get("status") == "SUCCESS"
                and output.get("success") is True
                and output.get("code") == "OK"
            )
            if plan.fault == "repeat":
                checks["bounded_execution"] = (
                    result.get("status") == "MAX_STEPS_EXCEEDED"
                    and "max_steps_exceeded" in types
                )
            else:
                import json

                checks["final_response_grounded"] = result.get(
                    "status"
                ) == "SUCCESS" and result.get("final_response") == json.dumps(
                    output, ensure_ascii=False, sort_keys=True
                )
            if plan.tool_name.startswith("query_"):
                checks["read_only"] = row.before_state == row.after_state
    checks.update(_cross_checks(plan, row, request))
    oracle = case.payload.get("oracle", {})
    module = obs.get("module_output") or {}
    if plan.category == "intent_module":
        specifications = oracle.get("evaluation", {}).get("checks", [])
        checks["assertion_suite_supported"] = {
            c.get("name") for c in specifications
        } == {
            "intent_parameters_schema_valid",
            "intent_match",
            "status_match",
            "next_action_match",
            "params_match",
            "missing_params_match",
        } and all(c.get("config") == {} for c in specifications)
        expected = oracle.get("expected_module_output") or {}
        for key in (
            "intent",
            "status",
            "next_action",
            "parameters",
            "missing_parameters",
        ):
            actual = module.get(key)
            wanted = expected.get(key)
            if (
                key == "missing_parameters"
                and isinstance(actual, list)
                and isinstance(wanted, list)
            ):
                actual, wanted = sorted(actual), sorted(wanted)
            checks[key] = type(actual) is type(wanted) and actual == wanted
        schema = request.target_schemas.get("intent." + str(module.get("intent")))
        checks["intent_parameters_schema_valid"] = (
            schema is not None
            and schema_validator(schema).is_valid(module.get("parameters"))
        )
        checks["module_boundary"] = (
            not row.tool_calls
            and "intent_decided" in types
            and obs.get("agent_result") is None
        )
    elif plan.category == "early_stop":
        result = obs.get("agent_result") or {}
        checks["assertion_suite_supported"] = (
            {c.get("name") for c in oracle.get("evaluation", {}).get("checks", [])}
            == {"status_match", "tool_not_called"}
            and all(c.get("config") == {} for c in oracle["evaluation"]["checks"])
            and oracle.get("expected_tool_calls") == []
        )
        if plan.scope == "end_to_end":
            specs = oracle.get("evaluation", {}).get("checks", [])
            expected_turns = (
                specs[0].get("config", {}).get("turns", []) if len(specs) == 1 else []
            )
            checks["assertion_suite_supported"] = (
                len(specs) == 1
                and specs[0].get("name") == "turns_match"
                and set(specs[0].get("config", {})) == {"turns"}
                and len(expected_turns) == 1
                and set(expected_turns[0]) == {"status", "tool_calls"}
            )
            observed_turns = obs.get("turns", [])
            checks["turns_match"] = len(observed_turns) == 1 and expected_turns == [
                {
                    "status": observed_turns[0]["status"],
                    "tool_calls": observed_turns[0]["tool_calls"],
                }
            ]
            goal = oracle.get("goal_state", {})
            checks["terminal_goal"] = (
                set(goal) == {"terminal_status", "forbidden_tools"}
                and result.get("status") == goal.get("terminal_status")
                and not row.tool_calls
            )
        checks["status_match"] = result.get("status") == oracle.get(
            "expected_agent_status"
        )
        checks["tool_not_called"] = not row.tool_calls and not any(
            t.startswith("tool_") for t in types
        )
        checks["terminal_event"] = (
            bool(events)
            and types[-1] == "run_finished"
            and events[-1]["payload"].get("status") == result.get("status")
        )
    else:
        from .operation_readiness import _value

        context = {
            "trace": {"event_types": types},
            "agent_result": obs.get("agent_result") or {},
            "tool_trace": {"names": [c.get("name") for c in row.tool_calls]},
        }
        assertions = oracle.get("checks", [])
        checks["assertions_present"] = bool(assertions)
        for i, c in enumerate(assertions):
            passed = False
            try:
                actual = _value(context, c["actual"])
                if set(c) == {"op", "actual", "expected"}:
                    if c["op"] == "equals":
                        passed = (
                            type(actual) is type(c["expected"])
                            and actual == c["expected"]
                        )
                    elif (
                        c["op"] == "subset"
                        and isinstance(actual, list)
                        and isinstance(c["expected"], list)
                    ):
                        passed = all(x in actual for x in c["expected"])
            except (TypeError, ValueError, KeyError, IndexError):
                pass
            checks[f"oracle_{i}"] = passed
    if plan.chain_id:
        nodes = node_evidence(plan, events, request)
        checks["ordered_chain_nodes"] = bool(nodes) and obs.get("chain_nodes") == nodes
    return checks


def _contract_plan(case, request):
    from .agent_reference_inputs import candidate
    from .operation_readiness import matching_records

    p = case.payload
    inp = p.get("input")
    if p.get("dataset_format") != "capability_contract_case" or not isinstance(
        inp, dict
    ):
        return None
    operation = inp.get("operation")
    if operation == "observe_module_event":
        if (
            set(inp) != {"operation", "stimulus"}
            or p.get("preconditions")
            != [{"kind": "controlled_module_harness", "isolated": True}]
            or not isinstance(inp["stimulus"], dict)
        ):
            return None
        stimulus = inp["stimulus"]
        action = stimulus.get("action")
        text = "查询用户 ID 1 的信息。"
        raw = decode(text)
        scope, name, fault, maximum = "link", "query_user_info", "none", 4
        allowed = [name]
        if action in {"start_single_run", "complete_single_run", "route_single_input"}:
            if set(stimulus) != {"action", "user_input"}:
                return None
            text = stimulus["user_input"]
            raw = decode(text)
            scope = "module" if action == "route_single_input" else "link"
            name = "" if scope == "module" or not raw["parameters"] else name
        elif action == "validate_candidate":
            if set(stimulus) != {"action", "intent", "parameters"} or stimulus[
                "intent"
            ] not in {"query_user", "query_gift"}:
                return None
            raw = candidate(stimulus["intent"], deepcopy(stimulus["parameters"]))
            text = (
                "查询用户 ID " + str(raw["parameters"].get("user_id", 1)) + " 的信息。"
                if raw["intent"] == "query_user"
                else "查询礼物 ID 1，礼物名称 x。"
            )
            scope, name = "module", ""
        elif action == "model_returns_structured_candidate":
            if stimulus != {"action": action, "intent": "query_user"}:
                return None
            text, raw = "请查询用户信息。", candidate("query_user", {})
            scope, name = "module", ""
        elif action == "model_raises_exception":
            if stimulus != {"action": action, "exception_type": "RuntimeError"}:
                return None
            fault = "model_error"
        elif action == "request_disallowed_tool":
            if stimulus != {"action": action, "tool_name": name, "allowed_tools": []}:
                return None
            allowed = []
        elif action == "model_repeats_tool_request":
            if stimulus != {"action": action, "max_steps": 1, "requests": 2}:
                return None
            fault, maximum = "repeat", 1
        elif action in {
            "complete_read_run",
            "model_requests_registered_tool",
            "invoke_registered_tool",
        }:
            if stimulus.get("tool_name") != name or set(stimulus) - {
                "action",
                "tool_name",
                "handler",
            }:
                return None
            handler = stimulus.get("handler")
            if handler not in {
                None,
                "returns_declared_OK",
                "raises_exception",
                "raises_timeout",
            }:
                return None
            fault = {
                "raises_exception": "tool_error",
                "raises_timeout": "tool_timeout",
            }.get(handler, "none")
        else:
            return None
        if scope == "module" or not name:
            allowed = []
        category, chain_id, branch = "module_event", "", ""
    elif operation == "agent_run":
        if p.get("preconditions") != [
            {
                "kind": "isolated_fixture",
                "required": (
                    "Arrange matching records for the selected arguments; "
                    "never assume production IDs."
                ),
            }
        ] or set(inp) - {
            "operation",
            "user_input",
            "intent_id",
            "tool_name",
            "branch",
            "controlled_fault",
        }:
            return None
        text, branch = inp["user_input"], inp["branch"]
        raw = decode(text)
        name = INTENT_TO_TOOL.get(raw["intent"], "")
        if (
            not name
            or inp.get("intent_id") != "intent." + raw["intent"]
            or inp.get("tool_name") != name
        ):
            return None
        if branch == "error" and inp.get("controlled_fault") == {
            "at": "tool_handler",
            "behavior": "raise_exception",
        }:
            fault = "tool_error"
        elif branch == "normal" and "controlled_fault" not in inp:
            fault = "none"
        else:
            return None
        category, chain_id, maximum = "agent_chain", p["target_id"], 4
        scope = "end_to_end" if p["layer"] == "end_to_end" else "link"
        allowed, stimulus = [name], {}
        if not any(
            d.get("snapshot_id") == chain_id and d.get("snapshot_type") == "chain"
            for d in request.capability_documents
        ):
            return None
    else:
        return None
    arguments, records = {}, {}
    if name:
        schema = request.target_schemas["tool." + name]["parameters"]
        arguments = {k: None for k in schema["properties"]}
        arguments.update({k: v for k, v in raw["parameters"].items() if k in arguments})
        records = (
            {} if name == "prepare_resource" else matching_records(name, arguments)
        )
    return AgentPlan(
        category=category,
        scope=scope,
        user_input=text,
        candidate=raw,
        allowed_tools=allowed,
        tool_name=name,
        tool_arguments=arguments,
        records=records,
        max_steps=maximum,
        fault=fault,
        chain_id=chain_id,
        branch=branch,
        stimulus=stimulus,
    )


def node_evidence(plan, events, request):
    if not plan.chain_id:
        return []
    graph = next(
        (
            d
            for d in request.capability_documents
            if d.get("snapshot_id") == plan.chain_id
        ),
        {},
    )
    mapping = {
        "intent_validation": {"intent_contract_validated"},
        "tool_execution": {"tool_started"},
        "bounded_execution": {
            "tool_succeeded",
            "tool_failed",
            "tool_timeout",
            "max_steps_exceeded",
        },
        "result_emission": {"run_finished"},
    }
    wanted = (
        ["intent_validation"]
        if plan.branch == "early_stop"
        else [n["node_id"] for n in graph.get("nodes", [])]
    )
    nodes, previous = [], -1
    for name in wanted:
        found = next(
            (
                (i, e)
                for i, e in enumerate(events)
                if i > previous and e.get("event_type") in mapping.get(name, set())
            ),
            None,
        )
        if found is None:
            return []
        previous, event = found
        nodes.append(
            {
                "node_id": name,
                "event_id": event["event_id"],
                "sequence": event["sequence"],
            }
        )
    return nodes


def binding_for(case, request):
    from .operation_readiness import plan_for

    operation = plan_for(case, request.target_schemas)
    if operation is not None:
        return operation
    return (
        agent_plan_for(case, request)
        if request.schema_version == "builder-full-readiness-v3"
        else None
    )


def category_for(case):
    p = case.payload
    if p.get("input", {}).get("operation") == "validate_arguments":
        return "schema_validation"
    return (
        "tool_behavior"
        if p.get("target_id", "").startswith("tool.")
        else "agent_behavior"
    )


def _cross_checks(plan, row, request):
    obs = row.observations
    result = obs.get("agent_result") or {}
    events = obs["events"]
    checks = {}
    if result:
        finished = [e for e in events if e["event_type"] == "run_finished"]
        checks["run_result_correlated"] = (
            len(finished) == 1
            and finished[0] == events[-1]
            and finished[0]["payload"].get("status") == result.get("status")
            and all(e["run_id"] == result.get("run_id") for e in events)
            and result.get("trace_id") == obs["evidence_manifest"].get("trace_id")
            and obs.get("turns") == [result]
        )
        final = [e for e in events if e["event_type"] == "final_response_generated"]
        checks["final_event_correlated"] = (
            (
                len(final) == 1
                and final[0]["payload"].get("response") == result.get("final_response")
            )
            if result.get("status") == "SUCCESS"
            else not final
        )
        intent = result.get("intent_result", {})
    else:
        intent = obs.get("module_output") or {}
    decisions = [e for e in events if e["event_type"] == "intent_decided"]
    checks["intent_event_correlated"] = len(decisions) == 1 and all(
        decisions[0]["payload"].get(key) == intent.get(key)
        for key in ("intent", "status", "next_action", "missing_parameters")
    )
    for index, call in enumerate(row.tool_calls):
        terminal = [
            e
            for e in events
            if e["event_type"] in {"tool_succeeded", "tool_failed", "tool_timeout"}
            and e["payload"].get("call_id") == call.get("call_id")
        ]
        event_type = {
            "SUCCESS": "tool_succeeded",
            "FAILED": "tool_failed",
            "TIMEOUT": "tool_timeout",
        }.get(call.get("status"))
        checks[f"tool_terminal_{index}"] = (
            len(terminal) == 1
            and terminal[0]["event_type"] == event_type
            and (
                terminal[0]["payload"].get("output") == call.get("output")
                if event_type == "tool_succeeded"
                else terminal[0]["payload"].get("error") == call.get("error")
            )
        )
    interactions = obs["model_interactions"]
    checks["model_classification_record"] = (
        bool(interactions) and interactions[0].get("method") == "classify_intent"
    )
    has_loop = bool(plan.tool_name) and plan.scope != "module"
    needs_final = (
        has_loop
        and plan.fault == "none"
        and plan.stimulus.get("action") != "request_disallowed_tool"
    )
    count = 0 if not has_loop else (2 if needs_final else 1)
    steps = interactions[1:]
    checks["model_interactions_complete"] = len(steps) == count
    expected_schemas = []
    for tool in sorted(plan.allowed_tools):
        schema = request.target_schemas["tool." + tool]
        expected_schemas.append(
            {key: schema[key] for key in ("name", "description", "parameters")}
        )
    for i, step in enumerate(steps, 1):
        inp = step.get("input", {})
        schemas = [
            {key: item.get(key) for key in ("name", "description", "parameters")}
            for item in inp.get("tool_schemas", [])
        ]
        previous = [
            {key: call[key] for key in ("call_id", "name", "output")}
            for call in row.tool_calls[: i - 1]
        ]
        passed = (
            step.get("method") == "next_tool_step"
            and inp.get("step") == i
            and inp.get("user_input") == plan.user_input
            and inp.get("intent_result") == intent
            and inp.get("tool_outputs") == previous
            and schemas == expected_schemas
        )
        if plan.fault == "model_error":
            passed = (
                passed
                and step.get("error") == "REFERENCE_MODEL_FAILURE"
                and "output" not in step
            )
        elif i == 1:
            call = row.tool_calls[0] if row.tool_calls else {}
            passed = passed and step.get("output") == {
                "type": "function_call",
                "call_id": call.get("call_id"),
                "name": call.get("name"),
                "arguments": call.get("arguments"),
            }
        else:
            passed = passed and step.get("output") == {
                "type": "message",
                "content": result.get("final_response"),
            }
        checks[f"model_step_{i}"] = passed
    return checks
