from test_full_generation_inventory import load


def plan(inv=None):
    from dataset_builder.full_generation.planner import plan_coverage

    return plan_coverage(inv or load())


def test_all_targets_accounted_for():
    inv = load()
    slots, _ = plan(inv)
    assert {s.target_id for s in slots} == {t["snapshot_id"] for t in inv.targets}
    assert len({s.slot_id for s in slots}) == len(slots)


def test_plan_is_stable():
    inv = load()
    a = plan(inv)
    inv.artifacts = dict(reversed(list(inv.artifacts.items())))
    b = plan(inv)
    assert [s.model_dump() for s in a[0]] == [s.model_dump() for s in b[0]]


def test_unknown_is_not_positive():
    slots, blockers = plan()
    for s in slots:
        if s.support_status != "supported":
            assert s.blocker_ids
    assert blockers


def test_all_declared_results_and_parameters_accounted_for():
    inv = load()
    slots, _ = plan(inv)
    for target in inv.targets:
        if target["snapshot_type"] != "tool":
            continue
        ident = target["snapshot_id"]
        d = inv.artifacts[ident]["payload"]
        pointers = {
            r.pointer for s in slots if s.target_id == ident for r in s.source_refs
        }
        for name in d["function_schema"]["parameters"]["properties"]:
            assert any("/properties/" + name in p for p in pointers)
        for name in d["result_protocols"]["declared_results"]:
            assert "/result_protocols/declared_results/" + name in pointers
        assert any("idempotency" in p for p in pointers)
