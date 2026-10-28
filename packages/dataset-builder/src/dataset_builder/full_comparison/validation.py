"""Bounded source-derived acceptance, distinct from actual Agent execution."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy

from jsonschema import Draft202012Validator

from dataset_builder.full_generation.contract_cases import EVENT_STIMULI, sample

from .plan import canonical
from .protocol import FullCandidate


def fingerprint(value):
    # Preserve @, minus signs, whitespace inside strings, numbers and JSON types.
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def schema_for(doc):
    return doc.get("function_schema", {}).get(
        "parameters", doc.get("parameters_schema", {})
    )


def expect(condition, message):
    if not condition:
        raise ValueError(message)


def check(op, actual, expected):
    return {"op": op, "actual": actual, "expected": expected}


def checks_equal(oracle, checks):
    expect(
        canonical(oracle.get("checks")) == canonical(checks),
        "oracle checks do not match source-bound obligations",
    )


def _hidden_answer(value):
    if isinstance(value, dict):
        if any(
            re.search(r"oracle|expected|assertion|预期|答案", k, re.I) for k in value
        ):
            return True
        return any(_hidden_answer(v) for v in value.values())
    if isinstance(value, list):
        return any(_hidden_answer(v) for v in value)
    return False


def _parameter(c, s, doc):
    inp = c["input"]
    oracle = c["oracle"]
    schema = schema_for(doc)
    name = s["parameter"]
    dim = s["dimension"]
    prop = schema["properties"][name]
    expect(inp.get("operation") == "validate_arguments", "wrong parameter operation")
    expect(
        inp.get("parameter") == name and inp.get("dimension") == dim,
        "wrong selected parameter/dimension",
    )
    args = inp["arguments"]
    expect(isinstance(args, dict), "arguments must be object")
    repaired = deepcopy(args)
    repaired[name] = sample(prop, schema, name)
    expect(
        Draft202012Validator(schema).is_valid(repaired),
        "another parameter violates the schema",
    )
    validator = Draft202012Validator({**prop, "$defs": schema.get("$defs", {})})
    if dim == "omitted":
        expect(name not in args, "omitted parameter is present")
    else:
        expect(name in args, "selected parameter absent")
        value = args[name]
        variants = prop.get("anyOf", [prop])
        nonnull = next((v for v in variants if v.get("type") != "null"), prop)
        valid = validator.is_valid(value)
        if dim == "wrong_type":
            allowed = {v.get("type") for v in variants}
            typ = (
                "null"
                if value is None
                else "boolean"
                if isinstance(value, bool)
                else "integer"
                if isinstance(value, int)
                else "number"
                if isinstance(value, float)
                else "string"
                if isinstance(value, str)
                else "array"
                if isinstance(value, list)
                else "object"
            )
            expect(
                not valid
                and typ not in allowed
                and not (typ == "integer" and "number" in allowed),
                "value is not a wrong-type example",
            )
        elif dim == "outside_boundary":
            expect(
                not valid and value is not None,
                "outside-boundary value must violate its declared constraint",
            )
            typ = nonnull.get("type")
            expect(
                (typ in {"integer", "number"} and type(value) in {int, float})
                or (typ == "string" and isinstance(value, str))
                or (typ == "array" and isinstance(value, list)),
                "outside-boundary must retain the declared type",
            )
        else:
            expect(
                valid and value is not None,
                "valid/boundary parameter must be non-null and valid",
            )
            if dim == "boundary":
                if "maximum" in nonnull:
                    expect(
                        value == nonnull["maximum"], "not the selected maximum boundary"
                    )
                elif "minimum" in nonnull:
                    expect(
                        value == nonnull["minimum"], "not the selected minimum boundary"
                    )
                elif "exclusiveMinimum" in nonnull:
                    expect(
                        value == nonnull["exclusiveMinimum"] + 1,
                        "not the first valid integer boundary",
                    )
                elif nonnull.get("type") == "array":
                    expect(
                        len(value) == max(1, nonnull.get("minItems", 1)),
                        "not minimum nonempty array boundary",
                    )
                elif "minLength" in nonnull:
                    expect(
                        len(value) == nonnull["minLength"], "not minimum string length"
                    )
                elif name == "phone":
                    expect(
                        bool(re.fullmatch("[0-9]{11}", value)),
                        "phone must be eleven ASCII digits",
                    )
    actual = Draft202012Validator(schema).is_valid(args)
    expect(
        type(oracle.get("arguments_schema_valid")) is bool
        and oracle["arguments_schema_valid"] == actual,
        "schema-valid oracle contradicts input",
    )
    checks_equal(oracle, [check("schema_valid", "input.arguments", actual)])
    expect(
        all(p.get("invoke_handler") is not True for p in c["preconditions"]),
        "schema checks must not invoke handler",
    )


def _grounded(text, value):
    if isinstance(value, dict):
        return all(_grounded(text, x) for x in value.values())
    if isinstance(value, list):
        return all(_grounded(text, x) for x in value)
    if value is None:
        return True
    token = re.escape(str(value))
    return bool(
        re.search(r"(?<![A-Za-z0-9_@.+-])" + token + r"(?![A-Za-z0-9_@.+-])", text)
    )


def _intent(c, s, doc):
    text = c["input"].get("user_input")
    expect(isinstance(text, str) and bool(text.strip()), "intent input missing")
    out = c["oracle"]["expected_module_output"]
    expect(
        set(out)
        == {"intent", "status", "next_action", "parameters", "missing_parameters"},
        "intent oracle fields mismatch",
    )
    expect(out["intent"] == s["target_id"].removeprefix("intent."), "intent mismatch")
    rule = doc["decision_rules"]["complete"]
    expect(
        out["status"] == rule["status"] and out["next_action"] == rule["next_action"],
        "decision/action mismatch",
    )
    expect(
        out["missing_parameters"] == [],
        "complete/rejected intent must not invent missing parameters",
    )
    params = out["parameters"]
    expect(
        Draft202012Validator(doc["parameters_schema"]).is_valid(params),
        "intent parameter schema mismatch",
    )
    expect(
        all(_grounded(text, v) for v in params.values()),
        "parameter value is not grounded in input",
    )
    if out["intent"] == "unsupported":
        expect(params == {}, "unsupported intent parameters must be empty")
    else:
        expect(
            any(v is not None for v in params.values()),
            "complete intent needs identifying parameters",
        )
    _selection(params, doc, allow_missing_optional=True)


def _selection(args, doc, allow_missing_optional=False):
    name = doc.get("tool_name", doc.get("capability_id"))
    rules = doc.get("parameter_semantics", {}).get(
        "rules", doc.get("semantic_rules", {})
    )
    for key in ("query_modes", "user_selection_modes", "gift_selection_modes"):
        group = rules.get(key)
        if isinstance(group, list):
            expect(
                sum(args.get(k) is not None for k in group) == 1,
                "selection modes require exactly one non-null field",
            )
    if name in {"query_user", "query_user_info"}:
        expect(
            any(
                args.get(k) is not None
                for k in ["user_id", "room_id", "email", "phone"]
            ),
            "query_user needs at least one condition",
        )
    if (
        name
        in {
            "query_information",
            "prepare_resource",
            "add_backpack_gift",
            "add_gift_to_backpack",
        }
        and allow_missing_optional
    ):
        required = {
            "query_information": ["resource_type", "environment"],
            "prepare_resource": ["resource_type", "environment", "count", "request_id"],
            "add_backpack_gift": ["environment"],
            "add_gift_to_backpack": [],
        }[name]
        expect(
            all(args.get(k) is not None for k in required),
            "complete intent lacks a required business field",
        )


def _tool_input(c, doc):
    inp = c["input"]
    expect(inp.get("tool_name") == doc["tool_name"], "wrong tool")
    args = inp["arguments"]
    expect(
        Draft202012Validator(schema_for(doc)).is_valid(args),
        "tool argument schema mismatch",
    )
    return args


def _tool_result(c, s, doc, declared):
    expect(c["input"].get("operation") == "invoke_tool", "wrong tool-result operation")
    args = _tool_input(c, doc)
    code = s["dimension"]
    _selection(args, doc)
    checks_equal(
        c["oracle"],
        [
            check("equals", "tool_result.code", code),
            check("schema_valid", "tool_result.data", declared["data_schema"]),
        ],
    )
    expect(
        c["oracle"].get("declared_terminal_status") == declared["terminal_status"],
        "terminal status differs from declared branch",
    )
    _fixture_branch(c, args, doc, code)


def _fixture_branch(c, args, doc, code, authorization=None):
    fixtures = [p for p in c["preconditions"] if p.get("kind") == "fixture_setup"]
    expect(len(fixtures) == 1, "exactly one concrete fixture_setup required")
    fixture = fixtures[0]
    expect(fixture.get("fresh_instance") is True, "fresh isolated fixture required")
    records = fixture.get("records")
    expect(isinstance(records, dict), "explicit fixture records required")
    name = doc["tool_name"]
    rules = doc["parameter_semantics"]["rules"]
    _selection(args, doc)
    if doc.get("requires_confirmation"):
        authorized = sum(
            p.get("owner_authorized_attempts", 0) for p in c["preconditions"]
        )
        expected_authorization = (
            authorization
            if authorization is not None
            else (0 if code == "CONFIRMATION_REQUIRED" else 1)
        )
        expect(
            authorized == expected_authorization,
            "fixture owner authorization differs from branch",
        )
    if rules.get("environment") == "test only":
        expect(
            (args.get("environment") == "test") == (code != "ENVIRONMENT_UNSUPPORTED"),
            "environment contradicts selected branch",
        )
    if name == "prepare_resource":
        maximum = rules["maximum_fixture_count"]
        expect(
            (args["count"] > maximum) == (code == "LIMIT_EXCEEDED"),
            "fixture count contradicts selected branch",
        )
        prior = fixture.get("prior_calls", [])
        if code == "CONFLICT":
            expect(len(prior) == 1, "conflict requires a prior successful invocation")
            old = prior[0]
            expect(old.get("tool_name") == name, "prior invocation tool mismatch")
            old_args = old.get("arguments")
            expect(
                Draft202012Validator(schema_for(doc)).is_valid(old_args),
                "prior invocation arguments invalid",
            )
            expect(
                old_args["environment"] == "test" and old_args["count"] <= maximum,
                "prior invocation cannot succeed",
            )
            expect(
                old_args["request_id"] == args["request_id"] and old_args != args,
                "prior invocation must reuse request id with different arguments",
            )
        else:
            expect(not prior, "use fresh request state for non-conflict branch")
        return
    if name == "add_gift_to_backpack":
        users = records.get("users")
        gifts = records.get("gifts")
        expect(
            isinstance(users, list) and isinstance(gifts, list),
            "explicit users and gifts required",
        )
        user_ids = args.get("user_ids") or [args.get("user_id")]
        gift_ids = args.get("gift_ids") or (
            [args["gift_id"]]
            if args.get("gift_id")
            else [g["gift_id"] for g in args.get("gift_nums", [])]
        )
        duplicate = len(gift_ids) != len(set(gift_ids))
        expect(
            duplicate == (code == "DUPLICATE_GIFT"), "gift duplicates contradict branch"
        )
        exists = all(x in {r.get("user_id") for r in users} for x in user_ids) and all(
            x in {r.get("gift_id") for r in gifts} for x in gift_ids
        )
        if code in {"OK", "NOT_FOUND"}:
            expect(exists == (code == "OK"), "fixture references contradict branch")
        return
    collection = {
        "query_user_info": "users",
        "query_gift_info": "gifts",
        "query_pool_config": "pools",
        "query_information": "resources",
    }[name]
    rows = records.get(collection)
    expect(
        isinstance(rows, list), "explicit fixture record list required: " + collection
    )
    props = doc["result_protocols"]["declared_results"]["OK"]["data_schema"][
        "properties"
    ]
    record_schema = (
        props["user"] if name == "query_user_info" else props[collection]["items"]
    )
    expect(
        all(Draft202012Validator(record_schema).is_valid(r) for r in rows),
        "fixture record violates source schema",
    )
    if name == "query_user_info":
        matches = [
            r
            for r in rows
            if all(r.get(k) == v for k, v in args.items() if v is not None)
        ]
    elif name == "query_gift_info":
        if args.get("gift_name") is not None:
            matches = [
                r for r in rows if args["gift_name"].lower() in r["gift_name"].lower()
            ]
            actual = "OK" if matches else "EMPTY"
        else:
            ids = args.get("gift_ids") or [args["gift_id"]]
            actual = (
                "OK"
                if all(x in {r["gift_id"] for r in rows} for x in ids)
                else "NOT_FOUND"
                if args.get("gift_ids") is not None
                else "EMPTY"
            )
        expect(code == actual, "gift fixture contradicts branch")
        return
    elif name == "query_pool_config":
        matches = [
            r
            for r in rows
            if (
                r["pool_id"] == args["pool_id"]
                if args.get("pool_id") is not None
                else args["gift_id"] in r["gift_ids"]
            )
        ]
    else:
        matches = [
            r
            for r in rows
            if r["resource_type"] == args["resource_type"]
            and r["environment"] == args["environment"]
        ]
        if code == "ENVIRONMENT_UNSUPPORTED":
            return
    expect(bool(matches) == (code == "OK"), "fixture does not produce declared branch")


def _module(c, s, doc, declared, plan):
    expect(
        c["input"].get("operation") == "observe_module_event",
        "wrong module observation operation",
    )
    stimulus = c["input"]["stimulus"]
    binding = EVENT_STIMULI[declared]
    if s["target_id"] == "module.execution_guard":
        binding = {"action": "request_disallowed_tool", "allowed_tools": []}
    for key, value in binding.items():
        if key in {"user_input", "parameters", "tool_name"}:
            continue
        expect(
            stimulus.get(key) == value,
            "stimulus does not trigger declared event: " + key,
        )
    checks_equal(c["oracle"], [check("subset", "trace.event_types", [declared])])
    expect(
        any(
            p.get("kind") == "controlled_module_harness" and p.get("isolated") is True
            for p in c["preconditions"]
        ),
        "module fixture isolation must be explicit",
    )
    if "user_input" in binding:
        expect(
            isinstance(stimulus.get("user_input"), str)
            and bool(stimulus["user_input"].strip()),
            "module trigger needs a user input",
        )
    if "tool_name" in binding or s["target_id"] == "module.execution_guard":
        expect(
            "tool." + str(stimulus.get("tool_name")) in plan.documents,
            "module trigger must reference a declared tool",
        )
    if "parameters" in binding:
        params = stimulus.get("parameters")
        intent_doc = plan.documents["intent." + binding["intent"]]
        valid = Draft202012Validator(intent_doc["parameters_schema"]).is_valid(params)
        if declared == "intent_parameter_validation_failed":
            expect(not valid, "validation-failed event requires invalid parameters")
        elif declared == "intent_parameter_normalized":
            value = (params or {}).get("user_id")
            expect(
                isinstance(value, str)
                and value.isascii()
                and value.isdigit()
                and int(value) > 0,
                "normalization trigger needs a positive integer string",
            )
        elif declared == "intent_semantic_constraint_failed":
            group = intent_doc["semantic_rules"]["query_modes"]
            expect(
                valid and sum(params.get(k) is not None for k in group) > 1,
                "semantic failure needs valid types with conflicting modes",
            )
        else:
            expect(valid, "validated-event parameters must satisfy the schema")


def _chain(c, s, plan):
    intent_id, branch = s["dimension"].split(":")
    doc = plan.documents[intent_id]
    expect(
        isinstance(c["input"].get("user_input"), str)
        and bool(c["input"]["user_input"].strip()),
        "chain needs natural-language input",
    )
    params = c["input"].get("intent_parameters")
    expect(
        isinstance(params, dict)
        and Draft202012Validator(doc["parameters_schema"]).is_valid(params),
        "chain requires schema-valid intent_parameters annotation",
    )
    expect(
        all(_grounded(c["input"]["user_input"], v) for v in params.values()),
        "chain parameters not grounded in user text",
    )
    if branch == "early_stop" and intent_id not in {
        "intent.unsupported",
        "intent.add_backpack_gift",
    }:
        expect(
            not params,
            "clarification stimulus must deliberately omit all identifying fields",
        )
        expect(
            not re.search(
                r"[0-9@]|\btest\b|request_id", c["input"]["user_input"], re.I
            ),
            "clarification text carries identifying fields",
        )
    elif intent_id != "intent.unsupported":
        _selection(params, doc, allow_missing_optional=True)
    if branch == "early_stop":
        expect(c["preconditions"] == [], "early-stop must not pre-authorize execution")
        rule = doc["decision_rules"][
            "complete"
            if intent_id in {"intent.unsupported", "intent.add_backpack_gift"}
            else "incomplete"
        ]
        expect(
            c["oracle"] == {"terminal_status": rule["status"]},
            "early-stop terminal expectation mismatch",
        )
        return
    expect(
        c["input"].get("operation") == "agent_run"
        and c["input"].get("intent_id") == intent_id
        and c["input"].get("branch") == branch,
        "chain stimulus mismatch",
    )
    expect(
        c["input"].get("tool_name") == doc["required_tool_name"], "chain tool mismatch"
    )
    if branch == "error":
        expect(
            c["input"].get("controlled_fault")
            == {"at": "tool_handler", "behavior": "raise_exception"},
            "missing explicit controlled fault",
        )
    checks_equal(
        c["oracle"],
        [
            check(
                "equals",
                "agent_result.status",
                "FAILED" if branch == "error" else "SUCCESS",
            ),
            check("subset", "tool_trace.names", [doc["required_tool_name"]]),
        ],
    )
    tool_doc = plan.documents["tool." + doc["required_tool_name"]]
    args = c["input"].get("tool_arguments")
    expect(
        Draft202012Validator(schema_for(tool_doc)).is_valid(args),
        "chain tool_arguments invalid",
    )
    expect(
        all(args.get(k) == v for k, v in params.items() if v is not None and k in args),
        "chain tool arguments contradict intent parameters",
    )
    _fixture_branch(c, args, tool_doc, "OK")


def _rule(c, s, doc, declared):
    inp = c["input"]
    oracle = c["oracle"]
    dim = s["dimension"]
    rules = doc["parameter_semantics"]["rules"]
    if dim in {
        "query_modes",
        "query_mode_cardinality",
        "user_selection_modes",
        "gift_selection_modes",
        "selection_cardinality",
    }:
        group = rules.get(dim)
        if not isinstance(group, list):
            allowed_groups = [
                rules[k]
                for k in ("query_modes", "user_selection_modes", "gift_selection_modes")
                if k in rules
            ]
            expect(
                inp.get("modes") in allowed_groups, "mode group not declared in source"
            )
            group = inp["modes"]
        expect(
            inp.get("operation") == "validate_selection_modes"
            and inp.get("modes") == group,
            "wrong mode group",
        )
        expect(
            Draft202012Validator(schema_for(doc)).is_valid(inp["arguments"]),
            "invalid mode argument types",
        )
        expect(
            sum(inp["arguments"].get(k) is not None for k in group) > 1,
            "mode conflict requires multiple active modes",
        )
        checks_equal(oracle, [check("equals", "argument_validator.accepted", False)])
        expect(
            oracle.get("business_arguments_valid") is False, "wrong business-valid flag"
        )
        return
    if dim in {"confirmation", "idempotency_rules"} and inp.get("operation") in {
        "authorization_sequence",
        "idempotency_sequence",
    }:
        steps = inp["steps"]
        expect(len(steps) == 3, "sequence requires three steps")
        expect(inp.get("tool_name") == doc["tool_name"], "sequence tool mismatch")
        if dim == "confirmation":
            expect(
                inp["operation"] == "authorization_sequence"
                and steps[0].get("action") == "owner_authorize_one_attempt",
                "missing one-shot owner authorization",
            )
            expect(
                steps[1].get("action") == steps[2].get("action") == "invoke",
                "wrong authorization sequence actions",
            )
            expect(
                steps[1]["arguments"] == steps[2]["arguments"],
                "authorization attempts must repeat same arguments",
            )
            expected = [
                check("equals", "step[1].code", "OK"),
                check("equals", "step[2].code", "CONFIRMATION_REQUIRED"),
                check(
                    "unchanged", "state.after_step[2]", {"ref": "state.after_step[1]"}
                ),
            ]
            args_list = [steps[1]["arguments"], steps[2]["arguments"]]
        else:
            expect(
                declared.get("mode") == "REQUEST_ID_WITHIN_FIXTURE_INSTANCE",
                "idempotency mode unsupported",
            )
            args_list = [x["arguments"] for x in steps]
            expect(
                args_list[0] == args_list[1] and args_list[2] != args_list[1],
                "wrong idempotency duplicate/conflict sequence",
            )
            expect(
                len({x["request_id"] for x in args_list}) == 1,
                "request id must stay fixed",
            )
            expected = [
                check("equals", "step[1].resources", {"ref": "step[0].resources"}),
                check("equals", "step[2].code", "CONFLICT"),
                check(
                    "unchanged", "state.after_step[2]", {"ref": "state.after_step[1]"}
                ),
            ]
        expect(
            all(Draft202012Validator(schema_for(doc)).is_valid(x) for x in args_list),
            "sequence arguments invalid",
        )
        checks_equal(oracle, expected)
        _fixture_branch(
            c,
            args_list[0],
            doc,
            "OK",
            authorization=0 if dim == "confirmation" else None,
        )
        if dim == "idempotency_rules":
            expect(
                all(
                    x["environment"] == "test"
                    and x["count"] <= rules["maximum_fixture_count"]
                    for x in args_list
                ),
                "idempotency business arguments invalid",
            )
            expect(
                any(
                    p.get("share_instance_within_case") is True
                    for p in c["preconditions"]
                ),
                "sequence must share one fixture instance",
            )
        return
    expect(inp.get("operation") == "invoke_tool", "wrong rule operation")
    args = _tool_input(c, doc)
    if dim.startswith("default_"):
        field = dim.removeprefix("default_")
        expect(args.get(field) is None, "default field must be absent/null")
        if field == "num":
            expect(
                args.get("gift_nums") is None,
                "explicit gift quantities override default_num; use gift_id/gift_ids",
            )
        expected = [check("equals", "tool_result.data.grants[0]." + field, declared)]
    elif dim == "duplicate_users":
        users = args.get("user_ids", [])
        expect(
            len(users) > 1 and len(set(users)) == 1,
            "duplicate_users requires repeated identical user",
        )
        expect(
            args.get("gift_id") is not None and args.get("gift_ids") is None,
            "use one gift for count assertion",
        )
        expected = [check("count", "tool_result.data.grants", 1)]
    elif dim == "mutation":
        expect(
            len(set(args.get("user_ids", []))) >= 2,
            "mutation test needs mixed existing/missing users",
        )
        expected = [
            check("equals", "tool_result.code", "NOT_FOUND"),
            check("unchanged", "fixture.after", {"ref": "fixture.before"}),
        ]
    elif dim == "idempotency_rules" and declared.get("mode") == "READ_ONLY":
        expected = [check("unchanged", "fixture.after", {"ref": "fixture.before"})]
    else:
        raise ValueError("unbound tool rule: " + dim)
    checks_equal(oracle, expected)
    if dim == "idempotency_rules" and declared.get("mode") == "READ_ONLY":
        accepted_branch = False
        for branch in doc["result_protocols"]["declared_results"]:
            try:
                _fixture_branch(c, args, doc, branch)
                accepted_branch = True
                break
            except ValueError:
                pass
        expect(accepted_branch, "no declared read branch matches fixture")
    else:
        _fixture_branch(c, args, doc, "NOT_FOUND" if dim == "mutation" else "OK")
    if dim == "mutation":
        users = next(
            p["records"]["users"]
            for p in c["preconditions"]
            if p.get("kind") == "fixture_setup"
        )
        expect(
            any(u in {r["user_id"] for r in users} for u in args["user_ids"]),
            "mutation stimulus needs at least one existing user",
        )


def validate_candidate(value, s, plan):
    try:
        errors = list(
            Draft202012Validator(FullCandidate.model_json_schema()).iter_errors(value)
        )
        expect(not errors, errors[0].message if errors else "")
        c = FullCandidate.model_validate(value).model_dump()
        expect(
            c["evidence_refs"] == s["evidence_refs"],
            "source evidence references mismatch",
        )
        expect(not _hidden_answer(c["input"]), "input contains oracle/assertion fields")
        if s["input_only"]:
            expect(c["oracle"] is None, "contract-gap slot must not contain an oracle")
            expect(
                isinstance(c["gap"], str) and bool(c["gap"].strip()),
                "contract gap must be explicit",
            )
            if s["extra_oracle_gap"]:
                expect(
                    set(c["input"]) == {"user_input"}
                    and isinstance(c["input"]["user_input"], str)
                    and bool(c["input"]["user_input"].strip()),
                    "input-only intent must contain only user_input",
                )
            else:
                expect(
                    set(c["input"]) == {"operation", "requirement", "needed_contract"}
                    and c["input"]["operation"] == "contract_gap",
                    "blocked requirement must use the gap-only shape",
                )
                expect(
                    all(
                        isinstance(c["input"][k], str) and c["input"][k].strip()
                        for k in ["requirement", "needed_contract"]
                    ),
                    "gap description empty",
                )
            expect(
                c["preconditions"] == [], "blocked slots cannot invent executable setup"
            )
            return []
        expect(
            c["oracle"] is not None and c["gap"] is None,
            "supported slot needs oracle and no fabricated gap",
        )
        doc = plan.document(s)
        declared = plan.declared(s)
        kind = s["case_kind"]
        allowed = {"checks"}
        if kind == "parameter":
            allowed.add("arguments_schema_valid")
        if kind == "tool_result":
            allowed.add("declared_terminal_status")
        if kind == "intent_case":
            allowed = {"expected_module_output"}
        if kind == "chain_case" and s["dimension"].endswith(":early_stop"):
            allowed = {"terminal_status"}
        if (
            kind == "tool_rule"
            and c["input"].get("operation") == "validate_selection_modes"
        ):
            allowed.add("business_arguments_valid")
        expect(
            set(c["oracle"]) == allowed,
            "oracle fields differ from the supported contract",
        )
        if kind == "schema_constraint":
            expect(
                c["input"]
                == {
                    "operation": "inspect_declared_constraint",
                    "pointer": s["pointer"],
                },
                "static inspection pointer/operation mismatch",
            )
            checks_equal(
                c["oracle"], [check("equals", "contract" + s["pointer"], declared)]
            )
        elif kind == "parameter":
            _parameter(c, s, doc)
        elif kind == "intent_case":
            _intent(c, s, doc)
        elif kind == "module_event":
            _module(c, s, doc, declared, plan)
        elif kind == "tool_result":
            _tool_result(c, s, doc, declared)
        elif kind == "chain_case":
            _chain(c, s, plan)
        elif kind == "tool_rule":
            _rule(c, s, doc, declared)
        else:
            raise ValueError("no semantic validator for " + kind)
        return []
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        return [f"{type(exc).__name__}: {exc}"]
