"""Schema 与真实工具执行的离线集成回归。"""

import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
DELIVERY = (
    ROOT
    / "packages/dataset-builder/tests/fixtures/full_tools_fixture_v1_full_eval_20261020"
)


def request_fixture():
    from eval_contracts.full_readiness import FullCase, FullRequest
    from eval_contracts.readiness import digest_bytes

    raw = (DELIVERY / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    cases = []
    for ds in manifest["datasets"]:
        if ds["definition_kind"] == "behavior_case":
            cases.extend(
                FullCase(case_id=r["case_id"], source_path=ds["path"], payload=r)
                for r in map(
                    json.loads, (DELIVERY / ds["path"]).read_text().splitlines()
                )
            )
    schemas = {}
    for kind, field in [("tools", "function_schema"), ("intents", "parameters_schema")]:
        for path in (DELIVERY / "source_delivery/bundle" / kind).glob("*.json"):
            doc = json.loads(path.read_text())
            schemas[f"{kind[:-1]}.{path.stem}"] = doc[field]
    return FullRequest(
        schema_version="builder-full-readiness-v2",
        source_manifest_sha256=digest_bytes(raw),
        bundle_sha256=manifest["bundle_sha256"],
        source_files=manifest["files_sha256"],
        definition_counts=manifest["definition_counts"],
        tool_schema={},
        target_schemas=schemas,
        cases=cases,
    )


def test_schema_bindings_execute_without_mini_agent_or_handler(monkeypatch):
    from eval_contracts.operation_readiness import operation_checks, plan_for
    from eval_framework.benchmark.operation_readiness import execute_plan

    request = request_fixture()
    plans = [(c, plan_for(c, request.target_schemas)) for c in request.cases]
    schemas = [(c, p) for c, p in plans if p and p.operation == "validate_arguments"]
    assert len(schemas) == 233

    def forbidden():
        raise AssertionError("schema validation must not create a fixture")

    for case, plan in schemas:
        row = execute_plan(case.case_id, plan, forbidden)
        assert all(operation_checks(case, plan, row).values())
        assert row.tool_calls == []
    assert {
        execute_plan(c.case_id, p, forbidden).observations["schema_valid"]
        for c, p in schemas
    } == {True, False}


def test_all_six_tools_really_execute_with_isolation():
    pytest.importorskip("minimal_agent")
    from eval_contracts.operation_readiness import operation_checks, plan_for
    from eval_framework.benchmark.full_readiness import fixture_class
    from eval_framework.benchmark.operation_readiness import execute_plan

    request = request_fixture()
    factory = fixture_class(ROOT / "examples/mini_agent")
    counts = Counter()
    for case in request.cases:
        plan = plan_for(case, request.target_schemas)
        if plan is None or plan.operation == "validate_arguments":
            continue
        row = execute_plan(case.case_id, plan, factory)
        checks = operation_checks(case, plan, row)
        assert all(checks.values()), (case.case_id, row, checks)
        counts[plan.operation] += 1
        # Each invocation starts afresh, even sequences sharing state internally.
        assert execute_plan(case.case_id, plan, factory) == row
    assert counts == {
        "invoke_tool": 26,
        "validate_selection_modes": 7,
        "authorization_sequence": 1,
        "idempotency_sequence": 1,
    }


def test_unknown_preconditions_and_remote_schemas_fail_closed():
    from eval_contracts.operation_readiness import plan_for, schema_validator

    request = request_fixture()
    case = next(
        c
        for c in request.cases
        if c.payload.get("input", {}).get("operation") == "invoke_tool"
    )
    case.payload["preconditions"].append({"kind": "unknown_side_effect"})
    assert plan_for(case, request.target_schemas) is None
    with pytest.raises(ValueError, match="external"):
        schema_validator({"$ref": "https://example.invalid/private-schema"})


def test_oracle_is_not_execution_input_and_missing_values_fail():
    from eval_contracts.operation_readiness import operation_checks, plan_for
    from eval_framework.benchmark.operation_readiness import execute_plan

    request = request_fixture()
    case = next(
        c
        for c in request.cases
        if c.payload.get("input", {}).get("operation") == "validate_arguments"
    )
    plan = plan_for(case, request.target_schemas)
    row = execute_plan(case.case_id, plan)
    case.payload["oracle"] = {
        "checks": [{"op": "equals", "actual": "tool_result.missing", "expected": None}]
    }
    assert plan_for(case, request.target_schemas) == plan
    assert not operation_checks(case, plan, row)["oracle_0"]
    case.payload["oracle"]["checks"][0]["op"] = "unknown_predicate"
    assert not operation_checks(case, plan, row)["oracle_0"]


def test_tampered_observed_fixture_is_rejected():
    pytest.importorskip("minimal_agent")
    from eval_contracts.operation_readiness import operation_checks, plan_for
    from eval_framework.benchmark.full_readiness import fixture_class
    from eval_framework.benchmark.operation_readiness import execute_plan

    request = request_fixture()
    case = next(
        c
        for c in request.cases
        if c.payload.get("input", {}).get("operation") == "invoke_tool"
    )
    plan = plan_for(case, request.target_schemas)
    row = execute_plan(case.case_id, plan, fixture_class(ROOT / "examples/mini_agent"))
    row.observations["initial_state"] = {"users": {"999": {"user_id": 999}}}
    assert not all(operation_checks(case, plan, row).values())


def test_inspect_operations_keep_private_oracles_out_of_logs(tmp_path):
    pytest.importorskip("minimal_agent")
    from eval_contracts.operation_readiness import operation_checks, plan_for
    from eval_framework.benchmark.full_readiness import run
    from inspect_ai.log import read_eval_log

    request = request_fixture()
    selected = next(
        c
        for c in request.cases
        if c.payload.get("input", {}).get("operation") == "invoke_tool"
        and c.payload["target_id"] == "tool.query_user_info"
    )
    selected.payload["oracle"]["checks"] = [
        {
            "op": "equals",
            "actual": "tool_result.code",
            "expected": "PRIVATE_ORACLE_SENTINEL",
        }
    ]
    path = tmp_path / "request.json"
    path.write_text(request.model_dump_json())
    evidence = run(path, tmp_path / "logs", ROOT / "examples/mini_agent")
    assert len(evidence.results) == 268
    assert all(r.evidence_complete and not r.errors for r in evidence.results)
    by_id = {r.case_id: r for r in evidence.results}
    assert not operation_checks(
        selected, plan_for(selected, request.target_schemas), by_id[selected.case_id]
    )["oracle_0"]
    for path in (tmp_path / "logs").glob("*.eval"):
        log = read_eval_log(path)
        assert len(log.samples) == 268
        for sample in log.samples:
            assert "PRIVATE_ORACLE_SENTINEL" not in sample.model_dump_json()
            assert sample.target == ""


def test_selection_validation_never_invokes_handlers():
    pytest.importorskip("minimal_agent")
    from eval_contracts.operation_readiness import operation_checks, plan_for
    from eval_framework.benchmark.full_readiness import fixture_class
    from eval_framework.benchmark.operation_readiness import execute_plan

    base = fixture_class(ROOT / "examples/mini_agent")

    class GuardedFixture(base):
        def registry(self):
            registry = super().registry()

            def forbidden(**kwargs):
                raise AssertionError("handler must not run during validation")

            for definition in registry.definitions:
                definition.handler = forbidden
            return registry

    request = request_fixture()
    cases = [
        c
        for c in request.cases
        if c.payload.get("input", {}).get("operation") == "validate_selection_modes"
    ]
    for case in cases:
        plan = plan_for(case, request.target_schemas)
        row = execute_plan(case.case_id, plan, GuardedFixture)
        assert all(operation_checks(case, plan, row).values())


def test_runtime_schema_drift_is_an_execution_error():
    pytest.importorskip("minimal_agent")
    from eval_contracts.operation_readiness import operation_checks, plan_for
    from eval_framework.benchmark.full_readiness import fixture_class
    from eval_framework.benchmark.operation_readiness import execute_plan

    request = request_fixture()
    case = next(
        c
        for c in request.cases
        if c.payload.get("input", {}).get("operation") == "invoke_tool"
    )
    plan = plan_for(case, request.target_schemas)
    plan.contract_schema["parameters"]["additionalProperties"] = True
    row = execute_plan(case.case_id, plan, fixture_class(ROOT / "examples/mini_agent"))
    assert row.status == "error"
    assert "runtime tool schema differs" in row.errors[0]
    assert not all(operation_checks(case, plan, row).values())


@pytest.mark.parametrize(
    "field", ["tool_calls", "states", "setup_calls", "authorization_after_step"]
)
def test_incomplete_sequence_evidence_cannot_pass(field):
    pytest.importorskip("minimal_agent")
    from eval_contracts.operation_readiness import operation_checks, plan_for
    from eval_framework.benchmark.full_readiness import fixture_class
    from eval_framework.benchmark.operation_readiness import execute_plan

    request = request_fixture()
    case = next(
        c
        for c in request.cases
        if c.payload.get("input", {}).get("operation") == "authorization_sequence"
    )
    plan = plan_for(case, request.target_schemas)
    row = execute_plan(case.case_id, plan, fixture_class(ROOT / "examples/mini_agent"))
    if field == "tool_calls":
        row.tool_calls.pop()
    else:
        row.observations.pop(field)
    assert not all(operation_checks(case, plan, row).values())


@pytest.mark.parametrize(
    "operation", ["authorization_sequence", "idempotency_sequence"]
)
def test_empty_or_disconnected_state_evidence_fails(operation):
    pytest.importorskip("minimal_agent")
    from eval_contracts.operation_readiness import operation_checks, plan_for
    from eval_framework.benchmark.full_readiness import fixture_class
    from eval_framework.benchmark.operation_readiness import execute_plan

    request = request_fixture()
    case = next(
        c
        for c in request.cases
        if c.payload.get("input", {}).get("operation") == operation
    )
    plan = plan_for(case, request.target_schemas)
    row = execute_plan(case.case_id, plan, fixture_class(ROOT / "examples/mini_agent"))
    row.before_state = {}
    row.after_state = {}
    row.observations["states"] = [{}, {}, {}]
    assert not all(operation_checks(case, plan, row).values())


def test_setup_state_cannot_be_omitted():
    pytest.importorskip("minimal_agent")
    from eval_contracts.operation_readiness import operation_checks, plan_for
    from eval_framework.benchmark.full_readiness import fixture_class
    from eval_framework.benchmark.operation_readiness import execute_plan

    request = request_fixture()
    case = next(
        c
        for c in request.cases
        if any(p.get("steps") for p in c.payload.get("preconditions", []))
    )
    plan = plan_for(case, request.target_schemas)
    row = execute_plan(case.case_id, plan, fixture_class(ROOT / "examples/mini_agent"))
    row.observations.pop("setup_states", None)
    assert not all(operation_checks(case, plan, row).values())


@pytest.mark.parametrize(
    "operation",
    [
        "validate_arguments",
        "invoke_tool",
        "authorization_sequence",
        "idempotency_sequence",
    ],
)
@pytest.mark.parametrize("mutation", ["precondition", "input", "steps"])
def test_malformed_case_is_unbound(operation, mutation):
    from eval_contracts.operation_readiness import plan_for

    request = request_fixture()
    case = next(
        c
        for c in request.cases
        if c.payload.get("input", {}).get("operation") == operation
    )
    if mutation == "precondition":
        case.payload["preconditions"] = [None]
    elif mutation == "input":
        case.payload["input"] = []
    else:
        case.payload["input"]["steps"] = [None, None, None]
    assert plan_for(case, request.target_schemas) is None
