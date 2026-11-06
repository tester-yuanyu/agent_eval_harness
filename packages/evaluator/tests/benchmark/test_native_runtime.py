"""Opt-in native Harness runtime, through the existing benchmark entry point."""

from __future__ import annotations

import json

import pytest
from inspect_ai.model import ChatMessageAssistant, ModelOutput, get_model
from inspect_ai.tool import ToolCall


@pytest.mark.parametrize("provider", ["raw_model", "nanobot_component"])
def test_raw_model_request_registry_scoring_and_resume(tmp_path, monkeypatch, provider):
    import importlib.util

    if provider == "nanobot_component" and importlib.util.find_spec("nanobot") is None:
        pytest.skip("optional nanobot components")
    from eval_framework.benchmark.runner import run_benchmark
    from eval_framework.composition import resolve_benchmark_adapter
    from eval_framework.harness.adapters.runtime import RawModelRuntimeAdapter
    from eval_framework.orchestration.config import load_run_request

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "model": {"model": "mockllm/model"},
                "harness": {
                    "max_steps": 3,
                    "max_tool_calls": 2,
                    "prompt_version": "harness-v1",
                },
                "environment": {"provider": provider, "sandbox": "local"},
                "benchmark": {},
                "execution": {},
            }
        )
    )
    config = load_run_request(config_path).runtime_config()
    assert resolve_benchmark_adapter(config).provider_id == provider
    secret = "PRIVATE_ORACLE_SENTINEL"
    task = {
        "id": "native-bridge",
        "prompt": "Write ok to result.txt",
        "followups": [],
        "fixtures": {},
        "allowed_tools": ["write_file"],
        "required_tools": ["write_file"],
        "max_steps": 3,
        "category": "create_edit",
        "family": "write",
        "split": "dev",
        "oracle": {"expected_files": {"result.txt": "ok"}},
        "reference_answer": secret,
        "reference": [
            {"tool": "write_file", "arguments": {"path": "result.txt", "content": "ok"}}
        ],
    }

    def answer(messages, tools, tool_choice, generate_config):
        assert secret not in str(messages)
        value = ModelOutput.from_content("mockllm/model", "done")
        if messages[-1].role == "user":
            value.choices[0].message = ChatMessageAssistant(
                content="",
                tool_calls=[
                    ToolCall(
                        id="write",
                        function="write_file",
                        arguments={"path": "result.txt", "content": "ok"},
                    )
                ],
            )
        return value

    monkeypatch.setattr(
        RawModelRuntimeAdapter,
        "inspect_model",
        lambda _: get_model("mockllm/model", custom_outputs=answer),
    )
    run = run_benchmark(
        [task],
        dataset={"id": "native-test"},
        config=config,
        output=tmp_path / "run",
        concurrency=1,
    )
    row = run["trials"][0]
    assert row["assessment"]["verdict"] == "PASS", row
    assert row["observation"]["execution_kind"] == "harness_" + provider
    assert row["observation"]["prompt_identity"]["version"] == "harness-v1"
    assert secret not in json.dumps(row["observation"])
    assert (
        run_benchmark(
            [task],
            dataset={"id": "native-test"},
            config=config,
            output=tmp_path / "run",
        )
        == run
    )
    with pytest.raises(ValueError, match="identity changed"):
        run_benchmark(
            [task],
            dataset={"id": "native-test"},
            config={**config, "max_tool_calls": 3},
            output=tmp_path / "run",
        )


@pytest.mark.parametrize("mode", ["module", "decision"])
def test_raw_runtime_does_not_silently_change_native_module_semantics(mode):
    from eval_framework.composition import resolve_benchmark_adapter

    adapter = resolve_benchmark_adapter({"provider": "raw_model"})
    with pytest.raises(ValueError, match="agent"):
        adapter.runtime_identity(mode)


def test_prompt_identity_includes_policy_and_instruction_content(tmp_path):
    import hashlib

    from eval_contracts.benchmark import TaskInput
    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample

    from eval_framework.harness.adapters.inspect_solver import harness_solver

    public = TaskInput(
        task_id="policy",
        prompt="say ok",
        policy="Specific policy",
        initial_state={"files": {}},
    )
    log = inspect_eval(
        Task(
            dataset=[Sample(id="policy", input="say ok")],
            sandbox="local",
            solver=harness_solver(
                {"policy": public}, instructions="Specific instruction"
            ),
        ),
        model="mockllm/model",
        display="none",
        notification=False,
        ctl_server=False,
        log_dir=str(tmp_path),
    )[0]
    from inspect_ai.log import read_eval_log

    log = read_eval_log(log.location, resolve_attachments=True)
    event = next(e for e in log.samples[0].events if e.event == "model")
    identity = log.samples[0].metadata["harness_observation"]["prompt_identity"]
    assert (
        identity["rendered_sha256"]
        == hashlib.sha256(event.input[0].text.encode()).hexdigest()
    )
