from test_full_generation_inventory import load
from test_full_generation_planner import plan


def compile_cases():
    from dataset_builder.full_generation.contract_cases import compile_contract_cases

    inv = load()
    slots, _ = plan(inv)
    return inv, slots, compile_contract_cases(inv, slots)


def test_tool_case_has_structured_arguments():
    _, _, cases = compile_cases()
    concrete = [c for c in cases if "arguments" in c.payload["input"]]
    assert concrete
    assert all(c.dataset_format == "capability_contract_case" for c in concrete)
    assert all("user_input" not in c.payload["input"] for c in concrete)


def test_invalid_argument_case_is_intentional():
    _, _, cases = compile_cases()
    bad = [
        c for c in cases if c.payload["oracle"].get("arguments_schema_valid") is False
    ]
    assert len(bad) >= 20
    assert all(c.payload["oracle"]["checks"] for c in bad)


def test_unknown_fixture_record_requires_precondition():
    _, slots, cases = compile_cases()
    by_slot = {s.slot_id: s for s in slots}
    for c in cases:
        if by_slot[c.slot_id].case_kind == "tool_result":
            assert c.payload["preconditions"]
            assert c.execution_readiness == "needs_runner"


def test_confirmation_is_external_fixture_only():
    _, _, cases = compile_cases()
    approval = [
        c
        for c in cases
        if c.payload["target_id"] == "tool.add_gift_to_backpack"
        and c.payload["input"].get("operation") == "authorization_sequence"
    ]
    assert approval
    assert (
        approval[0].payload["input"]["steps"][0]["action"]
        == "owner_authorize_one_attempt"
    )
    assert "Agent resume" not in str(approval[0].payload["input"])


def test_resource_idempotency_sequence():
    _, _, cases = compile_cases()
    seq = [
        c
        for c in cases
        if c.payload["input"].get("operation") == "idempotency_sequence"
    ]
    assert len(seq) == 1
    steps = seq[0].payload["input"]["steps"]
    assert steps[0]["arguments"] == steps[1]["arguments"]
    assert steps[2]["arguments"]["count"] != steps[0]["arguments"]["count"]
    assert any(c["op"] == "unchanged" for c in seq[0].payload["oracle"]["checks"])


def test_declared_tool_modes_have_concrete_conflict_inputs():
    _, _, cases = compile_cases()
    matches = [
        c
        for c in cases
        if c.payload["input"].get("operation") == "validate_selection_modes"
    ]
    assert {c.payload["target_id"] for c in matches} >= {
        "tool.query_gift_info",
        "tool.query_pool_config",
        "tool.add_gift_to_backpack",
    }
    assert all(
        c.payload["oracle"]["business_arguments_valid"] is False for c in matches
    )


def test_result_cases_have_explicit_branch_setup():
    _, slots, cases = compile_cases()
    by_slot = {s.slot_id: s for s in slots}
    for c in cases:
        if by_slot[c.slot_id].case_kind == "tool_result":
            setup = c.payload["preconditions"][0]
            assert "records" in setup or "steps" in setup


def test_supported_module_events_have_stimulus_definitions():
    _, slots, cases = compile_cases()
    kinds = {s.slot_id: s.case_kind for s in slots}
    event_cases = [
        c
        for c in cases
        if kinds[c.slot_id] == "module_event" and c.execution_readiness != "blocked"
    ]
    assert {c.payload["target_id"] for c in event_cases} >= {
        "module.execution_guard",
        "module.tool_loop",
        "module.observability",
    }
    assert all(c.payload["input"]["stimulus"] for c in event_cases)


def test_gift_not_found_uses_batch_all_must_exist_mode():
    _, slots, cases = compile_cases()
    ids = {
        s.slot_id
        for s in slots
        if s.target_id == "tool.query_gift_info"
        and s.case_kind == "tool_result"
        and s.dimension == "NOT_FOUND"
    }
    matches = [c for c in cases if c.slot_id in ids]
    assert matches
    for case in matches:
        args = case.payload["input"]["arguments"]
        assert args["gift_id"] is None
        assert args["gift_ids"] == [1]
