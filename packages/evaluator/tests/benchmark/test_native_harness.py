"""Native Inspect integration with deterministic model outputs; no network."""

from __future__ import annotations

import asyncio

import pytest
from inspect_ai import Task
from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageAssistant, ModelOutput, ModelUsage, get_model
from inspect_ai.tool import ToolCall


def output(text="", calls=None, stop_reason="stop"):
    value = ModelOutput.from_content("mockllm/model", text)
    value.choices[0].message = ChatMessageAssistant(content=text, tool_calls=calls)
    value.choices[0].stop_reason = stop_reason
    value.usage = ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15)
    return value


def call(identifier, name, **arguments):
    return ToolCall(id=identifier, function=name, arguments=arguments)


def run_native(
    tmp_path,
    outputs,
    *,
    followups=(),
    max_steps=8,
    max_tool_calls=8,
    tools=None,
    samples=1,
    token_limit=None,
    timeout_seconds=None,
    max_consecutive_errors=None,
):
    from eval_contracts.benchmark import TaskInput
    from eval_framework.harness.adapters.inspect_solver import harness_solver

    tasks = {
        str(i): TaskInput(
            task_id=str(i),
            prompt="Create result.txt",
            followups=list(followups),
            initial_state={"files": {"input.txt": "keep\r\n"}},
            max_steps=max_steps,
            tools=tools or ["write_file", "read_file", "list_dir", "edit_file"],
        )
        for i in range(samples)
    }
    task = Task(
        dataset=[Sample(id=i, input=t.prompt, target="") for i, t in tasks.items()],
        solver=harness_solver(
            tasks,
            max_tool_calls=max_tool_calls,
            timeout_seconds=timeout_seconds,
            max_consecutive_errors=max_consecutive_errors,
        ),
        sandbox="local",
        token_limit=token_limit,
    )
    model = get_model("mockllm/model", custom_outputs=outputs)
    log = inspect_eval(
        task,
        model=model,
        log_dir=str(tmp_path / "logs"),
        display="none",
        notification=False,
        ctl_server=False,
        max_samples=4,
        fail_on_error=False,
    )[0]
    assert log.status == "success", log.error
    return log


def observation(log, index=0):
    return log.samples[index].metadata["harness_observation"]


def test_native_loop_multitool_followups_and_independent_evidence(tmp_path):
    log = run_native(
        tmp_path,
        [
            output(
                calls=[
                    call("a", "write_file", path="result.txt", content="first"),
                    call("b", "read_file", path="result.txt"),
                ]
            ),
            output("first answer"),
            output(
                calls=[
                    call(
                        "c",
                        "edit_file",
                        path="result.txt",
                        old_text="first",
                        new_text="second",
                    )
                ]
            ),
            output("second answer"),
        ],
        followups=["Now change it to second"],
    )
    row = observation(log)
    assert row["status"] == "completed" and row["stop_reason"] == "completed"
    assert row["before_files"] == {"input.txt": "keep\r\n"}
    assert row["final_files"] == {"input.txt": "keep\r\n", "result.txt": "second"}
    assert [turn["output"] for turn in row["turns"]] == [
        "first answer",
        "second answer",
    ]
    assert row["turns"][0]["snapshot"]["result.txt"] == "first"
    assert row["evidence_complete"] is True
    events = log.samples[0].events
    assert sum(e.event == "model" for e in events) == 4
    assert sum(e.event == "tool" for e in events) == 3
    model_events = [e for e in events if e.event == "model"]
    assert [m.text for m in model_events[1].input if m.role == "user"] == [
        "Create result.txt"
    ]
    assert [m.text for m in model_events[2].input if m.role == "user"] == [
        "Create result.txt",
        "Now change it to second",
    ]
    assert len(row["trace"]["turns"]) == 2
    tool_events = [e for e in row["events"] if e["type"] == "tool"]
    assert [e["tool_call_id"] for e in tool_events] == ["a", "b", "c"]
    assert tool_events[0]["before_files"] == {"input.txt": "keep\r\n"}
    assert tool_events[0]["after_files"]["result.txt"] == "first"


@pytest.mark.parametrize(
    "bad,code",
    [
        (call("a", "unknown", path="result.txt"), "tool_not_found"),
        (call("a", "write_file", path="result.txt"), "missing_argument"),
        (call("a", "write_file", path="result.txt", content=123), "argument_type"),
    ],
)
def test_native_router_rejections_are_logged_and_recoverable(tmp_path, bad, code):
    row = observation(
        run_native(
            tmp_path,
            [
                output(calls=[bad]),
                output(
                    calls=[call("b", "write_file", path="result.txt", content="ok")]
                ),
                output("done"),
            ],
        )
    )
    tools = [e for e in row["events"] if e["type"] == "tool"]
    assert tools[0]["validation_code"] == code
    assert tools[0]["execution_started"] is False
    assert "result.txt" not in tools[0]["after_files"]
    assert tools[1]["execution_started"] is True
    assert row["final_files"]["result.txt"] == "ok"
    assert row["evidence_complete"] is True


def test_tool_budget_checked_inside_batch_before_side_effect(tmp_path):
    row = observation(
        run_native(
            tmp_path,
            [
                output(
                    calls=[
                        call("a", "write_file", path="result.txt", content="first"),
                        call("b", "write_file", path="result.txt", content="FORBIDDEN"),
                    ]
                )
            ],
            max_tool_calls=1,
        )
    )
    assert row["final_files"]["result.txt"] == "first"
    assert row["stop_reason"] == "tool_call_limit"
    assert row["status"] == "error" and row["evidence_complete"] is False


def test_model_step_budget_applies_across_followup_turns(tmp_path):
    row = observation(
        run_native(
            tmp_path, [output("first answer")], followups=["continue"], max_steps=1
        )
    )
    assert row["stop_reason"] == "step_limit"
    assert len(row["turns"]) == 1


def test_truncated_generation_cannot_complete_or_execute_tools(tmp_path):
    row = observation(
        run_native(
            tmp_path,
            [
                output(
                    calls=[
                        call("a", "write_file", path="result.txt", content="FORBIDDEN")
                    ],
                    stop_reason="max_tokens",
                )
            ],
        )
    )
    assert "result.txt" not in row["final_files"]
    assert row["status"] == "error" and row["stop_reason"] == "model_length"


def test_concurrent_samples_use_separate_environments(tmp_path):
    def answer(messages, tools, tool_choice, config):
        if messages[-1].role == "tool":
            return output("done")
        return output(calls=[call("a", "write_file", path="result.txt", content="ok")])

    log = run_native(tmp_path, answer, samples=2)
    for sample in log.samples:
        row = sample.metadata["harness_observation"]
        assert row["before_files"] == {"input.txt": "keep\r\n"}
        assert row["final_files"]["result.txt"] == "ok"
        assert row["evidence_complete"] is True


def test_router_accepts_domain_schema_and_preserves_json_types():
    from eval_framework.harness.core.tool_router import ToolRouter

    router = ToolRouter(
        [
            {
                "name": "set_count",
                "description": "Set count",
                "parameters": {
                    "type": "object",
                    "properties": {"count": {"type": "integer", "minimum": 1}},
                    "required": ["count"],
                    "additionalProperties": False,
                },
            }
        ]
    )
    assert router.validate(call("a", "set_count", count=2)) is None
    assert router.validate(call("b", "set_count", count="2")).code == "argument_type"
    assert router.validate(call("c", "set_count", count=0)).code == "invalid_argument"


def test_cancellation_is_propagated_and_closes_agent():
    from eval_framework.harness.core.agent_loop import run_agent_loop
    from eval_framework.harness.core.session_state import SessionState
    from eval_framework.harness.core.tool_router import ToolRouter
    from eval_framework.harness.user_simulator import FixedFollowupUserSimulator

    class Agent:
        closed = False

        async def step(self, state):
            raise asyncio.CancelledError()

        async def close(self):
            self.closed = True

    agent = Agent()
    state = SessionState(task_id="cancel")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_agent_loop(
                agent,
                state,
                router=ToolRouter([]),
                environment=None,
                simulator=FixedFollowupUserSimulator("start"),
                max_steps=2,
            )
        )
    assert agent.closed
    assert state.stop_reason == "cancelled"


def test_repeated_call_ids_across_turns_keep_separate_snapshots(tmp_path):
    row = observation(
        run_native(
            tmp_path,
            [
                output(
                    calls=[
                        call("same", "write_file", path="result.txt", content="first")
                    ]
                ),
                output("first answer"),
                output(
                    calls=[
                        call("same", "write_file", path="result.txt", content="second")
                    ]
                ),
                output("second answer"),
            ],
            followups=["continue"],
        )
    )
    tools = [e for e in row["events"] if e["type"] == "tool"]
    assert tools[0]["after_files"]["result.txt"] == "first"
    assert tools[1]["before_files"]["result.txt"] == "first"
    assert [e["turn"] for e in tools] == [1, 2]
    assert row["evidence_complete"] is True


def test_schema_constraints_not_representable_by_inspect_fail_explicitly():
    from eval_framework.harness.core.tool_router import ToolRouter

    with pytest.raises(ValueError, match="schema"):
        ToolRouter(
            [
                {
                    "name": "choice",
                    "description": "Choice",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "oneOf": [{"required": ["a"]}],
                    },
                }
            ]
        ).tool_infos()


def test_custom_stop_policy_prevents_first_generation():
    from eval_framework.harness.core.agent_loop import run_agent_loop
    from eval_framework.harness.core.session_state import SessionState
    from eval_framework.harness.core.tool_router import ToolRouter
    from eval_framework.harness.user_simulator import FixedFollowupUserSimulator

    class Agent:
        async def step(self, state):
            raise AssertionError("stopped policy must prevent generation")

        async def close(self):
            pass

    state = SessionState(task_id="policy")
    asyncio.run(
        run_agent_loop(
            Agent(),
            state,
            router=ToolRouter([]),
            environment=None,
            simulator=FixedFollowupUserSimulator("hello"),
            stop_conditions=(lambda state, phase: "policy_stop",),
        )
    )
    assert state.stop_reason == "policy_stop" and state.steps == 0


def test_path_escape_is_recoverable_tool_error_and_never_writes_outside(tmp_path):
    row = observation(
        run_native(
            tmp_path,
            [
                output(
                    calls=[
                        call("a", "write_file", path="../outside", content="FORBIDDEN"),
                    ]
                ),
                output("cannot write outside"),
            ],
        )
    )
    assert row["final_files"] == {"input.txt": "keep\r\n"}
    event = next(e for e in row["events"] if e["type"] == "tool")
    assert event["tool_error"] and "inside the workspace" in event["error"]


def test_provider_failure_never_becomes_success(tmp_path):
    row = observation(run_native(tmp_path, []))
    assert row["status"] == "error"
    assert row["evidence_complete"] is False
    assert row["errors"][0]["kind"] == "provider"


def test_native_token_limit_is_agent_failure_not_provider_failure(tmp_path):
    row = observation(run_native(tmp_path, [output("done")], token_limit=1))
    assert row["status"] == "error" and row["evidence_complete"] is False
    assert row["stop_reason"] == "token_limit"
    assert all(e["kind"] == "agent" for e in row["errors"])


@pytest.mark.parametrize("failure", ["reset", "step", "teardown"])
def test_environment_failures_preserve_partial_evidence_and_cleanup(failure):
    import errno

    from eval_contracts.benchmark import TaskInput
    from eval_framework.harness.adapters.agent.base import AgentAction
    from eval_framework.harness.adapters.inspect_solver import execute_native_task

    class Environment:
        closed = False

        def tool_schemas(self):
            return [
                {
                    "name": "update",
                    "description": "Update",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                }
            ]

        async def reset(self, initial_state):
            if failure == "reset":
                raise OSError(errno.EIO, "setup failed")

        async def snapshot(self):
            return {"untouched": "original"}

        async def step(self, name, arguments):
            raise OSError(errno.ENOSPC, "disk full")

        async def teardown(self):
            self.closed = True
            if failure == "teardown":
                raise OSError(errno.EIO, "cleanup failed")

    class Agent:
        closed = False

        async def step(self, state):
            return AgentAction(
                ChatMessageAssistant(
                    content="done",
                    tool_calls=[call("a", "update")] if failure == "step" else None,
                )
            )

        async def close(self):
            self.closed = True

    environment, agent = Environment(), Agent()
    with pytest.raises(Exception) as error:
        asyncio.run(
            execute_native_task(
                TaskInput(task_id="failure", prompt="go", initial_state={}),
                agent=agent,
                environment=environment,
            )
        )
    row = error.value.benchmark_observation
    assert row["status"] == "error" and row["evidence_complete"] is False
    assert row["final_files"] == {"untouched": "original"}
    assert any(e["kind"] == "environment" for e in row["errors"])
    assert environment.closed and agent.closed


def test_nested_schema_constraints_cannot_be_silently_lost():
    from eval_framework.harness.core.tool_router import ToolRouter

    with pytest.raises(ValueError, match="schema"):
        ToolRouter(
            [
                {
                    "name": "filter",
                    "description": "Filter",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "value": {
                                "type": "string",
                                "not": {"enum": ["forbidden"]},
                            }
                        },
                    },
                }
            ]
        ).tool_infos()


def test_schema_default_allows_extra_arguments_in_advertised_tools():
    from eval_framework.harness.core.tool_router import ToolRouter

    router = ToolRouter(
        [
            {
                "name": "echo",
                "description": "Echo",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            }
        ]
    )
    assert router.validate(call("a", "echo", extra="valid")) is None
    assert router.tool_infos()[0].parameters.additionalProperties is True


def test_missing_native_generation_is_not_complete_evidence(tmp_path):
    from eval_framework.harness.trace.timeline_extractor import extract_timeline
    from inspect_ai.log import read_eval_log

    log = run_native(tmp_path, [output("done")])
    log = read_eval_log(log.location, resolve_attachments=True)
    partial = [e for e in log.samples[0].events if e.event != "model"]
    row = asyncio.run(extract_timeline("0", partial))
    assert row["evidence_complete"] is False
    assert row["trace"]["evidence_complete"] is False


@pytest.mark.parametrize("remove", ["one_model", "all_tools"])
def test_deleted_native_event_groups_fail_evidence_gate(tmp_path, remove):
    from eval_framework.harness.trace.timeline_extractor import extract_timeline
    from inspect_ai.log import read_eval_log

    log = run_native(
        tmp_path,
        [
            output(
                calls=[
                    call("a", "write_file", path="result.txt", content="ok"),
                ]
            ),
            output("done"),
        ],
    )
    log = read_eval_log(log.location, resolve_attachments=True)
    events = list(log.samples[0].events)
    if remove == "one_model":
        events.remove(next(e for e in events if e.event == "model"))
    else:
        events = [
            e
            for e in events
            if e.event != "tool"
            and not (
                e.event == "info"
                and isinstance(e.data, dict)
                and e.data.get("kind") in {"route_start", "route_end"}
            )
        ]
    row = asyncio.run(extract_timeline("0", events))
    assert row["final_files"]["result.txt"] == "ok"
    assert row["evidence_complete"] is False


def test_nested_object_schema_keeps_default_additional_properties():
    from eval_framework.harness.core.tool_router import ToolRouter

    router = ToolRouter(
        [
            {
                "name": "echo",
                "description": "Echo",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "nested": {
                            "type": "object",
                            "properties": {"x": {"type": "integer"}},
                        }
                    },
                },
            }
        ]
    )
    assert router.validate(call("a", "echo", nested={"x": 2, "extra": "yes"})) is None
    schema = router.tool_infos()[0].parameters.model_dump(exclude_none=True)
    assert schema["properties"]["nested"].get("additionalProperties", True) is True


def test_error_stop_is_projected_as_agent_failure_with_partial_evidence(tmp_path):
    row = observation(
        run_native(
            tmp_path, [output(calls=[call("bad", "missing")])], max_consecutive_errors=1
        )
    )
    assert row["stop_reason"] == "error_limit"
    assert row["errors"][0]["kind"] == "agent"
    assert row["trace"]["stop_reason"] == "error_limit"
    assert row["evidence_complete"] is False


@pytest.mark.parametrize(
    "damage",
    ["duplicate_uuid", "duplicate_end", "wrong_call", "wrong_turn", "orphan_end"],
)
def test_corrupt_native_associations_never_become_complete(tmp_path, damage):
    from eval_framework.benchmark.metrics import score_task
    from eval_framework.harness.trace.timeline_extractor import extract_timeline
    from inspect_ai.log import read_eval_log

    log = run_native(
        tmp_path,
        [
            output(calls=[call("a", "write_file", path="result.txt", content="ok")]),
            output("done"),
        ],
    )
    log = read_eval_log(log.location, resolve_attachments=True)
    events = list(log.samples[0].events)
    end = next(
        e
        for e in events
        if e.event == "info"
        and isinstance(e.data, dict)
        and e.data.get("kind") == "route_end"
    )
    if damage == "duplicate_uuid":
        models = [e for e in events if e.event == "model"]
        models[1].uuid = models[0].uuid
    elif damage == "duplicate_end":
        events.append(end.model_copy(deep=True, update={"uuid": "duplicate-end"}))
    elif damage == "wrong_call":
        end.data["call_id"] = "other"
    elif damage == "wrong_turn":
        end.data["turn"] = 99
    else:
        events.append(
            end.model_copy(
                deep=True,
                update={"uuid": "orphan", "data": {**end.data, "route_id": "missing"}},
            )
        )
    row = asyncio.run(extract_timeline("0", events))
    assert row["final_files"]["result.txt"] == "ok"
    assert row["evidence_complete"] is False
    assert row["trace"]["evidence_complete"] is False
    assert any(e["kind"] == "evidence" for e in row["errors"])
    task = {
        "id": "0",
        "prompt": "Create result.txt",
        "fixtures": {},
        "followups": [],
        "allowed_tools": ["write_file"],
        "oracle": {"expected_files": {"result.txt": "ok"}},
    }
    assert score_task(task, row)["verdict"] == "INCONCLUSIVE"


def test_converted_turns_and_steps_reference_persisted_native_events(tmp_path):
    from eval_framework.harness.trace.timeline_extractor import extract_timeline
    from inspect_ai.log import read_eval_log

    log = read_eval_log(
        run_native(tmp_path, [output("done")]).location, resolve_attachments=True
    )
    native = log.samples[0].events
    row = asyncio.run(extract_timeline("0", native))
    ids = {e.uuid for e in native}
    assert row["evidence_complete"]
    assert all(e["native_event_id"] in ids for e in row["events"])


def test_route_endpoints_cannot_agree_on_wrong_existing_turn(tmp_path):
    from eval_framework.harness.trace.timeline_extractor import extract_timeline
    from inspect_ai.log import read_eval_log

    log = run_native(
        tmp_path,
        [
            output(calls=[call("a", "write_file", path="result.txt", content="first")]),
            output("first answer"),
            output("second answer"),
        ],
        followups=["continue"],
    )
    native = read_eval_log(log.location, resolve_attachments=True).samples[0].events
    assert asyncio.run(extract_timeline("0", native))["evidence_complete"]
    for event in native:
        if (
            event.event == "info"
            and isinstance(event.data, dict)
            and event.data.get("kind") in {"route_start", "route_end"}
        ):
            event.data["turn"] = 2
    row = asyncio.run(extract_timeline("0", native))
    assert row["final_files"]["result.txt"] == "first"
    assert row["evidence_complete"] is False
    assert any(e["code"] == "TURN_ASSOCIATION_MISMATCH" for e in row["errors"])
