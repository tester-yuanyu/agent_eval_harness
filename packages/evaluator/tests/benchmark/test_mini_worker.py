# ruff: noqa: E402
from pathlib import Path

import pytest

pytest.importorskip("minimal_agent")
from minimal_agent.contracts.agent import IntentResult

from eval_framework.benchmark.mini_adapter import project_events
from eval_framework.benchmark.mini_dataset import build_dataset
from eval_framework.benchmark.mini_worker import execute_public
from eval_framework.benchmark.package_sandbox import package_inputs
from eval_framework.benchmark.provider_tasks import (
    load_provider_tasks,
    public_execution,
)
from tests.support.model_client import DeterministicModelClient

ROOT = Path(__file__).resolve().parents[4]


def test_worker_uses_independent_persisted_evidence_and_rejects_oracle(tmp_path):
    dataset = tmp_path / "dataset"
    build_dataset(dataset, ROOT)
    task = public_execution(load_provider_tasks(dataset)[0])
    intent = IntentResult(
        intent="query_user",
        status="READY",
        next_action="CALL_TOOL",
        parameters={"user_id": 91001},
        reason="test",
    )
    result = execute_public(
        task,
        dataset / "capability_bundle",
        tmp_path / "evidence",
        lambda _: DeterministicModelClient([intent]),
    )
    assert result["status"] == "completed", result
    assert result["evidence_complete"] is True
    assert (tmp_path / "evidence/trace.inspect.json").exists()
    events = project_events(result["adapter_output"])
    assert any(e["name"] == "intent_decided" for e in events)
    assert any(e["type"] == "turn" for e in events)
    with pytest.raises(ValueError, match="public"):
        execute_public(
            {**task, "oracle": {}},
            dataset / "capability_bundle",
            tmp_path / "unused",
            None,
        )


def test_container_context_excludes_private_dataset_and_environment(tmp_path):
    dataset = tmp_path / "dataset"
    build_dataset(dataset, ROOT)
    files = package_inputs(
        {"evaluator": ROOT / "packages/evaluator"}, dataset / "capability_bundle"
    )
    assert any("mini_worker.py" in key for key in files)
    assert not any(
        "mini_dataset.py" in key or "tasks.jsonl" in key or ".env" in key
        for key in files
    )


def test_query_tool_trace_and_gift_state_survive_worker_boundary(tmp_path):
    from minimal_agent.contracts.agent import FinalResponseItem, FunctionCallItem

    from eval_framework.benchmark.mini_scoring import MiniAgentDomain

    dataset = tmp_path / "dataset"
    build_dataset(dataset, ROOT)
    tasks = load_provider_tasks(dataset)
    query = next(t for t in tasks if t["id"] == "MINI-CHAIN-001")
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
            call_id="query-1",
            name="query_user_info",
            arguments={"user_id": 91001, "room_id": None, "email": None, "phone": None},
        ),
        FinalResponseItem(type="message", content="测试用户甲"),
    ]
    result = execute_public(
        public_execution(query),
        dataset / "capability_bundle",
        tmp_path / "query",
        lambda _: DeterministicModelClient(steps),
    )
    assert result["evidence_complete"], result
    assert (
        result["adapter_output"]["turns"][0]["tool_calls"][0]["output"]["data"][
            "users"
        ][0]["name"]
        == "测试用户甲"
    )
    events = project_events(result["adapter_output"])
    assert sum(e["type"] == "tool" and not e["incomplete"] for e in events) == 1
    result["events"] = events + [{"id": "test-generation", "type": "generation"}]
    assert MiniAgentDomain(dataset).score_task(query, result)["verdict"] == "PASS"

    gift = next(t for t in tasks if t["id"] == "MINI-E2E-001")
    result = execute_public(
        public_execution(gift),
        dataset / "capability_bundle",
        tmp_path / "gift",
        lambda _: DeterministicModelClient(
            [
                IntentResult(
                    intent="add_backpack_gift",
                    status="NEED_CONFIRMATION",
                    next_action="ASK_CONFIRMATION",
                    parameters={
                        "user_id": 91001,
                        "gift_id": 300101,
                        "num": 2,
                        "duration_days": 7,
                        "environment": "qa",
                    },
                    reason="confirm",
                )
            ]
        ),
    )
    assert result["evidence_complete"], result
    assert result["adapter_output"]["snapshot"]["grant_count"] == 0
    result["events"] = project_events(result["adapter_output"]) + [
        {"id": "test-generation", "type": "generation"}
    ]
    assessment = MiniAgentDomain(dataset).score_task(gift, result)
    assert assessment["verdict"] == "PASS", [
        m for m in assessment["metrics"] if m["success"] is not True
    ]


def test_empty_query_cannot_pass_with_fabricated_answer(tmp_path):
    from minimal_agent.contracts.agent import FinalResponseItem, FunctionCallItem

    from eval_framework.benchmark.mini_scoring import MiniAgentDomain

    dataset = tmp_path / "dataset"
    build_dataset(dataset, ROOT)
    task = next(t for t in load_provider_tasks(dataset) if t["id"] == "MINI-CHAIN-006")
    steps = [
        IntentResult(
            intent="query_user",
            status="READY",
            next_action="CALL_TOOL",
            parameters={"user_id": 91999},
            reason="test",
        ),
        FunctionCallItem(
            type="function_call",
            call_id="empty",
            name="query_user_info",
            arguments={"user_id": 91999, "room_id": None, "email": None, "phone": None},
        ),
        FinalResponseItem(type="message", content="找到了测试用户甲"),
    ]
    result = execute_public(
        public_execution(task),
        dataset / "capability_bundle",
        tmp_path / "empty",
        lambda _: DeterministicModelClient(steps),
    )
    result["events"] = project_events(result["adapter_output"]) + [
        {"id": "generation", "type": "generation"}
    ]
    metrics = MiniAgentDomain(dataset).score_task(task, result)["metrics"]
    assert any(
        m["name"] == "response_consistent" and m["success"] is False for m in metrics
    )


def test_real_provider_modes_have_explicit_report_labels():
    from eval_framework.benchmark.report import _mode

    for mode in ("mixed_execution", "real_model_intent", "real_agent_test_environment"):
        assert _mode({"mode": mode, "identity": {"offline": False}})[0] == "real"


def test_cancelled_worker_preserves_disk_events_and_model_evidence(
    tmp_path, monkeypatch
):
    import json
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    import anyio
    import inspect_ai.agent
    import inspect_ai.log
    import inspect_ai.util

    from eval_framework.benchmark import mini_adapter

    dataset = tmp_path / "dataset"
    build_dataset(dataset, ROOT)
    task = public_execution(load_provider_tasks(dataset)[0])
    intent = IntentResult(
        intent="query_user",
        status="READY",
        next_action="CALL_TOOL",
        parameters={"user_id": 91001},
        reason="test",
    )
    execute_public(
        task,
        dataset / "capability_bundle",
        tmp_path / "source",
        lambda _: DeterministicModelClient([intent]),
    )
    content = (tmp_path / "source/trace.inspect.json").read_text()
    adapter = mini_adapter.MiniAgentBenchmarkAdapter(
        {
            "repository_root": str(ROOT),
            "capability_bundle": str(dataset / "capability_bundle"),
        }
    )
    adapter.output = tmp_path / "run"
    observed = {}

    async def run():
        with anyio.CancelScope() as scope:

            class Sandbox:
                async def exec(self, command, **kwargs):
                    if "-c" in command:
                        return SimpleNamespace(
                            success=True,
                            stdout=json.dumps({"python": "test", "packages": {}}),
                        )
                    scope.cancel()
                    await anyio.lowlevel.checkpoint()

                async def read_file(self, path):
                    await anyio.lowlevel.checkpoint()
                    return content

            @asynccontextmanager
            async def bridge(**kwargs):
                yield SimpleNamespace(port=1234)

            async def model_events(*args):
                await anyio.lowlevel.checkpoint()
                return [
                    {
                        "id": "generation",
                        "type": "generation",
                        "usage": {},
                        "incomplete": False,
                    }
                ]

            monkeypatch.setattr(inspect_ai.util, "sandbox", lambda: Sandbox())
            monkeypatch.setattr(inspect_ai.agent, "sandbox_agent_bridge", bridge)
            monkeypatch.setattr(
                inspect_ai.log, "transcript", lambda: SimpleNamespace(events=[])
            )
            monkeypatch.setattr(mini_adapter, "bind_docker_environment", lambda *a: {})
            monkeypatch.setattr(mini_adapter, "model_evidence", model_events)
            try:
                await adapter.execute(
                    task, mode="module", config={"_inspect_docker_compose": "test"}
                )
            except BaseException as exc:
                observed.update(getattr(exc, "benchmark_observation", {}))

    anyio.run(run)
    assert observed["evidence_complete"] is False
    assert any(e["name"] == "intent_decided" for e in observed["events"] if "name" in e)
    assert any(e["type"] == "generation" for e in observed["events"])
