from test_full_generation_inventory import load
from test_full_generation_planner import plan


def compiled():
    from dataset_builder.full_generation.intent_cases import compile_intent_cases
    from dataset_builder.full_generation.runtime_cases import compile_runtime_cases

    inv = load()
    slots, _ = plan(inv)
    return (
        inv,
        slots,
        compile_intent_cases(inv, slots),
        compile_runtime_cases(inv, slots),
    )


def test_all_seven_intents_have_cases():
    inv, _, cases, _ = compiled()
    assert {c.payload["oracle"]["expected_module_output"]["intent"] for c in cases} == {
        "query_user",
        "query_gift",
        "query_pool",
        "query_information",
        "prepare_resource",
        "add_backpack_gift",
        "unsupported",
    }


def test_gift_stops_for_confirmation_without_write():
    _, _, _, (cases, _) = compiled()
    gifts = [
        c
        for c in cases
        if c.dataset_format == "eval_case"
        and "add_backpack_gift" in c.payload["task_id"]
    ]
    assert gifts
    for c in gifts:
        assert c.payload["oracle"]["expected_agent_status"] == "NEED_CONFIRMATION"
        assert not c.payload["oracle"]["expected_tool_calls"]
        assert "add_gift_to_backpack" in c.payload["oracle"]["forbidden_tools"]


def test_prepare_resource_dispute_blocks_positive_e2e():
    _, slots, _, (cases, blockers) = compiled()
    ids = {
        s.slot_id
        for s in slots
        if s.target_id == "chain.end_to_end"
        and s.dimension == "intent.prepare_resource:normal"
    }
    assert ids <= {x for b in blockers for x in b.affected_slot_ids}
    assert not any(c.slot_id in ids and c.dataset_format == "eval_case" for c in cases)


def test_no_fake_fault_injection_support():
    _, _, _, (cases, _) = compiled()
    for c in cases:
        if c.dataset_format == "eval_case":
            assert not c.payload["execution"]["fault_injection"]


def test_critical_path_serializes_as_link():
    _, slots, _, (cases, _) = compiled()
    by_id = {s.slot_id: s for s in slots}
    links = [
        c
        for c in cases
        if c.dataset_format == "eval_case"
        and by_id[c.slot_id].layer == "critical_links"
    ]
    assert links
    assert all(c.payload["test_scope"] == "link" for c in links)


def test_e2e_requires_real_supported_goal_assertion():
    _, _, _, (cases, _) = compiled()
    for c in cases:
        if c.dataset_format == "eval_case" and c.payload["test_scope"] == "end_to_end":
            assert (
                c.payload["oracle"]["goal_state"]["terminal_status"]
                == c.payload["oracle"]["expected_agent_status"]
            )
            check = c.payload["oracle"]["evaluation"]["checks"][0]
            assert check["name"] == "turns_match"
            assert check["config"]["turns"][0]["tool_calls"] == []
            assert (
                check["config"]["turns"][0]["status"]
                == c.payload["oracle"]["goal_state"]["terminal_status"]
            )


def test_gift_tool_error_is_blocked_before_confirmation_resume():
    _, slots, _, (cases, blockers) = compiled()
    ids = {s.slot_id for s in slots if s.dimension == "intent.add_backpack_gift:error"}
    assert ids
    assert ids <= {x for b in blockers for x in b.affected_slot_ids}
    assert all(c.execution_readiness == "blocked" for c in cases if c.slot_id in ids)
