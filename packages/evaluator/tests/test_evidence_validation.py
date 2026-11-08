"""Native and historical readers share field rules, not corruption policies."""

import json

import pytest


def manifest():
    return dict(
        trace_id="trial",
        attempted_count=1,
        written_count=1,
        last_sequence=1,
        execution_completed=True,
        collection_closed=True,
        issues=[],
    )


def event():
    return dict(
        event_id="event",
        event_type="test",
        trace_id="trial",
        run_id="run",
        timestamp="2026-11-08T00:00:00Z",
        sequence=1,
        payload={},
    )


@pytest.mark.parametrize(
    "update",
    [
        {"attempted_count": True},
        {"written_count": -1},
        {"last_sequence": 1.5},
        {"execution_completed": 1},
        {"collection_closed": None},
        {"issues": {}},
        {"issues": [{"kind": "unknown"}]},
    ],
)
def test_manifest_rejects_invalid_counts_flags_and_issues(update):
    from agent_trace_sdk.validation import valid_manifest

    assert valid_manifest(manifest())
    assert not valid_manifest({**manifest(), **update})
    assert not valid_manifest(None)


@pytest.mark.parametrize("value", [None, [], {"sequence": True}, {"sequence": "1"}])
def test_unreadable_envelope_raises_before_completeness_checks(value):
    from agent_trace_sdk.validation import valid_event_envelope

    with pytest.raises(ValueError):
        valid_event_envelope(value)


def test_readable_envelope_retains_invalid_payload_for_diagnostics():
    from agent_trace_sdk.validation import valid_event_envelope

    assert valid_event_envelope(event())
    assert not valid_event_envelope({**event(), "payload": []})
    assert not valid_event_envelope({**event(), "run_id": None})


def test_legacy_keeps_readable_records_but_native_rejects_damaged_log(tmp_path):
    from agent_trace_sdk import EvidenceReader, InspectEvidenceSink, TraceContext
    from inspect_ai.event import InfoEvent
    from inspect_ai.log import read_eval_log, write_eval_log

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "collection.json").write_text(json.dumps(manifest()))
    (legacy / "events.jsonl").write_text(
        json.dumps({"sequence": True}) + "\n" + json.dumps(event()) + "\n"
    )
    events, state = EvidenceReader().read(legacy)
    assert events == [event()]
    assert any(i["code"] == "DAMAGED_RECORD" for i in state["issues"])

    sink = InspectEvidenceSink(tmp_path / "native", TraceContext("trial"))
    sink.finish(execution_completed=True)
    path = sink.directory / "trace.inspect.json"
    log = read_eval_log(path)
    log.samples[0].events = [
        InfoEvent(source="agent_evidence", data={"sequence": True}),
        InfoEvent(source="agent_evidence", data=event()),
    ]
    write_eval_log(log, path, format="json")
    events, state = EvidenceReader().read(sink.directory)
    assert events == []
    assert state["status"] == "EXPORT_FAILED"
    assert any(i["code"] == "NATIVE_LOG_READ_FAILED" for i in state["issues"])
