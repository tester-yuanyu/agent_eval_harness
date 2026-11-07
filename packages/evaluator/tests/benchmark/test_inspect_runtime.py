"""Offline integration contracts for the Inspect execution adapter."""

from inspect_ai import Task
from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import solver
from inspect_ai.util import sandbox


def test_fixture_literals_survive_path_detection_and_epochs_are_isolated(tmp_path):
    from eval_framework.benchmark.inspect_runtime import sample_files

    source = tmp_path / "existing.txt"
    source.write_text("must not be substituted")
    fixtures = {"literal.txt": str(source), "unicode.txt": "中文\r\n", "empty": ""}
    observed = []
    directories = []

    @solver
    def probe():
        async def solve(state, generate):
            import sys

            location = await sandbox().exec(
                [sys.executable, "-c", "import os; print(os.getcwd())"]
            )
            directories.append(location.stdout.strip())
            observed.append(
                (state.epoch, await sandbox().read_file("workspace/literal.txt"))
            )
            assert (
                await sandbox().read_file("workspace/unicode.txt", text=False)
                == "中文\r\n".encode()
            )
            assert await sandbox().read_file("workspace/empty") == ""
            await sandbox().write_file("workspace/literal.txt", "changed")
            state.completed = True
            return state

        return solve

    logs = inspect_eval(
        Task(
            dataset=[Sample(id="same", input="test", files=sample_files(fixtures))],
            solver=probe(),
            sandbox="local",
            epochs=2,
        ),
        model="mockllm/model",
        log_dir=str(tmp_path / "logs"),
        display="none",
        notification=False,
        ctl_server=False,
    )
    assert logs[0].status == "success"
    assert sorted(observed) == [(1, str(source)), (2, str(source))]
    from pathlib import Path

    assert len(set(directories)) == 2
    assert all(not Path(directory).exists() for directory in directories)


def test_fixture_paths_cannot_write_outside_sample_workspace():
    import pytest

    from eval_framework.benchmark.inspect_runtime import sample_files

    for name in ["../private", "/tmp/private", "a/../../private"]:
        with pytest.raises(ValueError):
            sample_files({name: "private"})


def test_native_model_event_projects_schemas_usage_and_provenance(tmp_path):
    from inspect_ai.log import transcript
    from inspect_ai.model import (
        ChatMessageAssistant,
        ChatMessageTool,
        ChatMessageUser,
        get_model,
    )
    from inspect_ai.tool import ToolCall

    from eval_framework.benchmark.inspect_runtime import model_evidence

    events = []

    @solver
    def probe():
        async def solve(state, generate):
            await get_model().generate(
                [
                    ChatMessageUser(content="public input"),
                    ChatMessageAssistant(
                        content="",
                        tool_calls=[
                            ToolCall(
                                id="read1",
                                function="read_file",
                                arguments={"path": "input.txt"},
                            )
                        ],
                    ),
                    ChatMessageTool(
                        content="observed", tool_call_id="read1", function="read_file"
                    ),
                ]
            )
            events.extend(await model_evidence(transcript().events, []))
            return state

        return solve

    inspect_eval(
        Task(dataset=[Sample(input="public input")], solver=probe()),
        model="mockllm/model",
        log_dir=str(tmp_path / "logs"),
        display="none",
        notification=False,
        ctl_server=False,
    )
    assert len(events) == 1
    assert events[0]["source"] == "inspect_ai.ModelEvent"
    assert events[0]["output"]["content"] == "Default output from mockllm/model"
    assert events[0]["usage"]["total_tokens"] > 0
    assert events[0]["input"]["messages"][0]["content"] == "public input"
    call = events[0]["input"]["messages"][1]["tool_calls"][0]
    import json

    assert call["function"]["name"] == "read_file"
    assert json.loads(call["function"]["arguments"]) == {"path": "input.txt"}


def test_missing_native_usage_stays_unknown():
    from eval_framework.benchmark.inspect_runtime import aggregate_usage

    assert aggregate_usage([]) == {}
    assert aggregate_usage([{"usage": {}}, {"usage": {"total_tokens": 3}}]) == {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    }


def test_missing_tool_snapshot_never_counts_as_complete_evidence():
    from eval_framework.benchmark.inspect_runtime import evidence_is_complete

    observed = {
        "status": "completed",
        "final_files": {},
        "turns": [{"snapshot": {}}],
        "events": [
            {"type": "turn", "end_time": "done"},
            {
                "type": "tool",
                "execution_started": True,
                "before_files": None,
                "after_files": {},
                "end_time": "done",
            },
        ],
    }
    assert not evidence_is_complete(observed, {"prompt": "test"}, "agent")


def test_standalone_forwards_all_native_sample_limits(tmp_path, monkeypatch):
    import asyncio

    import inspect_ai
    import pytest

    from eval_framework.benchmark.inspect_runtime import _standalone

    class InspectedTask(Exception):
        pass

    async def capture(task, **kwargs):
        assert task.token_limit == 7
        assert task.message_limit == 3
        assert task.time_limit == 5
        raise InspectedTask

    monkeypatch.setattr(inspect_ai, "eval_async", capture)
    with pytest.raises(InspectedTask):
        asyncio.run(
            _standalone(
                {"prompt": "test"},
                config={"token_limit": 7, "message_limit": 3, "timeout_seconds": 5},
                workspace=tmp_path,
                mode="module",
                identity={},
            )
        )


def test_native_model_error_is_a_string_and_keeps_missing_usage_unknown():
    import asyncio

    from inspect_ai.event import ModelEvent
    from inspect_ai.model import GenerateConfig, ModelOutput

    from eval_framework.benchmark.inspect_runtime import model_evidence

    event = ModelEvent(
        model="mockllm/model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content("mockllm/model", ""),
        error="Provider rejected credentials",
    )
    projected = asyncio.run(model_evidence([event], []))[0]
    assert projected["error"] == "Provider rejected credentials"
    assert projected["usage"] == {}


def test_cache_usage_survives_native_projection_and_aggregation():
    import asyncio

    from inspect_ai.event import ModelEvent
    from inspect_ai.model import GenerateConfig, ModelOutput, ModelUsage

    from eval_framework.benchmark.inspect_runtime import aggregate_usage, model_evidence

    output = ModelOutput.from_content("mockllm/model", "ok")
    output.usage = ModelUsage(
        input_tokens=10, output_tokens=2, total_tokens=17, input_tokens_cache_read=5
    )
    event = ModelEvent(
        model="mockllm/model",
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=output,
    )
    projected = asyncio.run(model_evidence([event], []))
    assert projected[0]["usage"]["input_tokens_cache_read"] == 5
    assert aggregate_usage(projected)["input_tokens_cache_read"] == 5
    assert aggregate_usage(projected).get("input_tokens_cache_write") is None
