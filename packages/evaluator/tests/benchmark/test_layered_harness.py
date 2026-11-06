"""Offline behavior contracts for framework-owned environments and Harness."""

import errno
import json
from pathlib import Path

import pytest


def test_reset_isolates_trials_and_snapshots_and_teardown(tmp_path):
    from eval_framework.environments import FileToolsEnvironment

    environment = FileToolsEnvironment(parent=tmp_path)
    initial = {"a.txt": "first\r\n"}
    assert environment.reset(initial) is None
    first = environment.workspace
    initial["a.txt"] = "not a fixture mutation"
    snapshot = environment.snapshot()
    snapshot["a.txt"] = "not an environment mutation"
    assert environment.final_state() == {"a.txt": "first\r\n"}
    environment.step({"name": "write_file", "arguments": {"path": "b", "content": "b"}})
    assert environment.reset({"fresh": "new"}) is None
    assert environment.snapshot() == {"fresh": "new"}
    assert not first.exists()
    assert environment.workspace != first
    workspace = environment.workspace
    environment.teardown()
    environment.teardown()
    assert not workspace.exists()
    with pytest.raises(RuntimeError, match="reset"):
        environment.snapshot()


def test_environment_rejects_escape_symlinks_and_cleans_failed_reset(tmp_path):
    from eval_framework.environments import FileToolsEnvironment

    outside = tmp_path / "outside"
    outside.write_text("private")
    environment = FileToolsEnvironment(parent=tmp_path)
    for invalid in ("../outside", str(outside)):
        with pytest.raises(ValueError):
            environment.reset({invalid: "overwrite"})
    assert outside.read_text() == "private"
    assert not list(tmp_path.glob("harness-*"))
    environment.reset({})
    (environment.workspace / "link").symlink_to(outside)
    with pytest.raises(ValueError, match="symbolic"):
        environment.step({"name": "read_file", "arguments": {"path": "link"}})
    with pytest.raises(ValueError, match="symbolic"):
        environment.snapshot()
    environment.teardown()


def test_router_validates_before_dispatch_and_returns_independent_arguments(tmp_path):
    from eval_framework.environments import FileToolsEnvironment
    from eval_framework.harness import ToolRouter

    environment = FileToolsEnvironment(parent=tmp_path)
    environment.reset({})
    router = ToolRouter(environment, allowed_tools=["read_file", "write_file"])
    arguments = {"path": "a", "content": "hello"}
    action = router.parse({"name": "write_file", "arguments": arguments})
    arguments["content"] = "mutated"
    router.dispatch(action)
    assert (
        router.dispatch(router.parse('{"name":"read_file","arguments":{"path":"a"}}'))
        == "hello"
    )
    with pytest.raises(ValueError, match="allowed"):
        router.parse({"name": "list_dir", "arguments": {}})
    with pytest.raises(ValueError, match="arguments"):
        router.dispatch({"name": "write_file", "arguments": {"path": "bad"}})
    assert environment.snapshot() == {"a": "hello"}
    environment.teardown()


def test_fixed_followups_preserve_order_and_stop_after_last_message():
    from eval_framework.harness import FixedFollowupUserSimulator

    simulator = FixedFollowupUserSimulator("start", ["next", "last"])
    history = []
    for text in ["start", "next", "last"]:
        assert not simulator.should_terminate(history)
        assert simulator.next_message(history) == {"role": "user", "content": text}
        history.extend(
            [
                {"role": "user", "content": text},
                {"role": "assistant", "content": "done"},
            ]
        )
    assert simulator.should_terminate(history)
    assert simulator.next_message(history) is None


def test_framework_loop_routes_tools_before_followup_and_preserves_final_state(
    tmp_path,
):
    from eval_framework.environments import FileToolsEnvironment
    from eval_framework.harness import FixedFollowupUserSimulator, run_conversation

    inputs = []
    replies = iter(
        [
            {
                "content": "",
                "tool_calls": [
                    {
                        "name": "write_file",
                        "arguments": {"path": "a", "content": "written"},
                    }
                ],
            },
            {"content": "first answer"},
            {"content": "second answer"},
        ]
    )

    def agent(history):
        inputs.append(history)
        return next(replies)

    environment = FileToolsEnvironment(parent=tmp_path)
    result = run_conversation(
        agent,
        environment=environment,
        initial_state={},
        simulator=FixedFollowupUserSimulator("first", ["second"]),
    )
    assert [m["content"] for m in inputs[1] if m["role"] == "user"] == ["first"]
    assert [m["content"] for m in inputs[2] if m["role"] == "user"] == [
        "first",
        "second",
    ]
    assert result["final_files"] == {"a": "written"}
    assert result["turns"][0]["snapshot"] == {"a": "written"}
    tool = next(e for e in result["events"] if e["type"] == "tool")
    assert tool["before_files"] == {} and tool["after_files"] == {"a": "written"}
    assert not list(tmp_path.glob("harness-*"))


def test_framework_loop_cleans_environment_after_agent_failure(tmp_path):
    from eval_framework.environments import FileToolsEnvironment
    from eval_framework.harness import FixedFollowupUserSimulator, run_conversation

    def fail(_history):
        raise RuntimeError("agent unavailable")

    result = run_conversation(
        fail,
        environment=FileToolsEnvironment(parent=tmp_path),
        initial_state={},
        simulator=FixedFollowupUserSimulator("first"),
    )
    assert result["status"] == "error"
    assert result["errors"][0]["kind"] == "agent"
    assert result["errors"][0]["message"] == "agent unavailable"
    assert result["evidence_complete"] is False
    assert not list(tmp_path.glob("harness-*"))


def test_framework_loop_cleans_a_partially_initialized_environment(tmp_path):
    from eval_framework.environments import FileToolsEnvironment
    from eval_framework.harness import FixedFollowupUserSimulator, run_conversation

    class FailedEnvironment(FileToolsEnvironment):
        def reset(self, initial_state):
            super().reset(initial_state)
            raise OSError("fixture initialization interrupted")

    result = run_conversation(
        lambda history: {"content": "unused"},
        environment=FailedEnvironment(parent=tmp_path),
        initial_state={"a": "b"},
        simulator=FixedFollowupUserSimulator("first"),
    )
    assert result["status"] == "error"
    assert result["errors"][0]["kind"] == "environment"
    assert not list(tmp_path.glob("harness-*"))


def test_snapshot_failure_is_environment_error_not_agent_failure(tmp_path):
    from eval_framework.environments import FileToolsEnvironment
    from eval_framework.harness import FixedFollowupUserSimulator, run_conversation

    class InterruptedSnapshot(FileToolsEnvironment):
        fail_next = False

        def snapshot(self):
            if self.fail_next:
                self.fail_next = False
                raise OSError("snapshot interrupted")
            return super().snapshot()

    environment = InterruptedSnapshot(parent=tmp_path)

    def agent(_history):
        environment.fail_next = True
        return {"content": "done"}

    result = run_conversation(
        agent,
        environment=environment,
        initial_state={"a": "b"},
        simulator=FixedFollowupUserSimulator("first"),
    )
    assert result["status"] == "error"
    assert result["errors"][0]["kind"] == "environment"
    assert result["final_files"] == {"a": "b"}


def test_framework_components_satisfy_public_plugin_protocols(tmp_path):
    from eval_framework.environments import FileToolsEnvironment
    from eval_framework.harness import FixedFollowupUserSimulator, ToolRouter
    from eval_framework.plugins.protocols import (
        EnvironmentPlugin,
        ToolRouterPlugin,
        UserSimulatorPlugin,
    )

    environment = FileToolsEnvironment(parent=tmp_path)
    router = ToolRouter()
    simulator = FixedFollowupUserSimulator("public")
    assert isinstance(environment, EnvironmentPlugin)
    assert isinstance(router, ToolRouterPlugin)
    assert isinstance(simulator, UserSimulatorPlugin)
    environment.reset({"a": "b"})
    call = {"name": "read_file", "arguments": {"path": "a"}}
    assert router.validate_args(call) == []
    assert router.dispatch(router.parse(call), environment) == "b"
    environment.teardown()


def test_framework_loop_limits_agent_calls_and_keeps_partial_state(tmp_path):
    from eval_framework.environments import FileToolsEnvironment
    from eval_framework.harness import FixedFollowupUserSimulator, run_conversation

    def agent(_history):
        return {
            "tool_calls": [
                {"name": "write_file", "arguments": {"path": "a", "content": "partial"}}
            ]
        }

    result = run_conversation(
        agent,
        environment=FileToolsEnvironment(parent=tmp_path),
        initial_state={},
        simulator=FixedFollowupUserSimulator("first"),
        max_steps=1,
    )
    assert result["status"] == "error"
    assert result["stop_reason"] == "max_steps"
    assert result["errors"][0]["kind"] == "agent"
    assert result["final_files"] == {"a": "partial"}
    assert result["evidence_complete"] is False
    assert not list(tmp_path.glob("harness-*"))


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EIO, errno.EROFS])
def test_tool_infrastructure_failure_is_invalid_and_retains_event(tmp_path, code):
    from eval_framework.benchmark.metrics import score_task
    from eval_framework.environments import FileToolsEnvironment
    from eval_framework.harness import FixedFollowupUserSimulator, run_conversation

    class UnavailableStorage(FileToolsEnvironment):
        def step(self, action):
            raise OSError(code, "storage unavailable")

    result = run_conversation(
        lambda history: {
            "tool_calls": [
                {"name": "write_file", "arguments": {"path": "a", "content": "value"}}
            ]
        },
        environment=UnavailableStorage(parent=tmp_path),
        initial_state={},
        simulator=FixedFollowupUserSimulator("write a"),
    )
    assert result["errors"][0]["kind"] == "environment"
    task = {
        "id": "storage",
        "prompt": "write a",
        "followups": [],
        "fixtures": {},
        "oracle": {"expected_files": {"a": "value"}},
        "allowed_tools": ["write_file"],
    }
    assessment = score_task(task, result)
    assert (assessment["verdict"], assessment["validity"]) == ("INVALID", "INVALID")
    event = next(event for event in result["events"] if event["type"] == "tool")
    assert event["error"]["kind"] == "environment"
    assert event["error"]["errno"] == code
    assert event["incomplete"] is True
    assert event["end_time"]
    assert event["after_files"] == {}
    assert not list(tmp_path.glob("harness-*"))


@pytest.mark.parametrize("path", ["missing.txt", "../outside.txt"])
def test_invalid_tool_operation_remains_agent_failure_with_event(tmp_path, path):
    from eval_framework.benchmark.metrics import score_task
    from eval_framework.environments import FileToolsEnvironment
    from eval_framework.harness import FixedFollowupUserSimulator, run_conversation

    result = run_conversation(
        lambda history: {
            "tool_calls": [{"name": "read_file", "arguments": {"path": path}}]
        },
        environment=FileToolsEnvironment(parent=tmp_path),
        initial_state={},
        simulator=FixedFollowupUserSimulator("read a"),
    )
    assert result["errors"][0]["kind"] == "agent"
    task = {
        "id": "read",
        "prompt": "read a",
        "followups": [],
        "fixtures": {},
        "oracle": {"response_contains": ["answer"]},
        "allowed_tools": ["read_file"],
    }
    assessment = score_task(task, result)
    assert (assessment["verdict"], assessment["validity"]) == ("FAIL", "VALID")
    event = next(event for event in result["events"] if event["type"] == "tool")
    assert event["error"]["kind"] == "agent"
    assert event["incomplete"] is True


@pytest.mark.parametrize(
    "stage", ["parse", "dispatch", "should_terminate", "next_message"]
)
def test_framework_component_fault_is_not_an_agent_failure(tmp_path, stage):
    from eval_framework.environments import FileToolsEnvironment
    from eval_framework.harness import (
        FixedFollowupUserSimulator,
        ToolRouter,
        run_conversation,
    )

    def fail(*args):
        raise RuntimeError("plugin failed")

    router = ToolRouter()
    simulator = FixedFollowupUserSimulator("read a")
    setattr(router if stage in {"parse", "dispatch"} else simulator, stage, fail)
    result = run_conversation(
        lambda history: {
            "tool_calls": [{"name": "read_file", "arguments": {"path": "a"}}]
        },
        environment=FileToolsEnvironment(parent=tmp_path),
        initial_state={"a": "value"},
        simulator=simulator,
        router=router,
    )
    assert result["errors"][0]["kind"] == "harness"
    assert result["final_files"] == {"a": "value"}


@pytest.mark.parametrize(
    "response",
    [
        None,
        {"tool_calls": "not a list"},
        {"tool_calls": [{"name": "unknown", "arguments": {}}]},
    ],
)
def test_malformed_agent_response_remains_agent_failure(tmp_path, response):
    from eval_framework.environments import FileToolsEnvironment
    from eval_framework.harness import FixedFollowupUserSimulator, run_conversation

    result = run_conversation(
        lambda history: response,
        environment=FileToolsEnvironment(parent=tmp_path),
        initial_state={},
        simulator=FixedFollowupUserSimulator("request"),
    )
    assert result["errors"][0]["kind"] == "agent"


def test_tracer_preserves_partial_file_events_and_unknown_usage():
    from eval_framework.harness.tracer import aggregate_usage, read_file_events

    started = {"id": "call", "type": "tool", "end_time": None}
    completed = {**started, "end_time": "done", "output": "ok"}
    partial = {"id": "partial", "type": "tool", "end_time": None}
    events = read_file_events(
        "\n".join(map(json.dumps, [started, completed, partial])) + "\nbad"
    )
    assert events[0]["output"] == "ok"
    assert events[0]["source"] == "nanobot.file_evidence"
    assert events[1]["incomplete"] is True
    assert (
        aggregate_usage([{"usage": {}}, {"usage": {"total_tokens": 3}}])["total_tokens"]
        is None
    )


def test_inspect_environment_runs_in_owned_sample_and_retains_native_cleanup(tmp_path):
    import sys

    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.solver import solver
    from inspect_ai.util import sandbox

    from eval_framework.environments import InspectFileToolsEnvironment

    paths = []

    @solver
    def execute():
        async def solve(state, generate):
            environment = InspectFileToolsEnvironment(
                sandbox(),
                config={
                    "nanobot_root": str(tmp_path),
                    "python": sys.executable,
                    "sandbox": "local",
                },
                harness_dir=str(
                    Path(__file__).resolve().parents[2] / "src/eval_framework/benchmark"
                ),
                mode="module",
            )
            assert await environment.reset({"literal": "中文\r\n"}) is None
            paths.append(environment.workspace)
            assert await environment.final_state() == {"literal": "中文\r\n"}
            await environment.reset({"new": "replacement"})
            assert await environment.snapshot() == {"new": "replacement"}
            await environment.teardown()
            state.completed = True
            return state

        return solve

    logs = inspect_eval(
        Task(dataset=[Sample(input="offline")], solver=execute(), sandbox="local"),
        model="mockllm/model",
        log_dir=str(tmp_path / "logs"),
        display="none",
        notification=False,
        ctl_server=False,
    )
    assert logs[0].status == "success"
    assert paths and not Path(paths[0]).exists()
