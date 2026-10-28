"""Per-turn expectations over returned results and independently observed state."""

from eval_contracts.turn_assertions import TurnCheckConfig as TurnCheckConfig
from eval_contracts.turn_assertions import TurnExpectation as TurnExpectation
from eval_contracts.turn_assertions import TurnToolExpectation as TurnToolExpectation

from .native_scoring import exact_value


def evaluate_turns(ctx, spec, *, subset, tool_coverage_complete):
    expected = TurnCheckConfig.model_validate(spec.config)
    mismatches, missing, refs = [], [], []
    if not ctx.output.execution_completed:
        missing.append("execution did not complete")
    if len(ctx.turns) != len(expected.turns):
        if ctx.output.execution_completed or len(ctx.turns) > len(expected.turns):
            mismatches.append("turn count differs")
        else:
            missing.append("remaining turns unavailable")
    for index, (turn, wanted) in enumerate(
        zip(ctx.turns, expected.turns, strict=False)
    ):
        refs.append(f"turn:{index}/")
        if "status" not in turn:
            missing.append(f"turn {index}: status unavailable")
        elif not exact_value(turn["status"], wanted.status):
            mismatches.append(f"turn {index}: status differs")
        if wanted.parameters is not None:
            parameters = (turn.get("intent_result") or {}).get("parameters")
            if parameters is None:
                missing.append(f"turn {index}: parameters unavailable")
            elif not subset(parameters, wanted.parameters):
                mismatches.append(f"turn {index}: parameters differ")
        if wanted.tool_calls is not None:
            independent = ctx.output.evidence_status is not None
            calls = (
                [
                    e["payload"]
                    for e in ctx.events
                    if e["event_type"] == "tool_requested"
                    and e.get("run_id") == turn.get("run_id")
                ]
                if independent
                else turn.get("tool_calls")
            )
            complete = not independent or tool_coverage_complete
            if calls is None:
                missing.append(f"turn {index}: tool records unavailable")
            elif not complete:
                # Partial traces cannot prove ordering, but excess calls prove failure.
                if len(calls) > len(wanted.tool_calls):
                    mismatches.append(f"turn {index}: extra tool calls")
                missing.append(f"turn {index}: tool coverage incomplete")
            else:
                if len(calls) != len(wanted.tool_calls):
                    mismatches.append(f"turn {index}: tool count differs")
                for call, tool in zip(calls, wanted.tool_calls, strict=False):
                    if not exact_value(call.get("name"), tool.name) or (
                        tool.arguments is not None
                        and not subset(call.get("arguments"), tool.arguments)
                    ):
                        mismatches.append(
                            f"turn {index}: tool name or arguments differ"
                        )
                    if tool.status is not None:
                        terminal_types = {
                            "tool_succeeded": "SUCCESS",
                            "tool_failed": "FAILED",
                            "tool_timeout": "TIMEOUT",
                        }
                        terminal = next(
                            (
                                e
                                for e in ctx.events
                                if e["event_type"] in terminal_types
                                and e.get("run_id") == turn.get("run_id")
                                and e["payload"].get("call_id") == call.get("call_id")
                            ),
                            None,
                        )
                        if independent and terminal is None:
                            missing.append(
                                f"turn {index}: terminal tool evidence unavailable"
                            )
                            continue
                        if (
                            independent
                            and terminal_types[terminal["event_type"]] != tool.status
                        ):
                            mismatches.append(
                                f"turn {index}: observed tool status differs"
                            )
                        record = next(
                            (
                                r
                                for r in turn.get("tool_calls", [])
                                if r.get("call_id") == call.get("call_id")
                            ),
                            None,
                        )
                        if record is None or "status" not in record:
                            missing.append(f"turn {index}: tool status unavailable")
                        elif not exact_value(record["status"], tool.status):
                            mismatches.append(f"turn {index}: tool status differs")
        if wanted.state is not None:
            refs.append(f"snapshot:turn:{index}/")
            if index >= len(ctx.output.turn_snapshots):
                missing.append(f"turn {index}: state unavailable")
            elif not subset(ctx.output.turn_snapshots[index], wanted.state):
                mismatches.append(f"turn {index}: state differs")
    passed = False if mismatches else (None if missing else True)
    return (
        passed,
        expected.model_dump(exclude_none=True),
        {"mismatches": mismatches, "missing": missing},
        refs,
        "; ".join(mismatches + missing),
    )
