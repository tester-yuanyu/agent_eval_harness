"""离线环境缓存、分层身份和逐轮证据边界；不执行冻结 benchmark。"""

import asyncio
import json
from copy import deepcopy

import pytest


def test_full_multiturn_never_reuses_final_state():
    from eval_framework.benchmark.full_adapter import order_events

    events = [
        dict(
            id=f"t{i}",
            type="turn",
            turn=i,
            start_time=f"2026-01-01T00:00:0{i}Z",
            output={},
        )
        for i in (1, 2)
    ]
    row = dict(
        after_state={"grants": [1]},
        observations={
            "turns": [{}, {}],
            "turn_snapshots": [{"grants": []}, {"grants": [1]}],
        },
    )
    result = order_events(events, row)
    assert [e["snapshot"] for e in result] == [{"grants": []}, {"grants": [1]}]
    row["observations"].pop("turn_snapshots")
    with pytest.raises(ValueError, match="snapshot"):
        order_events(events, row)


def test_config_validation_shared_fields_and_explicit_legacy_extension():
    from eval_framework.orchestration.specs import validate_runtime_config

    config = {"model": "mockllm/model", "provider": "external", "custom_field": 1}
    assert validate_runtime_config(config) == config
    with pytest.raises(ValueError):
        validate_runtime_config({"max_steps": "3"})
    with pytest.raises(ValueError):
        validate_runtime_config({"unknown": 1}, strict=True)
    assert validate_runtime_config({}) == {}
    assert (
        json.dumps(validate_runtime_config({"timeout_seconds": 30}))
        == '{"timeout_seconds": 30}'
    )
    assert validate_runtime_config({"log_realtime": True}, strict=True) == {
        "log_realtime": True
    }


def test_harness_layer_identity_excludes_scoring_and_keeps_legacy_import():
    from eval_framework.benchmark.layer_sources import layer_source_paths as legacy
    from eval_framework.source_identity import (
        layer_source_paths,
        runtime_layer_source_paths,
    )

    assert legacy() == layer_source_paths()
    layers = runtime_layer_source_paths()
    assert {"harness", "environment", "contracts", "model"} <= layers.keys()
    assert not any(
        "/benchmark/scorers/" in n or "/benchmark/datasets/" in n
        for paths in layers.values()
        for n in paths
    )
    assert any("runtime_model.py" in n for n in layers["model"])


def test_runtime_environment_cache_invalidates_image_and_returns_isolated_values(
    tmp_path,
):
    from eval_framework.benchmark.package_sandbox import RuntimeEnvironmentCache

    cache = RuntimeEnvironmentCache()
    image = ["sha256:first"]
    calls = []

    def bind(compose, environment=None):
        return {"image": "tag", "image_id": image[0]}

    async def probe():
        calls.append(1)
        return {"packages": {"p": "1"}}

    async def run():
        first = await cache.get("compose", probe=probe, bind=bind)
        first["packages"]["p"] = "modified by a sample"
        second = await cache.get("compose", probe=probe, bind=bind)
        assert second["packages"]["p"] == "1"
        assert len(calls) == 1
        image[0] = "sha256:second"
        await cache.get("compose", probe=probe, bind=bind)
        assert len(calls) == 2

    asyncio.run(run())


def test_existing_binding_pins_compose_to_actual_image(tmp_path, monkeypatch):
    from eval_framework.benchmark import inspect_docker

    compose = tmp_path / "sandbox-build/hash/compose.json"
    compose.parent.mkdir(parents=True)
    compose.write_text(
        json.dumps(
            {"services": {"default": {"image": "test:tag", "build": {"context": "."}}}}
        )
    )
    current = ["sha256:first"]
    monkeypatch.setattr(inspect_docker, "docker_image_id", lambda image: current[0])
    bound = inspect_docker.bind_docker_environment(str(compose), {"python": "3.11"})
    inspect_docker.pin_docker_environment(str(compose))
    service = json.loads(compose.read_text())["services"]["default"]
    assert service["image"] == "sha256:first"
    assert "build" not in service
    assert inspect_docker.bind_docker_environment(str(compose)) == bound
    current[0] = "sha256:second"
    with pytest.raises(inspect_docker.SandboxEnvironmentChanged):
        inspect_docker.bind_docker_environment(str(compose))


@pytest.mark.parametrize("scenario_index", range(3))
def test_public_worker_multiturn_fixture_preserves_state_and_faults(
    scenario_index, tmp_path
):
    from pathlib import Path

    from eval_contracts.agent_readiness import AgentPlan, reference_context
    from eval_framework.benchmark.full_worker import execute_public

    from .test_agent_readiness import ROOT, request_fixture

    scenarios = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/runtime_multiturn_v1/scenarios.json"
        ).read_text()
    )["scenarios"]
    scenario = scenarios[scenario_index]
    ready = dict(
        intent="query_user",
        status="READY",
        next_action="CALL_TOOL",
        parameters={"user_id": 10001},
        missing_parameters=[],
        reason="offline input",
    )
    first = {
        **ready,
        "status": "NEED_CLARIFICATION",
        "next_action": "ASK_USER",
        "parameters": {},
        "missing_parameters": ["user_id"],
    }
    if scenario["initial_status"] == "NEED_CONFIRMATION":
        first = dict(
            intent="add_backpack_gift",
            status="NEED_CONFIRMATION",
            next_action="ASK_CONFIRMATION",
            parameters={"user_id": 10001, "gift_id": 101, "environment": "qa"},
            missing_parameters=[],
            reason="offline input",
        )

    class Model:
        calls = 0

        def classify_intent(self, text):
            self.calls += 1
            return deepcopy(
                first if self.calls == 1 else (first if scenario_index == 2 else ready)
            )

        def next_tool_step(self, request):
            if request.tool_outputs:
                return {
                    "type": "message",
                    "content": json.dumps(
                        request.tool_outputs[-1].model_dump(mode="json")
                    ),
                }
            return dict(
                type="function_call",
                call_id="offline-call",
                name="query_user_info",
                arguments=dict(user_id=10001, room_id=None, email=None, phone=None),
            )

        def metadata(self):
            return {"model": "offline-script", "paid_model": "false"}

    plan = AgentPlan(
        category="agent_chain",
        scope="end_to_end",
        user_input=scenario["user_input"],
        candidate=ready,
        allowed_tools=["query_user_info"],
        max_steps=4,
        tool_name="query_user_info",
        tool_arguments=dict(user_id=10001, room_id=None, email=None, phone=None),
        records={
            "users": [
                {
                    "user_id": 10001,
                    "room_id": 1,
                    "email": "offline@example.test",
                    "phone": "15000000200",
                }
            ]
        },
        fault=scenario["fault"],
    )
    task = dict(
        case_id=scenario["id"],
        execution={
            "user_input": scenario["user_input"],
            "user_responses": scenario["user_responses"],
        },
        plan=plan.model_dump(mode="json"),
        live=True,
        context=reference_context(request_fixture()).model_dump(mode="json"),
    )
    row = execute_public(
        task, ROOT / "examples/mini_agent", tmp_path / "evidence", Model()
    )
    assert row["evidence_complete"], row["errors"]
    assert len(row["observations"]["turns"]) == 2
    snapshots = row["observations"]["turn_snapshots"]
    assert len(snapshots) == 2
    assert snapshots[0] == row["before_state"]
    assert snapshots[-1] == row["after_state"]
    assert snapshots[0]["grants"] == snapshots[-1]["grants"] == []
    if scenario["fault"] == "tool_error":
        assert any(
            event["event_type"] == "tool_failed"
            for event in row["observations"]["events"]
        )
    if scenario_index == 2:
        assert row["observations"]["handler_calls"] == []
