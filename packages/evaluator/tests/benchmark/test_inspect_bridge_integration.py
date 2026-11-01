"""Explicit opt-in: genuine Docker, nanobot, and Inspect bridge with a mock model."""

import os
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_BENCHMARK_TESTS") != "1",
    reason="opt-in Docker integration; never calls a paid model",
)
def test_docker_bridge_native_model_events_and_decision_boundary(tmp_path):
    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.model import ModelOutput, ModelUsage, get_model
    from inspect_ai.solver import solver
    from inspect_ai.tool import ToolCall

    from eval_framework.benchmark.decision_runtime import execute_decision_task
    from eval_framework.benchmark.inspect_runtime import sample_files, sandbox_spec
    from eval_framework.benchmark.nanobot_runtime import execute_task

    root = Path(os.environ.get("NANOBOT_TEST_ROOT", "/Users/yuanyu/Desktop/nanobot"))
    config = {
        "nanobot_root": str(root),
        "model": "mockllm/model",
        "sandbox": "docker",
        "tokenizer_mode": "byte_fallback",
        "max_steps": 6,
    }
    spec = sandbox_spec(config, tmp_path / "docker", needs_model=True)
    config["_inspect_docker_compose"] = spec[1]
    observed = {}
    container_ids = []

    def answer(messages, tools, choice, config):
        assert {tool.name for tool in tools} <= {
            "read_file",
            "write_file",
            "edit_file",
            "list_dir",
        }
        output = ModelOutput.from_content("mockllm/model", "done")
        output.usage = ModelUsage(input_tokens=8, output_tokens=2, total_tokens=10)
        if not any(message.role == "tool" for message in messages):
            output.message.tool_calls = [
                ToolCall(
                    id="write1",
                    function="write_file",
                    arguments={"path": "output.txt", "content": "created"},
                )
            ]
        return output

    @solver
    def run(mode):
        async def solve(state, generate):
            from inspect_ai.util import sandbox

            container = await sandbox().exec(["cat", "/etc/hostname"])
            assert container.success
            container_ids.append(container.stdout.strip())
            executor = execute_decision_task if mode == "decision" else execute_task
            task = {
                "id": "native-test",
                "prompt": "write output.txt",
                "allowed_tools": ["write_file"],
                "max_steps": 6,
            }
            try:
                observed[(mode, state.epoch)] = await executor(
                    task, config=config, workspace=None
                )
            except BaseException as exc:
                observed[(mode, state.epoch)] = getattr(
                    exc, "benchmark_observation", {}
                )
                raise
            return state

        return solve

    tasks = [
        Task(
            name=mode,
            dataset=[
                Sample(
                    input="write output.txt", files=sample_files({"input.txt": "keep"})
                )
            ],
            solver=run(mode),
            sandbox=spec,
            epochs=2 if mode == "agent" else 1,
            token_limit=1 if mode == "limited" else None,
            message_limit=1 if mode == "message_limited" else None,
        )
        for mode in ["agent", "decision", "limited", "message_limited"]
    ]
    logs = inspect_eval(
        tasks,
        model=get_model("mockllm/model", custom_outputs=answer),
        log_dir=str(tmp_path / "logs"),
        display="none",
        notification=False,
        ctl_server=False,
        max_samples=1,
        fail_on_error=False,
    )
    assert all(log.status == "success" for log in logs), [log.error for log in logs]
    import subprocess

    for container_id in container_ids:
        deleted = subprocess.run(
            ["docker", "inspect", container_id], capture_output=True
        )
        assert deleted.returncode != 0, "Inspect must delete each sample container"
    for epoch in [1, 2]:
        row = observed[("agent", epoch)]
        assert row["status"] == "completed", row
        assert row["before_files"] == {"input.txt": "keep"}
        assert row["final_files"] == {"input.txt": "keep", "output.txt": "created"}
        assert row["native_events"]["model"] == 2
        assert row["usage"]["total_tokens"] == 20
        assert len([event for event in row["events"] if event["type"] == "tool"]) == 1
    decision = observed[("decision", 1)]
    assert decision["status"] == "completed", decision
    assert decision["final_files"] == {"input.txt": "keep"}
    assert decision["native_events"]["model"] == 1
    assert decision["decision"]["tool_calls"][0]["name"] == "write_file"
    assert decision["evidence_complete"] is True
    from eval_framework.benchmark.inspect_runtime import apply_native_limits
    from eval_framework.benchmark.metrics import score_task

    for index, mode in [(2, "limited"), (3, "message_limited")]:
        limited = observed[(mode, 1)]
        apply_native_limits(limited, logs[index].samples[0].events)
        assert limited["evidence_complete"] is False
        assert limited["status"] != "completed"
        assert any(
            event.event == "sample_limit" for event in logs[index].samples[0].events
        )
        assessment = score_task(
            {
                "id": "native-test",
                "prompt": "write output.txt",
                "followups": [],
                "fixtures": {"input.txt": "keep"},
                "allowed_tools": ["write_file"],
                "required_tools": ["write_file"],
                "oracle": {"expected_files": {"output.txt": "created"}},
            },
            limited,
        )
        assert assessment["validity"] == "VALID", (limited, assessment)
        assert assessment["verdict"] == "FAIL", (limited, assessment)


@pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_BENCHMARK_TESTS") != "1",
    reason="opt-in Docker integration; never calls a paid model",
)
def test_runner_honors_explicit_docker_for_frozen_module(tmp_path):
    from eval_framework.benchmark.runner import run_benchmark
    from eval_framework.benchmark.tasks import load_tasks

    root = Path(__file__).resolve().parents[4]
    task = next(
        t
        for t in load_tasks(root / "data/benchmarks/file-tools-v2")
        if t.get("execution_mode") == "module"
    )
    result = run_benchmark(
        [task],
        dataset={"identity": "docker-module-test"},
        config={
            "nanobot_root": os.environ.get(
                "NANOBOT_TEST_ROOT", "/Users/yuanyu/Desktop/nanobot"
            ),
            "sandbox": "docker",
            "tokenizer_mode": "byte_fallback",
            "model": "mockllm/model",
        },
        output=tmp_path,
        concurrency=1,
    )
    row = result["trials"][0]
    assert row["assessment"]["verdict"] == "PASS", row
    assert row["observation"]["runtime_identity"]["isolation"] == "docker"
    assert row["observation"]["native_events"]["sandbox"] > 0
    assert (tmp_path / "sandbox-environment.json").is_file()
