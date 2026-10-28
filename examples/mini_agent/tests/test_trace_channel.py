from agent_trace_sdk import EvidenceReader, LocalEvidenceSink, TraceContext

from minimal_agent.runtime.agent import MinimalAgent
from tests.support.model_client import DeterministicModelClient
from tests.test_runtime_agent import echo_registry, ready_intent, tool_call


def test_observation_does_not_change_business_calls_or_result(tmp_path):
    def run(sink=None):
        client = DeterministicModelClient(
            [
                ready_intent(),
                tool_call(),
                {"type": "message", "content": "done"},
            ]
        )
        agent = MinimalAgent(
            client,
            echo_registry(),
            run_id_factory=lambda: "run-fixed",
            evidence_sink=sink,
        )
        result = agent.run("echo")
        return result, client

    original, original_client = run()
    sink = LocalEvidenceSink(tmp_path / "trace", TraceContext())
    observed, client = run(sink)
    sink.finish(execution_completed=True)
    events, manifest = EvidenceReader().read(sink.directory)
    assert manifest["status"] == "COMPLETE"
    assert len(events) == len(observed.events)
    assert [e["event_id"] for e in events] == [e["event_id"] for e in observed.events]
    assert observed.status == original.status
    assert observed.intent_result == original.intent_result
    assert observed.final_response == original.final_response
    assert len(observed.tool_calls) == len(original.tool_calls) == 1
    assert observed.tool_calls[0].output == original.tool_calls[0].output
    assert client.requests == original_client.requests
    assert client.remaining_responses == original_client.remaining_responses == 0


def test_failed_channel_keeps_full_legacy_events_and_business_success(
    tmp_path, monkeypatch
):
    sink = LocalEvidenceSink(tmp_path / "trace", TraceContext())

    def fail_write(*args, **kwargs):
        raise OSError("native log write unavailable")

    monkeypatch.setattr("agent_trace_sdk.native.write_eval_log", fail_write)
    agent = MinimalAgent(
        DeterministicModelClient(
            [
                ready_intent(),
                tool_call(),
                {"type": "message", "content": "done"},
            ]
        ),
        echo_registry(),
        evidence_sink=sink,
    )
    result = agent.run("echo")
    sink.finish(execution_completed=True)
    assert result.status == "SUCCESS"
    assert len(result.tool_calls) == 1
    assert result.events[-1]["event_type"] == "run_finished"
    events, state = EvidenceReader().read(
        sink.directory, memory_manifest=sink.manifest()
    )
    assert events == []
    assert state["status"] == "EXPORT_FAILED"


def test_business_failed_can_have_complete_evidence(tmp_path):
    sink = LocalEvidenceSink(tmp_path / "trace", TraceContext())
    agent = MinimalAgent(
        DeterministicModelClient([ready_intent(), tool_call(name="missing")]),
        echo_registry(),
        evidence_sink=sink,
    )
    result = agent.run("missing tool")
    sink.finish(execution_completed=True)
    assert result.status == "FAILED"
    assert sink.manifest()["status"] == "COMPLETE"
