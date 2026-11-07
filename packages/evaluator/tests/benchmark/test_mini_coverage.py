"""Coverage fixtures exercise real tool execution without network calls."""

import pytest

pytest.importorskip("minimal_agent")


def test_read_fixture_filters_gifts_and_rejects_disallowed_calls():
    from minimal_agent.runtime.tool_registry import ToolNotAllowedError

    from eval_framework.providers.mini_agent.benchmark_environment import (
        read_fixture_registry,
    )

    registry = read_fixture_registry(
        {"kind": "read_fixture_v2", "gifts": [{"gift_id": 7, "gift_name": "星河"}]},
        frozenset({"query_gift_info"}),
    )
    args = dict(gift_id=7, gift_ids=None, gift_name=None, limit=None)
    assert registry.invoke("query_gift_info", args).data == {
        "gifts": [{"gift_id": 7, "gift_name": "星河"}]
    }
    assert registry.invoke("query_gift_info", {**args, "gift_id": 8}).code == "EMPTY"
    with pytest.raises(ToolNotAllowedError):
        registry.invoke("query_gift_info", args, allowed_tools=frozenset())


@pytest.mark.parametrize(
    "mode,code",
    [("business_failure", "BUSINESS_FAILURE"), ("rate_limit", "RATE_LIMITED")],
)
def test_read_fixture_returns_business_failure(mode, code):
    from eval_framework.providers.mini_agent.benchmark_environment import (
        read_fixture_registry,
    )

    registry = read_fixture_registry(
        {"kind": "read_fixture_v2", "fault": {"tool": "query_user_info", "mode": mode}},
        frozenset({"query_user_info"}),
    )
    result = registry.invoke(
        "query_user_info", dict(user_id=1, room_id=None, phone=None, email=None)
    )
    assert result.success is False and result.code == code and result.data == {}


@pytest.mark.parametrize(
    "mode,error", [("timeout", TimeoutError), ("execution_failure", RuntimeError)]
)
def test_read_fixture_raises_real_failure(mode, error):
    from eval_framework.providers.mini_agent.benchmark_environment import (
        read_fixture_registry,
    )

    registry = read_fixture_registry(
        {"kind": "read_fixture_v2", "fault": {"tool": "query_user_info", "mode": mode}},
        frozenset({"query_user_info"}),
    )
    with pytest.raises(error, match="fixture"):
        registry.invoke(
            "query_user_info", dict(user_id=1, room_id=None, phone=None, email=None)
        )


def test_invalid_fault_configuration_fails_before_execution():
    from eval_framework.providers.mini_agent.benchmark_environment import (
        read_fixture_registry,
    )

    with pytest.raises(ValueError, match="fault"):
        read_fixture_registry(
            {"fault": {"tool": "query_user_info", "mode": "typo"}},
            frozenset({"query_user_info"}),
        )


def test_versioned_coverage_keeps_oracles_private_and_historical_data_unchanged(
    tmp_path,
):
    import json
    from pathlib import Path

    from eval_framework.benchmark.mini_coverage import build_coverage_dataset
    from eval_framework.benchmark.provider_tasks import (
        load_provider_tasks,
        public_execution,
    )

    root = Path(__file__).resolve().parents[4]
    base = root / "data/benchmarks/mini-agent-v1.0.1"
    before = (base / "tasks.jsonl").read_bytes()
    output = tmp_path / "new"
    build_coverage_dataset(output, base)
    tasks = load_provider_tasks(output)
    original = {t["id"]: t for t in load_provider_tasks(base)}
    for task in tasks:
        if task["id"] in original:
            assert task["oracle"] == original[task["id"]]["oracle"]
        public = public_execution(task)
        assert set(public) == {"execution", "scope", "environment"}
        assert "oracle" not in json.dumps(public)
    assert (base / "tasks.jsonl").read_bytes() == before
    coverage = json.loads((output / "coverage.json").read_text())
    assert len(coverage["smoke_case_ids"]) == len(set(coverage["smoke_case_ids"])) == 30
    assert set(coverage["smoke_case_ids"]) <= {t["id"] for t in tasks}
    assert {
        "tool_timeout",
        "tool_failure",
        "business_failure",
        "tool_restriction",
        "duplicate_confirmation",
    } <= set(coverage["scenarios"])
    assert all(value["case_ids"] for value in coverage["scenarios"].values())
    assert any(x["id"] == "rbac" for x in coverage["unsupported"])
    with pytest.raises(ValueError, match="immutable"):
        build_coverage_dataset(output, base)


@pytest.mark.parametrize(
    "mode,terminal,case_id",
    [
        ("timeout", "tool_timeout", "MINI-FAULT-001"),
        ("execution_failure", "tool_failed", "MINI-FAULT-002"),
    ],
)
def test_fault_worker_preserves_trace_and_deepeval_detects_wrong_expectation(
    tmp_path, mode, terminal, case_id
):
    import copy
    from pathlib import Path

    from minimal_agent.contracts.agent import FunctionCallItem, IntentResult

    from eval_framework.benchmark.mini_adapter import project_events
    from eval_framework.benchmark.mini_coverage import build_coverage_dataset
    from eval_framework.benchmark.mini_scoring import MiniAgentDomain
    from eval_framework.benchmark.mini_worker import execute_public
    from eval_framework.benchmark.provider_tasks import (
        load_provider_tasks,
        public_execution,
    )
    from tests.support.model_client import DeterministicModelClient

    root = Path(__file__).resolve().parents[4]
    dataset = tmp_path / "dataset"
    build_coverage_dataset(dataset, root / "data/benchmarks/mini-agent-v1.0.1")
    task = next(t for t in load_provider_tasks(dataset) if t["id"] == case_id)
    steps = [
        IntentResult(
            intent="query_user",
            status="READY",
            next_action="CALL_TOOL",
            parameters={"user_id": 91001},
            reason="test",
        ),
        FunctionCallItem(
            type="function_call",
            call_id="fault",
            name="query_user_info",
            arguments=dict(user_id=91001, room_id=None, email=None, phone=None),
        ),
    ]
    result = execute_public(
        public_execution(task),
        dataset / "capability_bundle",
        tmp_path / "evidence",
        lambda _: DeterministicModelClient(steps),
    )
    assert result["evidence_complete"], result
    assert result["adapter_output"]["observations"]["completed_turns"] == 1
    assert result["adapter_output"]["turns"][0]["status"] == "FAILED"
    assert any(
        e["event_type"] == terminal for e in result["adapter_output"]["trace_events"]
    )
    result["events"] = project_events(result["adapter_output"]) + [
        {"id": "offline-generation", "type": "generation"}
    ]
    tool_event = next(e for e in result["events"] if e["type"] == "tool")
    assert tool_event["error"] and tool_event["tool_call_id"] == "fault"
    turn = next(e for e in result["events"] if e["type"] == "turn")
    assert turn["input"]["user_input"] == task["prompt"]
    assert turn["output"]["status"] == "FAILED"
    domain = MiniAgentDomain(dataset)
    assessment = domain.score_task(task, result)
    assert assessment["verdict"] == "PASS", [
        m for m in assessment["metrics"] if m["success"] is not True
    ]
    wrong = copy.deepcopy(task)
    wrong["oracle"]["expected_agent_status"] = "SUCCESS"
    assert domain.score_task(wrong, result)["verdict"] == "FAIL"


def test_continuation_revision_requires_three_completed_turns(tmp_path):
    import json
    from pathlib import Path

    from eval_framework.benchmark.mini_coverage import build_continuation_dataset
    from eval_framework.benchmark.provider_tasks import load_provider_tasks
    from eval_framework.observation_assertions import evaluate_observations

    base = Path(__file__).resolve().parents[4] / "data/benchmarks/mini-agent-v1.1.0"
    before = (base / "manifest.json").read_bytes()
    output = tmp_path / "revision"
    build_continuation_dataset(output, base)
    row = next(t for t in load_provider_tasks(output) if t["id"] == "MINI-E2E-007")
    assert row["execution"]["adapter_input"] == {"continue_after_terminal": True}
    spec = next(
        c
        for c in row["oracle"]["evaluation"]["checks"]
        if c["name"] == "observations_match"
    )
    assert evaluate_observations({"completed_turns": 2}, spec["config"])[0] is False
    assert evaluate_observations({"completed_turns": 3}, spec["config"])[0] is True
    assert json.loads((output / "manifest.json").read_text())["version"] == "1.1.1"
    assert (base / "manifest.json").read_bytes() == before
