"""Concrete schema/tool contracts and explicitly blocked semantic obligations."""

from copy import deepcopy

from jsonschema import Draft202012Validator

from .inventory import pointer_value
from .models import CompiledCase, ContractCase, CoverageSlot, FullInventory


def sample(schema, root=None, name=""):
    root = root or schema
    if "$ref" in schema:
        return sample(pointer_value(root, schema["$ref"][1:]), root, name)
    if "enum" in schema:
        return schema["enum"][0]
    if "anyOf" in schema:
        return sample(
            next(
                (x for x in schema["anyOf"] if x.get("type") != "null"),
                schema["anyOf"][0],
            ),
            root,
            name,
        )
    typ = schema.get("type")
    if typ == "null":
        return None
    if typ == "boolean":
        return True
    if typ in ("integer", "number"):
        return max(1, schema.get("minimum", 1), schema.get("exclusiveMinimum", 0) + 1)
    if typ == "array":
        return [sample(schema.get("items", {}), root, name)] * max(
            1, schema.get("minItems", 1)
        )
    if typ == "object" or "properties" in schema:
        return {k: sample(v, root, k) for k, v in schema.get("properties", {}).items()}
    if name == "phone" or schema.get("pattern") == "^[0-9]{11}$":
        return "15000000200"
    if name == "email" or "@" in schema.get("pattern", ""):
        return "fixture@example.test"
    if name == "environment":
        return "test"
    if name == "request_id":
        return "fixture-request-001"
    return "x" * max(1, schema.get("minLength", 1))


def base_arguments(d):
    schema = d.get("function_schema", {}).get(
        "parameters", d.get("parameters_schema", {})
    )
    args = sample(schema)
    rules = d.get("parameter_semantics", {}).get("rules", d.get("semantic_rules", {}))
    modes = []
    for key in ("query_modes", "user_selection_modes", "gift_selection_modes"):
        if key in rules:
            modes.append(rules[key])
    if d.get("tool_name") == "query_user_info":
        modes.append(["user_id", "room_id", "email", "phone"])
    for group in modes:
        for name in group[1:]:
            args[name] = None
    return args


def mutated_arguments(d, name, dimension):
    schema = d.get("function_schema", {}).get(
        "parameters", d.get("parameters_schema", {})
    )
    args = base_arguments(d)
    prop = schema["properties"][name]
    nonnull = next(
        (v for v in prop.get("anyOf", [prop]) if v.get("type") != "null"), prop
    )
    if dimension == "omitted":
        args.pop(name, None)
    elif dimension == "wrong_type":
        args[name] = {"unexpected": "object"} if nonnull.get("type") != "object" else []
    elif dimension in ("boundary", "outside_boundary"):
        invalid = dimension == "outside_boundary"
        if "maximum" in nonnull:
            args[name] = nonnull["maximum"] + int(invalid)
        elif "minimum" in nonnull:
            args[name] = nonnull["minimum"] - int(invalid)
        elif "exclusiveMinimum" in nonnull:
            args[name] = nonnull["exclusiveMinimum"] + (0 if invalid else 1)
        elif nonnull.get("type") == "array":
            args[name] = [] if invalid else sample(nonnull, schema, name)
        elif "pattern" in nonnull:
            args[name] = "bad-value" if invalid else sample(nonnull, schema, name)
        else:
            args[name] = "" if invalid else sample(nonnull, schema, name)
    else:
        # This case tests the parameter schema, not business mode cardinality.
        args[name] = sample(prop, schema, name)
    return args, Draft202012Validator(schema).is_valid(args)


def _check(op, actual, expected):
    return {"op": op, "actual": actual, "expected": expected}


def compile_contract_cases(
    inv: FullInventory, slots: list[CoverageSlot]
) -> list[CompiledCase]:
    result = []
    for s in slots:
        if s.case_kind in {"intent_case", "chain_case"}:
            continue
        ref = s.source_refs[0]
        d = inv.artifacts[s.target_id]["payload"]
        declared = pointer_value(d, ref.pointer)
        schema = d.get("function_schema", {}).get(
            "parameters", d.get("parameters_schema", {})
        )
        inp, oracle, pre = {}, {"checks": []}, []
        readiness = "needs_runner"
        requirements = [
            (
                "Implement the named observation interface;"
                " do not infer PASS from this definition."
            )
        ]
        if s.support_status != "supported":
            readiness = "blocked"
            inp = {"operation": "unsupported_capability", "capability": s.dimension}
            oracle["declared_status"] = s.support_status
        elif s.case_kind == "parameter":
            name = ref.pointer.rsplit("/", 1)[1].replace("~1", "/").replace("~0", "~")
            args, valid = mutated_arguments(d, name, s.dimension)
            inp = {
                "operation": "validate_arguments",
                "arguments": args,
                "parameter": name,
                "dimension": s.dimension,
            }
            oracle.update(
                arguments_schema_valid=valid,
                checks=[_check("schema_valid", "input.arguments", valid)],
            )
            pre = [
                {
                    "kind": "validation_only",
                    "invoke_handler": False,
                    "note": (
                        "JSON Schema acceptance only; business mode"
                        " validation is separate."
                    ),
                }
            ]
            requirements = [
                "Argument-schema validation adapter; no handler invocation."
            ]
        elif s.case_kind == "schema_constraint":
            # Contract inspection is not credited as runtime behavior coverage.
            inp = {"operation": "inspect_declared_constraint", "pointer": ref.pointer}
            oracle = {
                "checks": [_check("equals", "contract" + ref.pointer, declared)],
                "coverage_limit": "static contract assertion, not a behavior test",
            }
            requirements = ["Source-bound JSON Pointer reader."]
        elif s.case_kind == "tool_result":
            args = base_arguments(d)
            code = s.dimension
            inp = {
                "operation": "invoke_tool",
                "tool_name": d["tool_name"],
                "arguments": args,
            }
            pre = [branch_setup(d, code, declared["data_schema"])]
            if code == "ENVIRONMENT_UNSUPPORTED":
                inp["arguments"]["environment"] = "non-test"
            elif code == "LIMIT_EXCEEDED":
                inp["arguments"]["count"] = (
                    d["parameter_semantics"]["rules"]["maximum_fixture_count"] + 1
                )
            elif code == "NOT_FOUND" and d["tool_name"] == "query_gift_info":
                inp["arguments"]["gift_id"] = None
                inp["arguments"]["gift_ids"] = [1]
            elif code == "DUPLICATE_GIFT":
                inp["arguments"]["gift_id"] = None
                inp["arguments"]["gift_ids"] = [1, 1]
            oracle = {
                "checks": [
                    _check("equals", "tool_result.code", code),
                    _check("schema_valid", "tool_result.data", declared["data_schema"]),
                ],
                "declared_terminal_status": declared["terminal_status"],
            }
            if d.get("requires_confirmation") and code != "CONFIRMATION_REQUIRED":
                pre.append({"kind": "external_owner_authorization", "attempts": 1})
            requirements = [
                "Direct fixture tool runner",
                "Branch-specific fixture initialization",
                "Map actual tool envelope to code/data without guessing.",
            ]
        elif s.case_kind == "module_event" and declared in EVENT_STIMULI:
            stimulus = deepcopy(EVENT_STIMULI[declared])
            if s.target_id == "module.execution_guard":
                stimulus = {
                    "action": "request_disallowed_tool",
                    "tool_name": "query_user_info",
                    "allowed_tools": [],
                }
            inp = {"operation": "observe_module_event", "stimulus": stimulus}
            oracle["checks"] = [_check("subset", "trace.event_types", [declared])]
            pre = [{"kind": "controlled_module_harness", "isolated": True}]
            requirements = [
                (
                    "Bind stimulus to explicit module test inte"
                    "rface; native run_module only calls intent"
                    " router."
                )
            ]
        elif s.case_kind == "tool_rule" and s.dimension in {
            "query_modes",
            "query_mode_cardinality",
            "user_selection_modes",
            "gift_selection_modes",
            "selection_cardinality",
        }:
            rules = d["parameter_semantics"]["rules"]
            group = rules.get(s.dimension)
            if not isinstance(group, list):
                group = rules.get("query_modes", rules.get("user_selection_modes", []))
            args = base_arguments(d)
            for name in group:
                args[name] = sample(schema["properties"][name], schema, name)
            inp = {
                "operation": "validate_selection_modes",
                "arguments": args,
                "modes": group,
            }
            oracle = {
                "business_arguments_valid": False,
                "checks": [_check("equals", "argument_validator.accepted", False)],
            }
            pre = [{"kind": "validation_only", "invoke_handler": False}]
        elif s.case_kind == "tool_rule" and s.dimension in {
            "default_num",
            "default_duration_days",
        }:
            field = s.dimension.removeprefix("default_")
            args = base_arguments(d)
            args[field] = None
            inp = {
                "operation": "invoke_tool",
                "tool_name": d["tool_name"],
                "arguments": args,
            }
            pre = [
                branch_setup(
                    d,
                    "OK",
                    d["result_protocols"]["declared_results"]["OK"]["data_schema"],
                )
            ]
            oracle["checks"] = [
                _check("equals", "tool_result.data.grants[0]." + field, declared)
            ]
        elif s.case_kind == "tool_rule" and s.dimension == "duplicate_users":
            args = base_arguments(d)
            args.update(user_id=None, user_ids=[1, 1])
            inp = {
                "operation": "invoke_tool",
                "tool_name": d["tool_name"],
                "arguments": args,
            }
            pre = [
                branch_setup(
                    d,
                    "OK",
                    d["result_protocols"]["declared_results"]["OK"]["data_schema"],
                )
            ]
            oracle["checks"] = [_check("count", "tool_result.data.grants", 1)]
        elif s.case_kind == "tool_rule" and s.dimension == "mutation":
            args = base_arguments(d)
            args.update(user_id=None, user_ids=[1, 99999])
            inp = {
                "operation": "invoke_tool",
                "tool_name": d["tool_name"],
                "arguments": args,
            }
            pre = [
                branch_setup(
                    d,
                    "OK",
                    d["result_protocols"]["declared_results"]["OK"]["data_schema"],
                )
            ]
            oracle["checks"] = [
                _check("equals", "tool_result.code", "NOT_FOUND"),
                _check("unchanged", "fixture.after", {"ref": "fixture.before"}),
            ]
        elif s.case_kind == "tool_rule" and s.dimension == "idempotency_rules":
            mode = declared.get("mode")
            args = base_arguments(d)
            if mode == "REQUEST_ID_WITHIN_FIXTURE_INSTANCE":
                changed = {**args, "count": args["count"] + 1}
                inp = {
                    "operation": "idempotency_sequence",
                    "tool_name": d["tool_name"],
                    "steps": [
                        {"arguments": args},
                        {"arguments": deepcopy(args)},
                        {"arguments": changed},
                    ],
                }
                pre = [{"kind": "fresh_fixture", "share_instance_within_case": True}]
                oracle["checks"] = [
                    _check("equals", "step[1].resources", {"ref": "step[0].resources"}),
                    _check("equals", "step[2].code", "CONFLICT"),
                    _check(
                        "unchanged",
                        "state.after_step[2]",
                        {"ref": "state.after_step[1]"},
                    ),
                ]
            elif mode == "READ_ONLY":
                inp = {
                    "operation": "invoke_tool",
                    "tool_name": d["tool_name"],
                    "arguments": args,
                }
                pre = [
                    {
                        "kind": "fixture_setup",
                        "required": "Provide matching isolated records.",
                    }
                ]
                oracle["checks"] = [
                    _check("unchanged", "fixture.after", {"ref": "fixture.before"})
                ]
            else:
                readiness = "blocked"
                inp = {"operation": "idempotency_contract", "mode": mode}
                oracle["unresolved"] = (
                    "NOT_IDEMPOTENT does not define a determini"
                    "stic duplicate-call result."
                )
        elif s.case_kind == "tool_rule" and s.dimension == "confirmation":
            args = base_arguments(d)
            inp = {
                "operation": "authorization_sequence",
                "tool_name": d["tool_name"],
                "steps": [
                    {"action": "owner_authorize_one_attempt"},
                    {"action": "invoke", "arguments": args},
                    {"action": "invoke", "arguments": deepcopy(args)},
                ],
            }
            pre = [
                {
                    "kind": "fixture_setup",
                    "required": "All selected IDs exist; no authorization initially.",
                }
            ]
            oracle["checks"] = [
                _check("equals", "step[1].code", "OK"),
                _check("equals", "step[2].code", "CONFIRMATION_REQUIRED"),
                _check(
                    "unchanged", "state.after_step[2]", {"ref": "state.after_step[1]"}
                ),
            ]
        else:
            # Broad module schemas and semantic strings need explicit input/runner
            # bindings. Retain their exact obligation, never invent executable tests.
            readiness = "blocked"
            inp = {
                "operation": "contract_obligation",
                "target": s.target_id,
                "dimension": s.dimension,
            }
            oracle = {
                "declared_requirement": declared,
                "checks": [],
                "unresolved": (
                    "Concrete stimulus and executable predicate"
                    " require a contract-specific binding."
                ),
            }
        ids = list(s.blocker_ids)
        if readiness == "blocked" and not ids:
            ids = ["BINDING-" + s.slot_id]
        case = ContractCase(
            case_id="C-" + s.slot_id,
            slot_id=s.slot_id,
            target_id=s.target_id,
            layer=s.layer,
            preconditions=pre,
            input=inp,
            oracle=oracle,
            source_refs=s.source_refs,
            runner_requirements=requirements,
        )
        result.append(
            CompiledCase(
                slot_id=s.slot_id,
                dataset_format="capability_contract_case",
                payload=case.model_dump(mode="json"),
                execution_readiness=readiness,
                coverage_mode="contract",
                blocker_ids=ids,
            )
        )
    return result


EVENT_STIMULI = {
    "run_started": {
        "action": "start_single_run",
        "user_input": "查询用户 ID 1 的信息。",
    },
    "run_finished": {"action": "complete_single_run", "user_input": "请查询用户信息。"},
    "intent_candidate_received": {
        "action": "model_returns_structured_candidate",
        "intent": "query_user",
    },
    "model_failed": {
        "action": "model_raises_exception",
        "exception_type": "RuntimeError",
    },
    "intent_decided": {
        "action": "route_single_input",
        "user_input": "查询用户 ID 1 的信息。",
    },
    "intent_contract_validated": {
        "action": "validate_candidate",
        "intent": "query_user",
        "parameters": {"user_id": 1},
    },
    "intent_parameter_normalized": {
        "action": "validate_candidate",
        "intent": "query_user",
        "parameters": {"user_id": "1"},
    },
    "intent_parameter_validation_failed": {
        "action": "validate_candidate",
        "intent": "query_user",
        "parameters": {"user_id": 0},
    },
    "intent_semantic_constraint_failed": {
        "action": "validate_candidate",
        "intent": "query_gift",
        "parameters": {"gift_id": 1, "gift_name": "x"},
    },
    "tool_requested": {
        "action": "model_requests_registered_tool",
        "tool_name": "query_user_info",
    },
    "tool_started": {
        "action": "invoke_registered_tool",
        "tool_name": "query_user_info",
    },
    "tool_succeeded": {
        "action": "invoke_registered_tool",
        "tool_name": "query_user_info",
        "handler": "returns_declared_OK",
    },
    "tool_failed": {
        "action": "invoke_registered_tool",
        "tool_name": "query_user_info",
        "handler": "raises_exception",
    },
    "tool_timeout": {
        "action": "invoke_registered_tool",
        "tool_name": "query_user_info",
        "handler": "raises_timeout",
    },
    "max_steps_exceeded": {
        "action": "model_repeats_tool_request",
        "max_steps": 1,
        "requests": 2,
    },
    "final_response_generated": {
        "action": "complete_read_run",
        "tool_name": "query_user_info",
    },
}


def branch_setup(d, code, data_schema):
    records = sample(data_schema)
    setup = {
        "kind": "fixture_setup",
        "records": records,
        "result_branch": code,
        "fresh_instance": True,
    }
    if code in {"EMPTY", "NOT_FOUND"}:
        setup["records"] = {"users": [], "gifts": [], "pools": [], "resources": []}
    if d["tool_name"] == "add_gift_to_backpack":
        setup["records"] = {
            "users": [{"user_id": 1}],
            "gifts": [{"gift_id": 1}],
            "grants": [],
        }
        setup["owner_authorized_attempts"] = 0 if code == "CONFIRMATION_REQUIRED" else 1
        if code == "NOT_FOUND":
            setup["records"]["users"] = []
    if code == "CONFLICT":
        args = base_arguments(d)
        setup["steps"] = [
            {
                "invoke": d["tool_name"],
                "arguments": {**args, "count": args["count"] + 1},
            }
        ]
    return setup
