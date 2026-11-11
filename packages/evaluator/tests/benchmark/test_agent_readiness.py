"""原始公开输入 → 真实 Provider / Agent 的离线 reference 回归。"""

import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


def request_fixture():
    from eval_contracts.full_readiness import FullRequest

    # Use checked-in frozen fixture as test source, never depend on output/ artifacts.
    delivery = (
        ROOT
        / "packages/dataset-builder/tests/fixtures"
        / "full_tools_fixture_v1_full_eval_20261020"
    )
    from .test_operation_readiness import request_fixture as operations_request

    request = operations_request()
    docs = []
    for path in (delivery / "source_delivery/bundle").rglob("*.json"):
        doc = json.loads(path.read_text())
        if isinstance(doc, dict) and "snapshot_id" in doc and "snapshot_type" in doc:
            docs.append(doc)
    return FullRequest(
        **{
            **request.model_dump(),
            "schema_version": "builder-full-readiness-v3",
            "capability_documents": docs,
        }
    )


def test_49_intent_and_early_stop_cases_execute_real_provider():
    pytest.importorskip("minimal_agent")
    from eval_contracts.agent_readiness import (
        agent_checks,
        agent_plan_for,
        reference_context,
    )
    from eval_framework.benchmark.agent_readiness import AgentReferenceExecutor

    request = request_fixture()
    executor = AgentReferenceExecutor(
        reference_context(request), ROOT / "examples/mini_agent"
    )
    counts = Counter()
    failures = []
    for case in request.cases:
        plan = agent_plan_for(case, request)
        if plan is None or plan.category not in {"intent_module", "early_stop"}:
            continue
        row = executor.execute(case.case_id, plan)
        assert row.evidence_complete and not row.errors, (case.case_id, row)
        checks = agent_checks(case, plan, row, request)
        if not all(checks.values()):
            failures.append(
                (
                    case.case_id,
                    {k: v for k, v in checks.items() if not v},
                    row.observations.get("module_output"),
                )
            )
        counts[plan.category] += 1
    assert counts == {"intent_module": 28, "early_stop": 21}
    # Wiring must expose these existing runtime / definition discrepancies.
    assert {item[0] for item in failures} == {
        "I-intent.add_backpack_gift.9101ca688a883c",
        "I-intent.query_gift.296ed04ad02b7a",
        "I-intent.query_pool.a9686242d0217c",
    }, failures


def test_21_module_stimuli_reach_real_events():
    pytest.importorskip("minimal_agent")
    from eval_contracts.agent_readiness import (
        agent_checks,
        agent_plan_for,
        reference_context,
    )
    from eval_framework.benchmark.agent_readiness import AgentReferenceExecutor

    request = request_fixture()
    executor = AgentReferenceExecutor(
        reference_context(request), ROOT / "examples/mini_agent"
    )
    selected = [(c, agent_plan_for(c, request)) for c in request.cases]
    selected = [(c, p) for c, p in selected if p and p.category == "module_event"]
    assert len(selected) == 21
    for case, plan in selected:
        row = executor.execute(case.case_id, plan)
        checks = agent_checks(case, plan, row, request)
        assert all(checks.values()), (case.case_id, row, checks)


def test_27_chains_have_tool_and_ordered_node_evidence():
    pytest.importorskip("minimal_agent")
    from eval_contracts.agent_readiness import (
        agent_checks,
        agent_plan_for,
        reference_context,
    )
    from eval_framework.benchmark.agent_readiness import AgentReferenceExecutor

    request = request_fixture()
    executor = AgentReferenceExecutor(
        reference_context(request), ROOT / "examples/mini_agent"
    )
    selected = [(c, agent_plan_for(c, request)) for c in request.cases]
    selected = [(c, p) for c, p in selected if p and p.category == "agent_chain"]
    assert len(selected) == 27
    assert Counter(p.branch for _, p in selected) == {"normal": 12, "error": 15}
    for case, plan in selected:
        row = executor.execute(case.case_id, plan)
        checks = agent_checks(case, plan, row, request)
        assert all(checks.values()), (case.case_id, row, checks)
        assert checks["ordered_chain_nodes"]


@pytest.mark.parametrize(
    "damage", ["events", "order", "handler", "state", "candidate", "manifest", "node"]
)
def test_missing_or_tampered_chain_evidence_fails(damage):
    pytest.importorskip("minimal_agent")
    from eval_contracts.agent_readiness import (
        agent_checks,
        agent_plan_for,
        reference_context,
    )
    from eval_framework.benchmark.agent_readiness import AgentReferenceExecutor

    request = request_fixture()
    case = next(
        c
        for c in request.cases
        if c.payload.get("input", {}).get("operation") == "agent_run"
        and c.payload["input"]["branch"] == "normal"
    )
    plan = agent_plan_for(case, request)
    row = AgentReferenceExecutor(
        reference_context(request), ROOT / "examples/mini_agent"
    ).execute(case.case_id, plan)
    if damage == "events":
        row.observations["events"] = []
    elif damage == "order":
        row.observations["events"].reverse()
    elif damage == "handler":
        row.observations["handler_calls"] = []
    elif damage == "state":
        row.before_state = {}
        row.after_state = {}
    elif damage == "candidate":
        row.observations["model_interactions"][0]["output"]["intent"] = "unsupported"
    elif damage == "manifest":
        row.observations["evidence_manifest"]["written_count"] = 0
    elif damage == "node":
        row.observations["chain_nodes"] = []
    assert not all(agent_checks(case, plan, row, request).values())


def test_reference_plan_does_not_read_oracle():
    from eval_contracts.agent_readiness import agent_plan_for

    request = request_fixture()
    for case in request.cases:
        before = agent_plan_for(case, request)
        case.payload["oracle"] = {"PRIVATE_ORACLE_SENTINEL": "unsupported secret"}
        assert agent_plan_for(case, request) == before


def test_removed_fault_fails_original_error_oracle():
    pytest.importorskip("minimal_agent")
    from eval_contracts.agent_readiness import (
        agent_checks,
        agent_plan_for,
        reference_context,
    )
    from eval_framework.benchmark.agent_readiness import AgentReferenceExecutor

    request = request_fixture()
    case = next(
        c
        for c in request.cases
        if c.payload.get("input", {}).get("operation") == "agent_run"
        and c.payload["input"]["branch"] == "error"
    )
    plan = agent_plan_for(case, request)
    row = AgentReferenceExecutor(
        reference_context(request), ROOT / "examples/mini_agent"
    ).execute(case.case_id, plan.model_copy(update={"fault": "none"}))
    assert not all(agent_checks(case, plan, row, request).values())


def test_full_inspect_run_has_365_observations_and_private_oracle_is_absent(tmp_path):
    pytest.importorskip("minimal_agent")
    from eval_contracts.agent_readiness import agent_checks, agent_plan_for
    from eval_framework.benchmark.full_readiness import run
    from inspect_ai.log import read_eval_log

    request = request_fixture()
    case = next(
        c
        for c in request.cases
        if c.payload.get("input", {}).get("operation") == "agent_run"
    )
    case.payload["oracle"]["checks"][0]["expected"] = "PRIVATE_ORACLE_SENTINEL"
    path = tmp_path / "request.json"
    path.write_text(request.model_dump_json())
    evidence = run(path, tmp_path / "logs", ROOT / "examples/mini_agent")
    assert len(evidence.results) == 365
    assert all(r.evidence_complete and not r.errors for r in evidence.results)
    row = next(r for r in evidence.results if r.case_id == case.case_id)
    assert not all(
        agent_checks(case, agent_plan_for(case, request), row, request).values()
    )
    assert len(list((tmp_path / "logs/business").glob("*/trace.inspect.json"))) == 97
    for path in (tmp_path / "logs").rglob("*"):
        if path.suffix == ".eval":
            log = read_eval_log(path)
            assert "PRIVATE_ORACLE_SENTINEL" not in log.model_dump_json()
        elif path.suffix == ".json":
            assert "PRIVATE_ORACLE_SENTINEL" not in path.read_text()


def test_runtime_intent_semantic_drift_is_rejected():
    pytest.importorskip("minimal_agent")
    from eval_contracts.agent_readiness import reference_context
    from eval_framework.benchmark.agent_readiness import AgentReferenceExecutor

    request = request_fixture()
    doc = next(
        d
        for d in request.capability_documents
        if d["snapshot_id"] == "intent.query_user"
    )
    doc["parameter_semantics"]["execution_semantics"] = {
        "unsupported_semantics": "changed"
    }
    with pytest.raises(ValueError, match="semantics"):
        AgentReferenceExecutor(reference_context(request), ROOT / "examples/mini_agent")


@pytest.mark.parametrize(
    "damage",
    [
        "terminal_status",
        "terminal_output",
        "run_id",
        "model_missing",
        "model_output",
        "final_text",
    ],
)
def test_contradictory_trace_and_model_evidence_fails(damage):
    pytest.importorskip("minimal_agent")
    from eval_contracts.agent_readiness import (
        agent_checks,
        agent_plan_for,
        reference_context,
    )
    from eval_framework.benchmark.agent_readiness import AgentReferenceExecutor

    request = request_fixture()
    case = next(
        c
        for c in request.cases
        if c.payload.get("input", {}).get("operation") == "agent_run"
        and c.payload["input"]["branch"] == "normal"
    )
    plan = agent_plan_for(case, request)
    row = AgentReferenceExecutor(
        reference_context(request), ROOT / "examples/mini_agent"
    ).execute(case.case_id, plan)
    events = row.observations["events"]
    if damage == "terminal_status":
        events[-1]["payload"]["status"] = "FAILED"
    elif damage == "terminal_output":
        next(e for e in events if e["event_type"] == "tool_succeeded")["payload"][
            "output"
        ] = {"success": False}
    elif damage == "run_id":
        for e in events:
            e["run_id"] = "different-run"
    elif damage == "model_missing":
        row.observations["model_interactions"] = row.observations["model_interactions"][
            :1
        ]
    elif damage == "model_output":
        row.observations["model_interactions"][1]["output"]["arguments"] = {}
    elif damage == "final_text":
        next(e for e in events if e["event_type"] == "final_response_generated")[
            "payload"
        ]["response"] = "unrelated text"
    assert not all(agent_checks(case, plan, row, request).values())
