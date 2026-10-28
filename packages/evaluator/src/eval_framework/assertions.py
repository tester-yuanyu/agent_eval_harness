"""Registered deterministic assertions; no semantic judge and no case branching."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .capabilities import CapabilityRegistry
from .native_scoring import capture_scores, contains_text, exact_value, subset_value
from .observation_assertions import ObservationCheckConfig, evaluate_observations
from .provider import AdapterOutput
from .schemas import AssertionResult, AssertionSpec, EvalCase
from .turn_assertions import evaluate_turns

ASSERTION_REGISTRY_VERSION = "inspect-assertions-v1"
ASSERTION_SCOPES = {
    "observations_match": {"module", "link", "end_to_end"},
    "turns_match": {"link", "end_to_end"},
    "output_schema_valid": {"module"},
    "intent_envelope_schema_valid": {"module"},
    "intent_parameters_schema_valid": {"module"},
    "intent_match": {"module"},
    "status_match": {"module", "link"},
    "next_action_match": {"module"},
    "params_match": {"module"},
    "missing_params_match": {"module"},
    "tool_called": {"link"},
    "tool_not_called": {"link"},
    "tool_call_count": {"link"},
    "tool_args_match": {"link"},
    "tool_result_consistent": {"link"},
    "no_state_change": {"link"},
    "final_state_match": {"end_to_end"},
    "no_duplicate_side_effect": {"end_to_end"},
    "confirmation_requested": {"end_to_end"},
    "confirmation_accepted": {"end_to_end"},
    "no_write_before_confirmation": {"end_to_end"},
    "response_consistent": {"end_to_end"},
}


@dataclass(frozen=True)
class AssertionContext:
    case: EvalCase
    output: AdapterOutput
    capabilities: CapabilityRegistry

    @property
    def module(self) -> dict[str, Any]:
        return self.output.module_output or {}

    @property
    def turns(self) -> list[dict[str, Any]]:
        return self.output.turns

    @property
    def calls(self) -> list[dict[str, Any]]:
        if self.output.evidence_status is not None:
            return [
                event["payload"]
                for event in self.events
                if event["event_type"] == "tool_requested"
            ]
        return [call for turn in self.turns for call in turn.get("tool_calls", [])]

    @property
    def events(self) -> list[dict[str, Any]]:
        if self.output.trace_events is not None:
            return [
                event
                for event in self.output.trace_events
                if event.get(
                    "validation_status",
                    "INVALID" if self.output.evidence_status is not None else "VALID",
                )
                == "VALID"
            ]
        return [event for turn in self.turns for event in turn.get("events", [])]


RawResult = tuple[bool | None, Any, Any, list[str], str]
AssertionFunction = Callable[[AssertionContext, AssertionSpec], RawResult]
REGISTRY: dict[str, AssertionFunction] = {}


def register(name: str) -> Callable[[AssertionFunction], AssertionFunction]:
    def decorate(function: AssertionFunction) -> AssertionFunction:
        REGISTRY[name] = function
        return function

    return decorate


def _module_expected(ctx: AssertionContext, key: str, spec: AssertionSpec) -> Any:
    return spec.config.get(
        "expected", (ctx.case.oracle.expected_module_output or {}).get(key)
    )


def _module_field(key: str) -> AssertionFunction:
    def check(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
        expected = _module_expected(ctx, key, spec)
        actual = ctx.module.get(key)
        return (
            exact_value(actual, expected),
            expected,
            actual,
            [f"module_output:/{key}"],
            "",
        )

    return check


for _name, _key in {
    "intent_match": "intent",
    "next_action_match": "next_action",
}.items():
    REGISTRY[_name] = _module_field(_key)


@register("status_match")
def status_match(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
    if ctx.case.test_scope == "module":
        expected = _module_expected(ctx, "status", spec)
        actual = ctx.module.get("status")
        ref = "module_output:/status"
    else:
        expected = spec.config.get("expected", ctx.case.oracle.expected_agent_status)
        actual = ctx.turns[-1].get("status") if ctx.turns else None
        ref = "turn:last/status"
    return exact_value(actual, expected), expected, actual, [ref], ""


@register("intent_envelope_schema_valid")
def intent_envelope_schema_valid(
    ctx: AssertionContext, spec: AssertionSpec
) -> RawResult:
    try:
        schema = ctx.capabilities.get_module(ctx.case.target).payload.get(
            "output_schema"
        )
    except KeyError:
        return (
            False,
            {"module_id": ctx.case.target, "schema": "output_schema"},
            {"errors": [{"type": "UNKNOWN_MODULE", "path": []}]},
            ["module_output:/"],
            "",
        )
    if not isinstance(schema, dict):
        return (
            False,
            {"module_id": ctx.case.target, "schema": "output_schema"},
            {"errors": [{"type": "MISSING_SCHEMA", "path": []}]},
            ["module_output:/"],
            "",
        )
    errors = _json_schema_errors(ctx.module, schema)
    return (
        not errors,
        {"module_id": ctx.case.target, "schema": "output_schema"},
        "valid" if not errors else {"value": ctx.module, "errors": errors},
        ["module_output:/"],
        "",
    )


# Compatibility alias for already-frozen evaluation datasets.
REGISTRY["output_schema_valid"] = intent_envelope_schema_valid


@register("intent_parameters_schema_valid")
def intent_parameters_schema_valid(
    ctx: AssertionContext, spec: AssertionSpec
) -> RawResult:
    intent = ctx.module.get("intent")
    parameters = ctx.module.get("parameters")
    expected = {"intent": intent, "schema": "parameters_schema"}
    if not isinstance(intent, str) or not intent:
        return (
            False,
            expected,
            {
                "parameters": parameters,
                "errors": [{"type": "UNKNOWN_CAPABILITY", "path": ["intent"]}],
            },
            ["module_output:/parameters"],
            "",
        )
    try:
        schema = ctx.capabilities.parameter_schema(intent)
    except KeyError:
        return (
            False,
            expected,
            {
                "parameters": parameters,
                "errors": [{"type": "UNKNOWN_CAPABILITY", "path": ["intent"]}],
            },
            ["module_output:/parameters"],
            "",
        )
    errors = _json_schema_errors(parameters, schema)
    return (
        not errors,
        expected,
        "valid" if not errors else {"parameters": parameters, "errors": errors},
        ["module_output:/parameters"],
        "",
    )


def _json_schema_errors(value: Any, schema: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
    except SchemaError as exc:
        return [
            {
                "type": "INVALID_SCHEMA",
                "path": [],
                "schema_path": list(exc.schema_path),
                "message": exc.message,
            }
        ]
    found = sorted(
        validator.iter_errors(value),
        key=lambda item: (list(item.path), list(item.schema_path)),
    )
    return [
        {
            "type": f"JSON_SCHEMA_{str(item.validator).upper()}",
            "path": list(item.path),
            "schema_path": list(item.schema_path),
            "message": item.message,
        }
        for item in found
    ]


@register("params_match")
def params_match(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
    expected = spec.config.get(
        "expected", (ctx.case.oracle.expected_module_output or {}).get("parameters")
    )
    actual = ctx.module.get("parameters")
    if (
        spec.config.get("expected_subset")
        and isinstance(expected, dict)
        and isinstance(actual, dict)
    ):
        passed = exact_value({k: actual[k] for k in expected if k in actual}, expected)
    else:
        passed = exact_value(actual, expected)
    return passed, expected, actual, ["module_output:/parameters"], ""


@register("missing_params_match")
def missing_params_match(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
    expected = spec.config.get(
        "expected",
        (ctx.case.oracle.expected_module_output or {}).get("missing_parameters", []),
    )
    actual = ctx.module.get("missing_parameters", [])
    return (
        exact_value(sorted(set(actual)), sorted(set(expected))),
        expected,
        actual,
        ["module_output:/missing_parameters"],
        "",
    )


def _tool_name(spec: AssertionSpec, ctx: AssertionContext) -> str | None:
    if "tool" in spec.config:
        return spec.config["tool"]
    return (
        ctx.case.oracle.expected_tool_calls[0].name
        if ctx.case.oracle.expected_tool_calls
        else None
    )


@register("tool_called")
def tool_called(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
    expected = _tool_name(spec, ctx)
    actual = [call["name"] for call in ctx.calls]
    refs = _call_refs(ctx, ctx.calls)
    return (
        any(exact_value(name, expected) for name in actual),
        expected,
        actual,
        refs,
        "",
    )


@register("tool_not_called")
def tool_not_called(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
    forbidden = spec.config.get("tools", ctx.case.oracle.forbidden_tools)
    actual = [call["name"] for call in ctx.calls]
    return (
        not any(exact_value(name, denied) for name in actual for denied in forbidden),
        forbidden,
        actual,
        _call_refs(ctx, [c for c in ctx.calls if c["name"] in forbidden]),
        "",
    )


@register("tool_call_count")
def tool_call_count(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
    tool = _tool_name(spec, ctx)
    expected = spec.config.get("count")
    if expected is None and ctx.case.oracle.expected_tool_calls:
        expected = ctx.case.oracle.expected_tool_calls[0].count
    actual = sum(call["name"] == tool for call in ctx.calls)
    return (
        exact_value(actual, expected),
        expected,
        actual,
        _call_refs(ctx, ctx.calls),
        "",
    )


@register("tool_args_match")
def tool_args_match(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
    tool = _tool_name(spec, ctx)
    calls = [call for call in ctx.calls if call["name"] == tool]
    expected = spec.config.get("expected")
    if expected is None and ctx.case.oracle.expected_tool_calls:
        expected = ctx.case.oracle.expected_tool_calls[0].arguments
    actual = calls[0]["arguments"] if calls else None
    if (
        spec.config.get("expected_subset")
        and isinstance(expected, dict)
        and isinstance(actual, dict)
    ):
        passed = exact_value({k: actual[k] for k in expected if k in actual}, expected)
    else:
        passed = exact_value(actual, expected)
    refs = _call_refs(ctx, calls[:1])
    return passed, expected, actual, refs, ""


def _call_refs(ctx, calls):
    if ctx.output.evidence_status is not None:
        refs = [
            f"event:{event['event_id']}"
            for event in ctx.events
            if event["event_type"] == "tool_requested" and event["payload"] in calls
        ]
        if not refs:
            refs = list(
                dict.fromkeys(
                    f"trace:{event['trace_id']}"
                    for event in ctx.events
                    if event.get("trace_id")
                )
            )
        if not refs and (ctx.output.evidence_manifest or {}).get("trace_id"):
            refs = [f"trace:{ctx.output.evidence_manifest['trace_id']}"]
        return refs
    return [f"tool_call:call:{call['call_id']}" for call in calls]


@register("tool_result_consistent")
def tool_result_consistent(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
    contradictions: list[str] = []
    terminal_events = {
        (event.get("run_id"), event.get("payload", {}).get("call_id")): event[
            "event_type"
        ]
        for event in ctx.events
        if event["event_type"] in {"tool_succeeded", "tool_failed", "tool_timeout"}
    }
    result_calls = [call for turn in ctx.turns for call in turn.get("tool_calls", [])]
    for run_id, call in (
        (turn.get("run_id"), call)
        for turn in ctx.turns
        for call in turn.get("tool_calls", [])
    ):
        if (
            call["status"] == "SUCCESS"
            and call.get("output", {}).get("success") is False
        ):
            contradictions.append(
                f"{call['call_id']}: successful record has failed output"
            )
        event = terminal_events.get((run_id, call["call_id"]))
        if event is None and ctx.output.evidence_status is None:
            event = terminal_events.get((None, call["call_id"]))
        expected_event = {
            "SUCCESS": "tool_succeeded",
            "FAILED": "tool_failed",
            "TIMEOUT": "tool_timeout",
        }[call["status"]]
        if event is None:
            contradictions.append(f"{call['call_id']}: terminal trace event missing")
        elif event != expected_event:
            contradictions.append(
                f"{call['call_id']}: trace={event}, record={call['status']}"
            )
    final_status = ctx.turns[-1]["status"] if ctx.turns else None
    if final_status == "SUCCESS" and any(
        call["status"] != "SUCCESS" for call in result_calls
    ):
        contradictions.append("Agent SUCCESS conflicts with failed tool call")
    return not contradictions, "no contradictions", contradictions, [], ""


def _without_run_id(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    return {key: value for key, value in snapshot.items() if key != "run_id"}


@register("no_state_change")
def no_state_change(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
    after = ctx.output.snapshot
    if after is None and ctx.turns:
        return False, "unchanged SQLite", "after snapshot unavailable", [], ""
    before_value, after_value = (
        _without_run_id(ctx.output.before_snapshot),
        _without_run_id(after),
    )
    return (
        exact_value(before_value, after_value),
        before_value,
        after_value,
        ["snapshot:/"],
        "",
    )


def _subset(actual: Any, expected: Any) -> bool:
    return subset_value(actual, expected)


@register("final_state_match")
def final_state_match(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
    expected = spec.config.get("expected", ctx.case.oracle.goal_state)
    actual = ctx.output.snapshot
    return _subset(actual, expected), expected, actual, ["snapshot:/"], ""


@register("no_duplicate_side_effect")
def no_duplicate_side_effect(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
    field = spec.config.get("count_field", "mock_backpack_grant_count")
    expected = spec.config.get("expected_count", 1)
    actual = (ctx.output.snapshot or {}).get(field)
    return exact_value(actual, expected), expected, actual, [f"snapshot:/{field}"], ""


def _event_assertion(event_type: str) -> AssertionFunction:
    def check(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
        accepted = {event_type}
        if event_type == "confirmation_requested":
            accepted.add("confirmation_required")
        matches = [event for event in ctx.events if event["event_type"] in accepted]
        refs = [f"event:{event['event_id']}" for event in matches]
        return (
            bool(matches),
            event_type,
            [event["event_type"] for event in matches],
            refs,
            "",
        )

    return check


REGISTRY["confirmation_requested"] = _event_assertion("confirmation_requested")
REGISTRY["confirmation_accepted"] = _event_assertion("confirmation_accepted")


@register("no_write_before_confirmation")
def no_write_before_confirmation(
    ctx: AssertionContext, spec: AssertionSpec
) -> RawResult:
    field = spec.config.get("count_field", "mock_backpack_grant_count")
    before = (ctx.output.before_snapshot or {}).get(field, 0)
    accepted = False
    missing = len(ctx.output.turn_snapshots) != len(ctx.turns)
    actual, refs = [], []
    for index, turn in enumerate(ctx.turns):
        events = [
            event for event in ctx.events if event.get("run_id") == turn.get("run_id")
        ]
        if ctx.output.evidence_status is None:
            events = turn.get("events", [])
        accepted = accepted or any(
            e["event_type"] == "confirmation_accepted" for e in events
        )
        waiting = turn.get("status") in {"NEED_CLARIFICATION", "NEED_CONFIRMATION"}
        if index >= len(ctx.output.turn_snapshots):
            missing = True
            continue
        count = ctx.output.turn_snapshots[index].get(field)
        refs.append(f"snapshot:turn:{index}/{field}")
        actual.append(count)
        if count is None:
            missing = True
        elif (waiting or not accepted) and count != before:
            if (
                waiting
                or ctx.output.evidence_status is None
                or _coverage_complete(ctx, {"confirmation_accepted"})
            ):
                return False, "unchanged before confirmation", actual, refs, ""
            missing = True
        if waiting:
            accepted = False
        if count is not None:
            before = count
    return (
        None if missing else True,
        "unchanged before confirmation",
        actual,
        refs,
        "Confirmation or state evidence incomplete" if missing else "",
    )


@register("response_consistent")
def response_consistent(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
    response = ctx.turns[-1].get("final_response", "") if ctx.turns else ""
    config = ctx.case.oracle.expected_response or {}
    config = {**config, **spec.config}
    contains_all = config.get("contains_all", [])
    contains_any = config.get("contains_any", [])
    forbidden = config.get("forbidden_contains", [])
    expected_outcome = config.get("expected_outcome")
    passed = all(contains_text(response, value) for value in contains_all)
    passed = passed and (
        not contains_any
        or any(contains_text(response, value) for value in contains_any)
    )
    passed = passed and not any(contains_text(response, value) for value in forbidden)
    if expected_outcome is not None:
        passed = passed and exact_value(ctx.turns[-1].get("status"), expected_outcome)
    return passed, config, response, ["turn:last/final_response"], ""


@register("observations_match")
def observations_match(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
    config = ObservationCheckConfig.model_validate(spec.config)
    # Returned observations never establish independent state. Only the Provider's
    # existing environment-observation channel supplies that evidence.
    values = (
        ctx.output.snapshot
        if config.channel == "independent"
        else ctx.output.observations
    )
    passed, expected, actual, refs, message = evaluate_observations(values, config)
    if passed is True and not ctx.output.execution_completed:
        passed, message = None, "Execution incomplete; remaining observations unknown"
    return passed, expected, actual, refs, message


@register("turns_match")
def turns_match(ctx: AssertionContext, spec: AssertionSpec) -> RawResult:
    return evaluate_turns(
        ctx,
        spec,
        subset=_subset,
        tool_coverage_complete=_coverage_complete(ctx, {"tool_requested"}),
    )


def run_assertions(
    case: EvalCase,
    output: AdapterOutput,
    capabilities: CapabilityRegistry,
) -> list[AssertionResult]:
    context = AssertionContext(case, output, capabilities)
    results = []
    for spec in case.oracle.evaluation.checks:
        reason = _insufficient_evidence(context, spec)
        if reason:
            results.append(
                AssertionResult(
                    name=spec.name,
                    weight=spec.weight,
                    critical=spec.critical,
                    applicable=True,
                    passed=None,
                    message=reason,
                )
            )
            continue
        with capture_scores() as native_scores:
            passed, expected, actual, refs, message = REGISTRY[spec.name](context, spec)
        results.append(
            AssertionResult(
                name=spec.name,
                weight=spec.weight,
                critical=spec.critical,
                passed=passed,
                expected=expected,
                actual=actual,
                message=message,
                evidence_refs=refs,
                native_scores=native_scores,
            )
        )
    return results


def _insufficient_evidence(ctx, spec):
    """Positive observations can decide checks despite an interrupted run."""
    if spec.name not in REGISTRY:
        return "Unknown assertion; evidence requirements are not defined"
    if spec.name in {"turns_match", "observations_match"}:
        return None  # Evaluate available turns; missing data cannot hide a failure.
    if spec.name in {
        "final_state_match",
        "no_duplicate_side_effect",
        "no_state_change",
    }:
        if ctx.output.snapshot is None:
            return "State snapshot unavailable"
        if spec.name == "no_state_change" and ctx.output.before_snapshot is None:
            return "Before-state snapshot unavailable"
    if spec.name == "no_write_before_confirmation" and not ctx.output.turn_snapshots:
        return "Pre-confirmation state evidence unavailable"
    if ctx.output.evidence_status is None:
        return None  # explicit legacy provider
    name = spec.name
    complete = _coverage_complete(ctx, {"tool_requested"})
    if ctx.case.test_scope == "module":
        return (
            None
            if ctx.output.module_output is not None
            else "Final module output unavailable"
        )
    if name in {"tool_called", "tool_not_called", "tool_args_match"}:
        # This rule compares the first invocation. A missing earlier invocation
        # means a later observed match cannot stand in for it.
        if name == "tool_args_match" and not complete:
            return (
                "First tool invocation cannot be established from incomplete coverage"
            )
        if name == "tool_not_called":
            forbidden = spec.config.get("tools", ctx.case.oracle.forbidden_tools)
            observed = any(call["name"] in forbidden for call in ctx.calls)
        else:
            observed = any(call["name"] == _tool_name(spec, ctx) for call in ctx.calls)
        if observed:
            return None
        return None if complete else "Complete tool-call coverage unavailable"
    if name == "tool_call_count":
        expected = spec.config.get("count")
        if expected is None and ctx.case.oracle.expected_tool_calls:
            expected = ctx.case.oracle.expected_tool_calls[0].count
        count = sum(c["name"] == _tool_name(spec, ctx) for c in ctx.calls)
        if isinstance(expected, int) and count > expected:
            return None  # Additional missing records cannot undo an excess.
        return None if complete else "Complete tool-call coverage unavailable"
    if name in {"confirmation_requested", "confirmation_accepted"}:
        accepted = {name}
        if name == "confirmation_requested":
            accepted.add("confirmation_required")
        if any(e["event_type"] in accepted for e in ctx.events):
            return None
        return (
            None
            if _coverage_complete(ctx, accepted)
            else "Confirmation evidence coverage incomplete"
        )
    if name in {"status_match", "response_consistent"}:
        if not ctx.output.execution_completed or not ctx.turns:
            return "Final Agent result unavailable"
        return None
    if name in {"final_state_match", "no_duplicate_side_effect", "no_state_change"}:
        if ctx.output.snapshot is None:
            return "State snapshot unavailable"
        if name == "no_state_change" and ctx.output.before_snapshot is None:
            return "Before-state snapshot unavailable"
        return None
    if name == "tool_result_consistent":
        if not ctx.output.execution_completed or not ctx.turns:
            return "Final tool results unavailable"
        terminal = {"tool_succeeded", "tool_failed", "tool_timeout"}
        observed = {
            (e.get("run_id"), e["payload"].get("call_id"))
            for e in ctx.events
            if e["event_type"] in terminal
        }
        if any(
            (turn.get("run_id"), call.get("call_id")) not in observed
            for turn in ctx.turns
            for call in turn.get("tool_calls", [])
        ):
            return "Required terminal tool event unavailable"
        return None if _coverage_complete(ctx, terminal) else "Tool coverage incomplete"
    if name == "no_write_before_confirmation" and not ctx.output.turn_snapshots:
        return "Pre-confirmation state evidence unavailable"
    if ctx.output.evidence_status != "COMPLETE":
        return "Required evidence coverage incomplete"
    return None


def _coverage_complete(ctx, event_types):
    """Only local, identified content loss may be unrelated to a check."""
    if ctx.output.evidence_status == "COMPLETE":
        return True
    manifest = ctx.output.evidence_manifest or {}
    if (
        ctx.output.evidence_status != "PARTIAL"
        or not manifest.get("execution_completed")
        or not manifest.get("collection_closed")
    ):
        return False
    events = {e.get("sequence"): e for e in ctx.output.trace_events or []}
    for issue in manifest.get("issues", []):
        if issue.get("code") not in {
            "INVALID_OR_TRUNCATED_EVENT",
            "RECORD_SIZE_EXCEEDED",
        }:
            return False
        event = events.get(issue.get("sequence"))
        if event is None or event.get("event_type") in event_types:
            return False
    return bool(manifest.get("issues"))
