"""Two contracts: shared-loop components and the native subprocess runtime."""

import asyncio
import hashlib
import importlib.util
import json
import os

import pytest


def test_native_runtime_name_preserves_subprocess_dispatch(monkeypatch):
    from eval_framework.benchmark import nanobot_runtime
    from eval_framework.benchmark.adapters import NanobotAdapter, NanobotRuntimeAdapter

    calls = []

    async def native(task, *, config, workspace):
        calls.append(task)
        return {"native": True}

    monkeypatch.setattr(nanobot_runtime, "execute_task", native)
    assert NanobotAdapter is NanobotRuntimeAdapter
    adapter = NanobotRuntimeAdapter({})
    assert asyncio.run(adapter.execute({"id": "native"}, mode="agent", config={})) == {
        "native": True
    }
    assert calls == [{"id": "native"}]


def test_component_dependency_is_optional_and_never_injected(monkeypatch):
    from eval_framework.composition import resolve_benchmark_adapter
    from eval_framework.harness.adapters.agent import nanobot_adapter

    monkeypatch.setattr(nanobot_adapter, "find_spec", lambda _: None)
    assert (
        resolve_benchmark_adapter({"provider": "raw_model"}).provider_id == "raw_model"
    )
    adapter = resolve_benchmark_adapter({"provider": "nanobot_component"})
    with pytest.raises(RuntimeError, match="nanobot.*optional|optional.*nanobot"):
        adapter.runtime_identity("agent")


@pytest.fixture
def native_components():
    if importlib.util.find_spec("nanobot") is None:
        pytest.skip(
            "optional nanobot must be installed or on process PYTHONPATH"
        )
    from nanobot.agent.context import ContextBuilder

    from eval_framework.harness.adapters.agent.nanobot_adapter import (
        NanobotComponentAdapter,
    )

    return NanobotComponentAdapter, ContextBuilder


def test_real_component_prompt_is_stable_and_private_state_is_cleaned(
    native_components,
):
    component, _ = native_components
    a, b = component(), component()
    try:
        pa, ia = a.prepare_prompt("policy-A")
        pb, ib = b.prepare_prompt("policy-B")
        assert "Tool Usage Notes" in pa and "policy-A" in pa and "policy-B" not in pa
        assert "policy-B" in pb and "policy-A" not in pb
        assert ia["profile"] == "nanobot-context-v1"
        assert ia["rendered_sha256"] == hashlib.sha256(pa.encode()).hexdigest()
        assert ia["rendered_sha256"] != ib["rendered_sha256"]
        assert str(a.workspace) not in pa
        assert a.workspace != b.workspace
        private = [a.workspace, b.workspace]
    finally:
        asyncio.run(a.close())
        asyncio.run(b.close())
    assert not any(p.exists() for p in private)


def test_component_rejects_different_source_version(native_components, tmp_path):
    from eval_framework.composition import resolve_benchmark_adapter

    adapter = resolve_benchmark_adapter(
        {"provider": "nanobot_component", "nanobot_root": str(tmp_path)}
    )
    with pytest.raises(ValueError, match="installed|loaded"):
        adapter.runtime_identity("agent")


def test_real_components_concurrently_use_inspect_without_global_mutation(
    native_components, monkeypatch, tmp_path
):
    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.log import read_eval_log
    from inspect_ai.model import ChatMessageAssistant, ModelOutput, get_model
    from inspect_ai.solver import solver
    from inspect_ai.tool import ToolCall
    from loguru import logger
    from nanobot.agent.skills import SkillsLoader
    from nanobot.config import loader
    from nanobot.utils import helpers

    from eval_framework.composition import resolve_benchmark_adapter

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "personal config, plugin discovery or tokenizer was accessed"
        )

    monkeypatch.setattr(loader, "set_config_path", forbidden)
    monkeypatch.setattr(helpers, "_get_token_encoding", forbidden)
    monkeypatch.setattr(SkillsLoader, "list_skills", forbidden)
    monkeypatch.setattr(loader, "load_config", forbidden)
    # Inspect loads cwd .env at eval startup; isolate the test from user secrets.
    monkeypatch.chdir(tmp_path)
    handlers = dict(logger._core.handlers)
    environment = dict(os.environ)
    tokenizer = helpers._get_token_encoding
    tasks = {
        name: {
            "id": name,
            "prompt": f"Write {name} to out.txt",
            "fixtures": {},
            "allowed_tools": ["write_file"],
            "max_steps": 3,
        }
        for name in ("ALPHA", "BETA")
    }
    adapter = resolve_benchmark_adapter(
        {"provider": "nanobot_component", "sandbox": "local"}
    )

    @solver
    def component_solver():
        async def solve(state, generate):
            await adapter.execute_in_inspect(
                tasks[str(state.sample_id)],
                mode="agent",
                config={"max_steps": 3},
                state=state,
            )
            return state

        return solve

    def answer(messages, tools, tool_choice, config):
        users = [m.text for m in messages if m.role == "user"]
        name = "ALPHA" if "ALPHA" in users[0] else "BETA"
        assert ("BETA" if name == "ALPHA" else "ALPHA") not in str(messages)
        assert "Tool Usage Notes" in messages[0].text
        value = ModelOutput.from_content("mockllm/model", "done")
        if messages[-1].role == "user":
            value.choices[0].message = ChatMessageAssistant(
                content="",
                tool_calls=[
                    ToolCall(
                        id="write",
                        function="write_file",
                        arguments={"path": "out.txt", "content": name},
                    )
                ],
            )
        return value

    log = inspect_eval(
        Task(
            dataset=[Sample(id=n, input=t["prompt"]) for n, t in tasks.items()],
            solver=component_solver(),
            sandbox="local",
        ),
        model=get_model("mockllm/model", custom_outputs=answer),
        display="none",
        notification=False,
        ctl_server=False,
        max_samples=2,
        log_dir=str(tmp_path),
    )[0]
    log = read_eval_log(log.location, resolve_attachments=True)
    assert log.status == "success", log.error
    for sample in log.samples:
        obs = sample.metadata["harness_observation"]
        assert obs["evidence_complete"], obs
        assert obs["final_files"] == {"out.txt": sample.id}
        assert obs["execution_kind"] == "harness_nanobot_component"
        model_event = next(e for e in sample.events if e.event == "model")
        assert (
            obs["prompt_identity"]["rendered_sha256"]
            == hashlib.sha256(model_event.input[0].text.encode()).hexdigest()
        )
        assert obs["runtime_identity"]["nanobot"]["sources"]
    assert dict(logger._core.handlers) == handlers
    changed_names = sorted(
        key
        for key in set(os.environ) | set(environment)
        if os.environ.get(key) != environment.get(key)
    )
    assert not changed_names, changed_names
    assert helpers._get_token_encoding is tokenizer
    assert loader.set_config_path is forbidden
    assert "oracle" not in json.dumps([s.metadata for s in log.samples]).lower()


def test_fresh_process_import_and_prepare_do_not_touch_global_setup(
    native_components, tmp_path
):
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent("""
        import asyncio
        import os
        from loguru import logger
        from nanobot.config import loader
        from nanobot.utils import helpers
        from eval_framework.harness.adapters.agent.nanobot_adapter import (
            NanobotComponentAdapter,
        )

        def forbidden(*args, **kwargs):
            raise AssertionError("global setup must not be called")

        loader.set_config_path = forbidden
        loader.load_config = forbidden
        helpers._get_token_encoding = forbidden
        original_path = loader.get_config_path()
        original_env = dict(os.environ)
        original_handlers = dict(logger._core.handlers)
        async def run():
            a = NanobotComponentAdapter()
            b = NanobotComponentAdapter()
            try:
                a.prepare_prompt("A")
                b.prepare_prompt("B")
            finally:
                await a.close()
                await b.close()
        asyncio.run(run())
        assert loader.get_config_path() == original_path
        assert dict(logger._core.handlers) == original_handlers
        assert not [
            k for k in set(os.environ) | set(original_env)
            if os.environ.get(k) != original_env.get(k)
        ]
        assert helpers._get_token_encoding is forbidden
    """)
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
