from test_full_generation_inventory import load
from test_full_generation_planner import plan


def generation():
    from dataset_builder.full_generation.contract_cases import compile_contract_cases
    from dataset_builder.full_generation.intent_cases import compile_intent_cases
    from dataset_builder.full_generation.models import GenerationResult
    from dataset_builder.full_generation.runtime_cases import compile_runtime_cases

    inv = load()
    slots, blockers = plan(inv)
    runtime, extra = compile_runtime_cases(inv, slots)
    return GenerationResult(
        inventory=inv,
        slots=slots,
        cases=compile_contract_cases(inv, slots)
        + compile_intent_cases(inv, slots)
        + runtime,
        blockers=blockers + extra,
    )


def validate(result):
    from dataset_builder.full_generation.validation import validate_generation

    return validate_generation(result)


def test_complete_generation_valid():
    report = validate(generation())
    assert report["valid"], report["issues"][:10]
    assert report["coverage"]["target_count"] == 23


def test_uncovered_slot_fails():
    r = generation()
    c = next(c for c in r.cases if c.execution_readiness == "not_run")
    r.cases.remove(c)
    assert not validate(r)["valid"]


def test_dangling_case_reference_fails():
    r = generation()
    r.cases[0].slot_id = "absent"
    assert not validate(r)["valid"]


def test_duplicate_id_fails():
    r = generation()
    r.cases[1].payload["case_id"] = r.cases[0].payload["case_id"]
    assert not validate(r)["valid"]


def test_changed_source_fails():
    r = generation()
    r.inventory.external_bindings["manifest.json"] = "0" * 64
    assert not validate(r)["valid"]


def test_static_pass_never_means_runtime_pass():
    report = validate(generation())
    assert report["runtime_execution"] == "NOT_RUN"
    assert report["approval"] == "PENDING"


def test_indirect_coverage_not_counted_as_direct():
    r = generation()
    report = validate(r)
    assert report["counts"]["coverage_mode"]["direct"] == sum(
        c.coverage_mode == "direct" for c in r.cases
    )


def test_contract_jsonl_not_sent_to_evalcase_loader():
    r = generation()
    assert any(c.dataset_format == "capability_contract_case" for c in r.cases)
    assert validate(r)["valid"]
