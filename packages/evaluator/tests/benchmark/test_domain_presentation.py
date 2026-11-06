"""文件和 SQLite Provider 的真实公开输入不能被 runner 的字段假设改变。"""

import copy
from pathlib import Path

import pytest
from inspect_ai.log import list_eval_logs, read_eval_log

from eval_framework.benchmark.runner import run_benchmark
from eval_framework.provider_registry import ProviderRegistry

from .test_agent_adapters import AdapterFactory, OfflineAdapter


class ProviderAdapter(OfflineAdapter):
    async def execute(self, task, *, mode, config):
        self.received.append(copy.deepcopy(task))
        return {
            "status": "completed",
            "turns": [],
            "events": [],
            "usage": {},
            "errors": [],
            "runtime_identity": self.runtime_identity(mode),
            "evidence_complete": True,
        }


class PublicDomain:
    def identity(self):
        return {"version": "public-v1"}

    def execution_task(self, task):
        return {"execution": {"user_input": "public database request"}}

    def score_task(self, task, observation):
        return {"verdict": "PASS", "validity": "VALID", "metrics": [], "errors": []}


def test_sample_uses_public_projection_without_fixtures(tmp_path):
    from eval_framework.benchmark.domains.presentation import ProviderPresentation

    adapter = ProviderAdapter()
    registry = ProviderRegistry()
    registry.register(adapter.provider_id, AdapterFactory(adapter))
    task = dict(
        id="database",
        category="query",
        family="query",
        split="dev",
        prompt="PRIVATE-TOPLEVEL",
        oracle={"secret": "PRIVATE-ORACLE"},
    )
    kwargs = dict(
        dataset={"id": "provider-test"},
        config={"provider": adapter.provider_id},
        output=tmp_path,
        domain=PublicDomain(),
        provider_registry=registry,
        presentation=ProviderPresentation(task_name="sqlite_test"),
    )
    result = run_benchmark([task], **kwargs)
    assert result["trials"][0]["assessment"]["verdict"] == "PASS"
    assert adapter.received == [
        {"execution": {"user_input": "public database request"}}
    ]
    log = read_eval_log(list_eval_logs(str(tmp_path / "inspect"))[0].name)
    assert log.eval.task == "sqlite_test"
    sample = log.samples[0]
    assert sample.input == "public database request"
    assert sample.target == ""
    assert "PRIVATE" not in str(sample.input) + str(sample.metadata)
    with pytest.raises(ValueError, match="identity changed"):
        run_benchmark(
            [task],
            **{**kwargs, "presentation": ProviderPresentation(task_name="changed")},
        )


def test_existing_sqlite_domain_runs_without_file_envelope(tmp_path):
    pytest.importorskip("minimal_agent")
    from minimal_agent.contracts.agent import (
        FinalResponseItem,
        FunctionCallItem,
        IntentResult,
    )

    from eval_framework.benchmark.mini_adapter import project_events
    from eval_framework.benchmark.mini_scoring import MiniAgentDomain
    from eval_framework.benchmark.mini_worker import execute_public
    from eval_framework.benchmark.provider_tasks import (
        load_provider_tasks,
        provider_dataset_identity,
    )
    from tests.support.model_client import DeterministicModelClient

    dataset = Path(__file__).resolve().parents[4] / "data/benchmarks/mini-agent-v1.0.1"
    task = copy.deepcopy(
        next(t for t in load_provider_tasks(dataset) if t["id"] == "MINI-CHAIN-001")
    )
    task.pop("fixtures", None)
    task.pop("prompt", None)
    domain = MiniAgentDomain(dataset)

    class ScriptedAdapter(ProviderAdapter):
        async def execute(self, public, *, mode, config):
            self.received.append(copy.deepcopy(public))
            result = execute_public(
                public,
                dataset / "capability_bundle",
                tmp_path / "evidence",
                lambda _: DeterministicModelClient(
                    [
                        IntentResult(
                            intent="query_user",
                            status="READY",
                            next_action="CALL_TOOL",
                            parameters={"user_id": 91001},
                            reason="offline test",
                        ),
                        FunctionCallItem(
                            type="function_call",
                            call_id="query",
                            name="query_user_info",
                            arguments={
                                "user_id": 91001,
                                "room_id": None,
                                "email": None,
                                "phone": None,
                            },
                        ),
                        FinalResponseItem(type="message", content="测试用户甲"),
                    ]
                ),
            )
            result["events"] = project_events(result["adapter_output"]) + [
                {"id": "offline-scripted-generation", "type": "generation"}
            ]
            result["runtime_identity"] = self.runtime_identity(mode)
            return result

    adapter = ScriptedAdapter()
    registry = ProviderRegistry()
    registry.register(adapter.provider_id, AdapterFactory(adapter))
    result = run_benchmark(
        [task],
        dataset=provider_dataset_identity(dataset),
        config={"provider": adapter.provider_id},
        output=tmp_path / "run",
        domain=domain,
        provider_registry=registry,
    )
    row = result["trials"][0]
    assert row["assessment"]["verdict"] == "PASS", row["assessment"]
    assert set(adapter.received[0]) == {"execution", "scope", "environment"}
    assert (
        row["observation"]["adapter_output"]["turns"][0]["tool_calls"][0]["output"][
            "data"
        ]["users"][0]["name"]
        == "测试用户甲"
    )
