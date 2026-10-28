from minimal_agent.runtime.agent import MinimalAgent
from minimal_agent.runtime.intent_router import IntentRouter
from minimal_agent.runtime.model_client import ModelInvocationError
from minimal_agent.runtime.tool_registry import ToolRegistry
from minimal_agent.runtime.trace import TraceCollector
from tests.support.model_client import DeterministicModelClient


def intent_candidate(parameters: dict[str, object]) -> dict[str, object]:
    return {
        "intent": "query_user",
        "status": "READY",
        "next_action": "CALL_TOOL",
        "parameters": parameters,
        "missing_parameters": [],
        "reason": "候选结果。",
    }


def event_types(trace: TraceCollector) -> list[str]:
    return [event["event_type"] for event in trace.export()]


def test_intent_trace_records_candidate_definition_normalization_and_decision() -> None:
    trace = TraceCollector("run-intent")
    router = IntentRouter(
        DeterministicModelClient([intent_candidate({"user_id": "9075333"})])
    )

    router.run_intent_only("查询用户 ID 9075333", trace=trace)

    assert event_types(trace) == [
        "intent_requested",
        "intent_candidate_received",
        "intent_definition_resolved",
        "intent_parameter_normalized",
        "intent_contract_validated",
        "intent_decided",
    ]
    normalized = trace.export()[3]["payload"]
    assert normalized["field"] == "user_id"
    assert normalized["before"] == "9075333"
    assert normalized["after"] == 9075333


def test_validation_failure_trace_names_public_field_without_hidden_reasoning() -> None:
    trace = TraceCollector("run-invalid")
    router = IntentRouter(
        DeterministicModelClient([intent_candidate({"user_id": 0})])
    )

    router.run_intent_only("查询用户 ID 0", trace=trace)

    failure = next(
        event
        for event in trace.export()
        if event["event_type"] == "intent_parameter_validation_failed"
    )
    assert failure["payload"]["fields"] == ["user_id"]
    assert set(failure["payload"]).isdisjoint(
        {"thought", "reasoning", "chain_of_thought", "expected", "score", "case_id"}
    )


def test_semantic_constraint_failure_trace_records_no_evaluation_data() -> None:
    trace = TraceCollector("run-or")
    router = IntentRouter(
        DeterministicModelClient(
            [
                intent_candidate(
                    {"user_id": "9075333", "phone": "13800000001"}
                )
            ]
        )
    )

    router.run_intent_only(
        "查询用户 ID 9075333 或手机号 13800000001",
        trace=trace,
    )

    failure = next(
        event
        for event in trace.export()
        if event["event_type"] == "intent_semantic_constraint_failed"
    )
    assert failure["payload"]["constraint"] == "DisallowAlternativeQuery"
    assert set(failure["payload"]).isdisjoint({"expected", "score", "case_id"})


def make_agent(responses: list[object]) -> MinimalAgent:
    return MinimalAgent(
        DeterministicModelClient(responses),
        ToolRegistry(),
        run_id_factory=iter(["run-1", "run-2", "run-3"]).__next__,
    )


def test_direct_intent_calls_replace_last_trace_snapshot() -> None:
    agent = make_agent(
        [
            intent_candidate({"user_id": "10001"}),
            intent_candidate({"phone": "13800000001"}),
        ],
    )

    agent.run_intent_only("按 ID 查询")
    first = agent.intent_trace_snapshot()
    agent.run_intent_only("按手机号查询")
    second = agent.intent_trace_snapshot()

    assert first[0]["run_id"] == "run-1"
    assert second[0]["run_id"] == "run-2"
    assert all(event["run_id"] == "run-2" for event in second)


def test_full_run_contains_one_intent_validation_sequence() -> None:
    agent = make_agent(
        [intent_candidate({"user_id": 10001}), {"type": "message", "content": "完成"}],
    )

    result = agent.run("查询用户")

    assert [event["event_type"] for event in result.events].count(
        "intent_candidate_received"
    ) == 1
    assert [event["event_type"] for event in result.events].count("intent_decided") == 1


def test_intent_trace_snapshot_returns_defensive_copies() -> None:
    agent = make_agent([intent_candidate({"user_id": 10001})])
    agent.run_intent_only("查询用户")

    mutated = agent.intent_trace_snapshot()
    candidate = next(
        event for event in mutated if event["event_type"] == "intent_candidate_received"
    )
    candidate["payload"]["intent"] = "changed"

    saved_candidate = next(
        event
        for event in agent.intent_trace_snapshot()
        if event["event_type"] == "intent_candidate_received"
    )
    assert saved_candidate["payload"]["intent"] == "query_user"


def test_direct_intent_failure_preserves_partial_trace() -> None:
    class FailingClient:
        def classify_intent(self, user_input: str) -> object:
            raise ModelInvocationError("fixture failure")

        def next_tool_step(self, request: object) -> object:
            raise AssertionError

    agent = MinimalAgent(
        FailingClient(),
        ToolRegistry(),
        run_id_factory=iter(["run-failed"]).__next__,
    )

    try:
        agent.run_intent_only("查询用户")
    except ModelInvocationError:
        pass
    else:
        raise AssertionError("expected model invocation failure")

    trace = agent.intent_trace_snapshot()
    assert trace
    assert trace[0]["event_type"] == "intent_requested"
