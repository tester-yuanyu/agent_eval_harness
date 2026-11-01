"""重复诊断只描述可观察的调用和文件状态，不推断必要性。"""

from copy import deepcopy
from importlib import import_module

import pytest


def score(observation):
    # Import here so the first red run reports a missing behavior per test.
    return import_module("eval_framework.benchmark.repetition").score_repetition(
        {}, observation
    )


def call(identifier, second=0, **extra):
    return {
        "id": identifier,
        "type": "tool",
        "name": "read_file",
        "turn": 1,
        "input": {"path": "./x"},
        "normalized_input": {"path": "x"},
        "start_time": f"2026-11-01T00:00:{second:02d}+00:00",
        "end_time": f"2026-11-01T00:00:{second + 1:02d}+00:00",
        "execution_started": True,
        "output": "value",
        "is_error": False,
        "tool_error": False,
        "before_files": {"x": "value"},
        "after_files": {"x": "value"},
        **extra,
    }


def observation(*events):
    return {"events": list(events), "evidence_complete": True}


def test_same_state_read_is_only_a_versioned_diagnostic_candidate():
    result = score(observation(call("a"), call("b", 2)))
    assert [row["score"] for row in result] == [1, 0]
    repeated = result[1]
    assert repeated["classification"] == "repeated_same_state"
    assert repeated["evidence_ids"] == ["a", "b"]
    assert repeated["event_id"] == "b"
    assert repeated["name"] == "tool_nonrepetition"
    assert repeated["formal"] is False
    assert repeated["backend"] == "deepeval"
    assert repeated["version"] and repeated["library_version"]
    assert repeated["threshold"] == 1
    assert "candidate" in repeated["reason"]
    assert "necessity" in repeated["semantics"]


def test_error_retry_is_not_a_repetition_candidate():
    result = score(observation(call("a", is_error=True, tool_error=True), call("b", 2)))
    assert result[1]["classification"] == "retry_after_error"
    assert result[1]["score"] == 1


@pytest.mark.parametrize("changed_field", ["before_files", "after_files"])
def test_changed_file_state_is_not_same_state_repetition(changed_field):
    result = score(
        observation(call("a"), call("b", 2, **{changed_field: {"x": "new"}}))
    )
    assert result[1]["classification"] == "state_changed"
    assert result[1]["score"] == 1


def test_intervening_write_and_restore_is_state_change():
    result = score(
        observation(
            call("a"),
            call(
                "write",
                2,
                name="write_file",
                normalized_input={"path": "x", "content": "new"},
                after_files={"x": "new"},
            ),
            call(
                "restore",
                4,
                name="write_file",
                normalized_input={"path": "x", "content": "value"},
                before_files={"x": "new"},
            ),
            call("b", 6),
        )
    )
    assert result[-1]["classification"] == "state_changed"
    assert result[-1]["score"] == 1
    assert result[-1]["evidence_ids"] == ["a", "write", "restore", "b"]


def test_cross_turn_calls_are_not_repeated():
    result = score(observation(call("a"), call("b", 2, turn=2)))
    assert result[1]["classification"] == "first_call"
    assert result[1]["score"] == 1


def test_normalized_argument_mapping_order_does_not_hide_repetition():
    result = score(
        observation(
            call("a", normalized_input={"path": "x", "options": {"a": 1, "b": 2}}),
            call("b", 2, normalized_input={"options": {"b": 2, "a": 1}, "path": "x"}),
        )
    )
    assert result[1]["score"] == 0


def test_boolean_and_numeric_arguments_are_not_equal():
    result = score(
        observation(
            call("a", normalized_input={"path": "x", "option": True}),
            call("b", 2, normalized_input={"path": "x", "option": 1}),
        )
    )
    assert result[1]["score"] == 1


@pytest.mark.parametrize(
    "field",
    [
        "before_files",
        "after_files",
        "is_error",
        "normalized_input",
        "execution_started",
        "end_time",
        "start_time",
        "output",
        "turn",
    ],
)
def test_first_call_with_missing_evidence_is_not_scored_normal(field):
    event = call("a")
    event.pop(field)
    if field == "is_error":
        event.pop("tool_error")
    result = score(observation(event))[0]
    assert result["status"] == "MISSING"
    assert result["score"] is None and result["success"] is None


@pytest.mark.parametrize(
    "extra",
    [
        {"is_error": "false"},
        {"tool_error": True},
        {"error": "conflicting failure"},
        {"execution_started": False},
        {"incomplete": True},
        {"before_snapshot_errors": [{"path": "x", "error": "denied"}]},
        {"after_files": {"x": None}},
        {"normalized_input": {"path": "x", "n": float("nan")}},
        {"end_time": "invalid"},
        {"turn": True},
    ],
)
def test_conflicting_or_incomplete_evidence_is_missing(extra):
    assert score(observation(call("a", **extra)))[0]["status"] == "MISSING"


def test_prior_unknown_result_cannot_make_later_call_normal():
    first = call("a")
    first.pop("is_error")
    first.pop("tool_error")
    result = score(observation(first, call("b", 2)))
    assert all(row["score"] is None for row in result)


@pytest.mark.parametrize(
    "observed",
    [
        observation(call("a"), call("a", 2)),
        {"events": [call("a")], "evidence_complete": False},
        {},
        {"events": [], "evidence_complete": False},
    ],
)
def test_untrusted_trace_never_reports_nonrepetition(observed):
    assert all(
        row["status"] == "MISSING" and row["score"] is None for row in score(observed)
    )


def test_no_calls_is_not_applicable_not_perfect():
    result = score(observation())
    assert len(result) == 1
    assert result[0]["status"] == "NOT_APPLICABLE"
    assert result[0]["score"] is None


def test_remote_tool_is_outside_file_state_diagnostic():
    result = score(
        observation(call("a", name="search_remote"), call("b", 2, name="search_remote"))
    )
    assert all(row["status"] == "NOT_APPLICABLE" for row in result)


def test_overlapping_call_results_cannot_establish_repetition_order():
    result = score(
        observation(call("a", end_time="2026-11-01T00:00:05+00:00"), call("b", 2))
    )
    assert result[-1]["status"] == "MISSING"


def test_inputs_are_not_mutated():
    observed = observation(call("a"), call("b", 2))
    original = deepcopy(observed)
    score(observed)
    assert observed == original


def test_parent_turn_link_is_compatible_with_saved_trajectory():
    first, second = call("a"), call("b", 2)
    for event in (first, second):
        event.pop("turn")
        event["parent_id"] = "turn-1"
    result = score(
        observation({"id": "turn-1", "type": "turn", "turn": 1}, first, second)
    )
    assert result[-1]["score"] == 0


def test_conflicting_parent_turn_link_is_missing():
    result = score(
        observation(
            {"id": "turn-1", "type": "turn", "turn": 1},
            call("a", turn=2, parent_id="turn-1"),
        )
    )
    assert result[0]["status"] == "MISSING"


def test_current_error_is_explicit_without_confusing_retry_with_success():
    result = score(
        observation(
            call("a", is_error=True, tool_error=True),
            call("b", 2, is_error=True, tool_error=True),
        )
    )
    assert result[-1]["classification"] == "retry_after_error"
    assert result[-1]["current_is_error"] is True


@pytest.mark.parametrize(
    "extra",
    [
        {"normalized_input": {"path": "x", "options": {1: "value"}}},
        {"before_snapshot_errors": None},
        {"before_snapshot_errors": ""},
    ],
)
def test_malformed_json_or_snapshot_status_is_missing(extra):
    assert score(observation(call("a", **extra)))[0]["status"] == "MISSING"


@pytest.mark.parametrize("turn", [0, "unknown"])
def test_prior_invalid_turn_cannot_be_treated_as_a_different_turn(turn):
    result = score(observation(call("a", turn=turn), call("b", 2)))
    assert result[-1]["status"] == "MISSING"


def test_malformed_tool_name_is_missing_instead_of_crashing():
    result = score(observation(call("a", name=[])))
    assert result[0]["status"] == "MISSING"


def test_duplicate_turn_numbers_do_not_merge_distinct_parent_turns():
    result = score(
        observation(
            {"id": "turn-1", "type": "turn", "turn": 1},
            call("a", parent_id="turn-1"),
            {"id": "turn-2", "type": "turn", "turn": 1},
            call("b", 2, parent_id="turn-2"),
        )
    )
    assert len(result) == 2
    assert all(row["status"] == "MISSING" and row["score"] is None for row in result)


@pytest.mark.parametrize("turn", [True, False, 0, -1, "1", None])
def test_invalid_parent_turn_number_cannot_be_overridden_by_valid_tool_turn(turn):
    result = score(
        observation(
            {"id": "turn-1", "type": "turn", "turn": turn},
            call("a", parent_id="turn-1"),
        )
    )
    assert result[0]["status"] == "MISSING"


def test_missing_parent_turn_number_is_not_inferred_from_event_position():
    result = score(
        observation(
            {"id": "turn-1", "type": "turn"},
            call("a", parent_id="turn-1"),
        )
    )
    assert result[0]["status"] == "MISSING"


@pytest.mark.parametrize(
    "parent_id", [[], {}, ["turn-1"], {"id": "turn-1"}, True, 1, "", "absent"]
)
def test_invalid_or_dangling_parent_reference_is_missing(parent_id):
    result = score(
        observation(
            {"id": "turn-1", "type": "turn", "turn": 1},
            call("a", parent_id=parent_id),
        )
    )
    assert result[0]["status"] == "MISSING"


def test_nonturn_parent_does_not_establish_file_tool_round():
    result = score(
        observation(
            {"id": "turn-1", "type": "turn", "turn": 1},
            {
                "id": "generation-1",
                "type": "generation",
                "turn": 1,
                "parent_id": "turn-1",
            },
            call("a", parent_id="generation-1"),
        )
    )
    assert result[0]["status"] == "MISSING"


def test_valid_distinct_parent_turns_remain_separate():
    result = score(
        observation(
            {"id": "turn-1", "type": "turn", "turn": 1},
            call("a", parent_id="turn-1"),
            {"id": "turn-2", "type": "turn", "turn": 2},
            call("b", 2, turn=2, parent_id="turn-2"),
        )
    )
    assert [row["classification"] for row in result] == ["first_call", "first_call"]


def test_explicit_tool_round_without_parent_retains_legacy_support():
    result = score(observation(call("a", parent_id=None), call("b", 2)))
    assert result[-1]["classification"] == "repeated_same_state"
