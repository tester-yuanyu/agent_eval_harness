"""Evidence is persisted and independently readable through Inspect APIs."""

import json
from datetime import UTC, datetime

import pytest
from agent_trace_sdk import (
    EventRule,
    EvidenceReader,
    LocalEvidenceSink,
    TraceCollector,
    TraceContext,
)
from inspect_ai.event import InfoEvent
from inspect_ai.log import read_eval_log


def test_events_and_collection_state_live_in_native_log(tmp_path):
    context = TraceContext("native-trial")
    sink = LocalEvidenceSink(tmp_path / "evidence", context)
    collector = TraceCollector(
        "agent-run",
        context=context,
        sink=sink,
        rules={"test": EventRule("result", ("ok",), ("ok",))},
    )
    collector.record("test", {"ok": True})
    path = sink.directory / "trace.inspect.json"
    assert path.exists()
    log = read_eval_log(path)
    sample = log.samples[0]
    assert sample.target == "" and sample.input == ""
    assert isinstance(sample.events[0], InfoEvent)
    assert sample.events[0].data["payload"] == {"ok": True}
    assert sample.metadata["evidence"]["written_count"] == 1
    assert sample.metadata["evidence"]["collection_closed"] is False
    sink.finish(execution_completed=True)
    events, manifest = EvidenceReader().read(sink.directory)
    assert len(events) == 1 and manifest["status"] == "COMPLETE"
    assert not (sink.directory / "events.jsonl").exists()
    assert not (sink.directory / "collection.json").exists()


def test_historical_jsonl_evidence_is_read_only_compatible(tmp_path):
    event = dict(
        event_id="legacy-event",
        event_type="test",
        trace_id="legacy",
        run_id="legacy-run",
        timestamp="2026-10-20T00:00:00Z",
        sequence=1,
        payload={},
        validation_status="VALID",
    )
    state = dict(
        trace_id="legacy",
        attempted_count=1,
        written_count=1,
        last_sequence=1,
        execution_completed=True,
        collection_closed=True,
        issues=[],
    )
    (tmp_path / "events.jsonl").write_text(json.dumps(event) + "\n")
    (tmp_path / "collection.json").write_text(json.dumps(state))
    events, manifest = EvidenceReader().read(tmp_path)
    assert events == [event] and manifest["status"] == "COMPLETE"
    assert not (tmp_path / "trace.inspect.json").exists()


def test_corrupt_native_log_never_falls_back_to_legacy_files(tmp_path):
    test_historical_jsonl_evidence_is_read_only_compatible(tmp_path)
    (tmp_path / "trace.inspect.json").write_text("damaged native log")
    events, state = EvidenceReader().read(tmp_path)
    assert events == [] and state["status"] == "EXPORT_FAILED"


@pytest.mark.parametrize("final_write", [False, True])
def test_failed_native_write_preserves_disk_evidence_without_memory_upgrade(
    tmp_path, monkeypatch, final_write
):
    context = TraceContext("failed-write")
    sink = LocalEvidenceSink(tmp_path / "evidence", context)
    collector = TraceCollector(
        "run",
        context=context,
        sink=sink,
        rules={"test": EventRule("result", ())},
    )
    collector.record("test")
    before = (sink.directory / "trace.inspect.json").read_bytes()

    def fail(*args, **kwargs):
        raise OSError("write unavailable")

    monkeypatch.setattr("agent_trace_sdk.native.write_eval_log", fail)
    if not final_write:
        collector.record("test")
    sink.finish(execution_completed=True)
    events, state = EvidenceReader().read(
        sink.directory, memory_manifest=sink.manifest()
    )
    assert len(events) == 1
    assert state["status"] == "EXPORT_FAILED"
    assert state["collection_closed"] is False
    assert state["execution_completed"] is False
    assert (sink.directory / "trace.inspect.json").read_bytes() == before
    # Offline recovery knows only the last committed snapshot, still incomplete.
    assert EvidenceReader().read(sink.directory)[1]["status"] == "STILL_OPEN"


@pytest.mark.parametrize(
    "value", [(1, 2), datetime(2026, 10, 21, tzinfo=UTC), object()]
)
def test_native_collector_does_not_bypass_business_sanitizer(tmp_path, value):
    context = TraceContext("non-json-value")
    sink = LocalEvidenceSink(tmp_path / "evidence", context)
    collector = TraceCollector(
        "run",
        context=context,
        sink=sink,
        rules={"test": EventRule("result", ("value",))},
    )
    collector.record("test", {"value": value})
    sink.finish(execution_completed=True)
    events, state = EvidenceReader().read(sink.directory)
    assert state["attempted_count"] == state["written_count"] == 1
    assert len(collector.export()) == len(events) == 1
    assert events[0]["payload"]["value"] == (
        [1, 2] if isinstance(value, tuple) else "[UNSERIALIZABLE]"
    )
    assert state["status"] == ("COMPLETE" if isinstance(value, tuple) else "PARTIAL")


@pytest.mark.parametrize("secret", [b"review-secret", b"\xffreview-secret"])
def test_non_json_secret_does_not_escape_as_native_validation_error(tmp_path, secret):
    context = TraceContext("redaction-first")
    sink = LocalEvidenceSink(tmp_path / "evidence", context)
    collector = TraceCollector(
        "run",
        context=context,
        sink=sink,
        rules={"test": EventRule("result", ("data",))},
    )
    collector.record("test", {"data": {"password": secret}})
    sink.finish(execution_completed=True)
    events, state = EvidenceReader().read(sink.directory)
    assert state["attempted_count"] == 1 and state["status"] == "PARTIAL"
    assert events[0]["payload"] == {"data": {}}
    assert "review-secret" not in (sink.directory / "trace.inspect.json").read_text()
    assert len(collector.export()) == 1


def test_memory_downgrade_does_not_duplicate_persisted_issues(tmp_path):
    context = TraceContext("one-issue")
    sink = LocalEvidenceSink(tmp_path / "evidence", context)
    TraceCollector("run", sink=sink, context=context).record("unknown")
    sink.finish(execution_completed=True)
    _, state = EvidenceReader().read(sink.directory, memory_manifest=sink.manifest())
    assert state["issues"] == [
        {
            "kind": "partial",
            "code": "INVALID_OR_TRUNCATED_EVENT",
            "sequence": 1,
        }
    ]
