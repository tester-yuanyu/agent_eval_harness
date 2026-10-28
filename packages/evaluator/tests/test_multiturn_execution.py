from dataclasses import replace

import pytest
from conftest import assertion, e2e_case, intent
from support.model_client import DeterministicModelClient

from eval_framework.assertions import run_assertions
from eval_framework.mini_agent_adapter import MiniAgentAdapter
from eval_framework.provider import AdapterOutput
from eval_framework.runtime_factory import RuntimeFactory
from eval_framework.schemas import EvalCase, ExecutionSpec


def test_clarification_continues_and_terminal_result_stops_conversation():
    execution = ExecutionSpec(
        user_input="query",
        user_responses=["user_id 7", "must not execute"],
        tool_profile="empty",
    )
    client = DeterministicModelClient(
        [
            intent("query_user", "NEED_CLARIFICATION", "ASK_USER", {}, ["user_id"]),
            intent(
                "query_user",
                parameters={
                    "user_id": 7,
                    "room_id": None,
                    "email": None,
                    "phone": None,
                },
            ),
            {"type": "message", "content": "done"},
        ]
    )
    runtime = RuntimeFactory(lambda _: client).create(
        execution,
        session_id="session",
        allowed_tools=frozenset(),
    )
    output = MiniAgentAdapter(runtime).run_full(execution, "end_to_end")
    assert [turn["status"] for turn in output.turns] == [
        "NEED_CLARIFICATION",
        "SUCCESS",
    ]
    assert output.turns[1]["intent_result"]["parameters"]["user_id"] == 7


def test_link_rejects_followup_inputs_instead_of_silently_running_e2e():
    execution = ExecutionSpec(
        user_input="query",
        user_responses=["confirm"],
        tool_profile="empty",
    )
    runtime = RuntimeFactory(lambda _: DeterministicModelClient([])).create(
        execution,
        session_id="session",
        allowed_tools=frozenset(),
    )
    with pytest.raises(ValueError, match="link"):
        MiniAgentAdapter(runtime).run_full(execution, "link")


def turn_case():
    raw = e2e_case()
    raw["oracle"]["evaluation"]["checks"] = [
        assertion(
            "turns_match",
            critical=True,
            config={
                "turns": [
                    {
                        "status": "NEED_CONFIRMATION",
                        "tool_calls": [],
                        "state": {"grant_count": 0},
                    },
                    {
                        "status": "SUCCESS",
                        "parameters": {"num": 2},
                        "tool_calls": [
                            {"name": "add_gift_to_backpack", "arguments": {"num": 2}}
                        ],
                        "state": {"grant_count": 1},
                    },
                ]
            },
        )
    ]
    return EvalCase.model_validate(raw)


def turn_output():
    return AdapterOutput(
        None,
        [
            {"run_id": "r1", "status": "NEED_CONFIRMATION", "tool_calls": []},
            {
                "run_id": "r2",
                "status": "SUCCESS",
                "intent_result": {"parameters": {"num": 2}},
                "tool_calls": [
                    {"name": "add_gift_to_backpack", "arguments": {"num": 2}}
                ],
            },
        ],
        {"grant_count": 0},
        [{"grant_count": 0}, {"grant_count": 1}],
        {"grant_count": 1},
    )


def test_turn_checks_match_each_state_parameter_and_tool_call():
    result = run_assertions(turn_case(), turn_output(), None)[0]
    assert result.passed is True
    assert "snapshot:turn:0/" in result.evidence_refs


@pytest.mark.parametrize("change", ["early_write", "wrong_parameters", "extra_call"])
def test_turn_checks_reject_bad_intermediate_behavior_despite_correct_final_state(
    change,
):
    output = turn_output()
    if change == "early_write":
        output.turn_snapshots[0]["grant_count"] = 1
    elif change == "wrong_parameters":
        output.turns[1]["intent_result"]["parameters"]["num"] = 9
    else:
        output.turns[0]["tool_calls"].append({"name": "unexpected"})
    assert run_assertions(turn_case(), output, None)[0].passed is False


def test_missing_turn_state_is_inconclusive_and_does_not_hide_known_failure():
    output = replace(turn_output(), turn_snapshots=[])
    assert run_assertions(turn_case(), output, None)[0].passed is None
    output.turns[1]["intent_result"]["parameters"]["num"] = 9
    assert run_assertions(turn_case(), output, None)[0].passed is False


def test_missing_final_state_is_inconclusive_even_for_legacy_provider():
    raw = e2e_case()
    raw["oracle"]["evaluation"]["checks"] = [assertion("final_state_match")]
    case = EvalCase.model_validate(raw)
    assert (
        run_assertions(case, AdapterOutput(None, [], None, [], None), None)[0].passed
        is None
    )


def test_unconfirmed_write_on_later_turn_is_not_hidden_by_clean_first_turn():
    raw = e2e_case()
    raw["oracle"]["evaluation"]["checks"] = [
        assertion(
            "no_write_before_confirmation",
            config={"count_field": "grant_count"},
        )
    ]
    output = turn_output()  # No confirmation_accepted event, but second turn writes.
    result = run_assertions(EvalCase.model_validate(raw), output, None)[0]
    assert result.passed is False


def test_turn_tool_status_requires_independent_terminal_evidence():
    case = turn_case()
    case.oracle.evaluation.checks[0].config["turns"][1]["tool_calls"][0]["status"] = (
        "SUCCESS"
    )
    output = turn_output()
    output.turns[1]["tool_calls"][0].update(call_id="c", status="SUCCESS")
    output = replace(
        output,
        evidence_status="PARTIAL",
        trace_events=[
            {
                "event_id": "e",
                "event_type": "tool_requested",
                "run_id": "r2",
                "sequence": 1,
                "validation_status": "VALID",
                "payload": {
                    "call_id": "c",
                    "name": "add_gift_to_backpack",
                    "arguments": {"num": 2},
                },
            },
            {
                "sequence": 2,
                "event_type": "tool_succeeded",
                "validation_status": "INVALID",
            },
        ],
        evidence_manifest={
            "execution_completed": True,
            "collection_closed": True,
            "issues": [{"code": "INVALID_OR_TRUNCATED_EVENT", "sequence": 2}],
        },
    )
    assert run_assertions(case, output, None)[0].passed is None


def test_interrupted_conversation_cannot_pass_matching_prefix():
    output = replace(turn_output(), execution_completed=False)
    assert run_assertions(turn_case(), output, None)[0].passed is None
