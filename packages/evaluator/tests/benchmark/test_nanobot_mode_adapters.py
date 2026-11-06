"""模式身份与实际执行路由必须一致；测试不初始化 nanobot 或真实模型。"""

import anyio
import pytest

from eval_framework.composition import default_benchmark_registry


@pytest.mark.parametrize(
    "mode,kind,needs_model",
    [
        ("module", "real_module", False),
        ("decision", "real_model_decision", True),
        ("agent", "real_agent", True),
    ],
)
def test_registered_mode_routes_identity_and_execution(
    mode, kind, needs_model, monkeypatch
):
    from eval_framework.benchmark import (
        decision_runtime,
        module_runtime,
        nanobot_runtime,
    )

    modules = {
        "module": module_runtime,
        "decision": decision_runtime,
        "agent": nanobot_runtime,
    }
    identities = {
        "module": "module_identity",
        "decision": "decision_identity",
        "agent": "runtime_identity",
    }
    executes = {
        "module": "execute_module_task",
        "decision": "execute_decision_task",
        "agent": "execute_task",
    }
    received = []
    for name, module in modules.items():
        monkeypatch.setattr(
            module, identities[name], lambda config, name=name: {"mode": name}
        )

        async def execute(task, *, config, workspace, name=name):
            received.append((name, task, workspace))
            return {"route": name}

        monkeypatch.setattr(module, executes[name], execute)
    adapter = default_benchmark_registry().create_adapter(f"nanobot_{mode}", config={})
    assert adapter.runtime_identity() == {"mode": mode}
    assert adapter.execution_kind(mode) == kind
    assert adapter.needs_model(mode) is needs_model

    async def run():
        return await adapter.execute({"prompt": "public"}, mode=mode, config={})

    assert anyio.run(run) == {"route": mode}
    assert received == [(mode, {"prompt": "public"}, None)]
    wrong = "decision" if mode == "module" else "module"
    for method in (
        adapter.runtime_identity,
        adapter.needs_model,
        adapter.execution_kind,
    ):
        with pytest.raises(ValueError, match="mode"):
            method(wrong)
    paths = {path.name for path in adapter.fingerprint_sources()}
    assert "inspect_bridge.py" in paths and "adapters.py" in paths


def test_legacy_facade_still_selects_all_modes(monkeypatch):
    from eval_framework.benchmark import (
        adapters,
        decision_runtime,
        module_runtime,
        nanobot_runtime,
    )

    monkeypatch.setattr(
        module_runtime, "module_identity", lambda config: {"mode": "module"}
    )
    monkeypatch.setattr(
        decision_runtime, "decision_identity", lambda config: {"mode": "decision"}
    )
    monkeypatch.setattr(
        nanobot_runtime, "runtime_identity", lambda config: {"mode": "agent"}
    )
    adapter = default_benchmark_registry().create_adapter("nanobot", config={})
    assert adapters.NanobotAdapter is adapters.NanobotRuntimeAdapter
    assert adapter.provider_id == "nanobot"
    for mode in ("module", "decision", "agent"):
        assert adapter.runtime_identity(mode) == {"mode": mode}
    assert adapter.runtime_identity() == {"mode": "agent"}


def test_bridge_compatibility_preserves_worker_loop_entrypoints():
    from eval_framework.harness import loop
    from eval_framework.integrations.nanobot import inspect_bridge

    assert loop.execute_inspect_task is inspect_bridge.execute_inspect_task
    assert loop._execute is inspect_bridge._execute
