import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from agent_trace_sdk import (
    EventRule,
    EvidenceReader,
    LocalEvidenceSink,
    TraceCollector,
    TraceContext,
    status_for,
)
from conftest import intent
from support.model_client import DeterministicModelClient

from eval_framework import RunConfig, load_dataset, run_evaluation
from eval_framework.assertions import run_assertions
from eval_framework.evidence_requirements import evidence_requirement_issues
from eval_framework.provider import AdapterOutput
from eval_framework.schemas import AssertionResult, EvalCase
from eval_framework.scoring import score_assertions


def test_priority_and_business_failure_are_independent(tmp_path):
    issues = [{"kind": "partial"}, {"kind": "export"}]
    assert status_for(issues) == "EXPORT_FAILED"
    assert status_for(issues[:1]) == "PARTIAL"
    assert status_for([]) == "STILL_OPEN"
    assert status_for([], completed=True) == "COMPLETE"
    assert status_for([], available=False) == "UNAVAILABLE"
    sink = LocalEvidenceSink(tmp_path / "trace", TraceContext())
    sink.finish(execution_completed=False)
    assert sink.manifest()["status"] == "STILL_OPEN"


def test_sequence_shared_across_turns_invalid_events_retained(tmp_path):
    context = TraceContext()
    sink = LocalEvidenceSink(tmp_path / "trace", context)
    rules = {"test": EventRule("understanding", ("field",), ("field",))}
    for turn in range(2):
        collector = TraceCollector(
            f"run-{turn}",
            sink=sink,
            context=TraceContext(context.trace_id, turn),
            rules=rules,
        )
        collector.record("test", {"field": "ok"})
        collector.record("test", {})
    sink.finish(execution_completed=True)
    events, state = EvidenceReader().read(sink.directory)
    assert [e["sequence"] for e in events] == [1, 2, 3, 4]
    assert [e["turn_index"] for e in events] == [0, 0, 1, 1]
    assert [e["validation_status"] for e in events] == ["VALID", "INVALID"] * 2
    assert state["status"] == "PARTIAL"
    assert state["attempted_count"] == state["written_count"] == 4


def test_secret_truncation_and_unknown_events(tmp_path):
    context = TraceContext()
    sink = LocalEvidenceSink(tmp_path / "trace", context, max_string=24)
    collector = TraceCollector(
        "run",
        sink=sink,
        context=context,
        rules={
            "test": EventRule("understanding", ("data",), ("data",)),
        },
    )
    collector.record(
        "test",
        {
            "data": {
                "api_key": "secret-value",
                "text": "Bearer abc.def",
                "long": "x" * 40,
            }
        },
    )
    collector.record("unknown", {"credential": "secret-value"})
    sink.finish(execution_completed=True)
    raw = (sink.directory / "trace.inspect.json").read_text()
    assert "secret-value" not in raw and "abc.def" not in raw
    events, state = EvidenceReader().read(sink.directory)
    assert events[0]["truncated"] and events[0]["redacted_fields"]
    assert events[1]["validation_status"] == "INVALID"
    assert state["status"] == "PARTIAL"


def test_write_failure_leaves_tail_gap_and_memory_status(tmp_path, monkeypatch):
    import agent_trace_sdk.native as native

    context = TraceContext()
    sink = LocalEvidenceSink(tmp_path / "trace", context)
    collector = TraceCollector("run", sink=sink, context=context)
    monkeypatch.setattr(
        native,
        "write_eval_log",
        lambda *args: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    collector.record("unknown", {})
    sink.finish(execution_completed=True)
    events, state = EvidenceReader().read(
        sink.directory, memory_manifest=sink.manifest()
    )
    assert not events
    assert state["status"] == "EXPORT_FAILED"
    assert state["attempted_count"] == 1 and state["written_count"] == 0
    assert {i["code"] for i in state["issues"]} >= {
        "EVENT_WRITE_FAILED",
        "MANIFEST_WRITE_FAILED",
        "SEQUENCE_OR_COUNT_MISMATCH",
    }


def test_concurrent_trials_are_isolated(tmp_path):
    def run(index):
        context = TraceContext()
        sink = LocalEvidenceSink(tmp_path / str(index), context)
        collector = TraceCollector(
            str(index),
            sink=sink,
            context=context,
            rules={
                "test": EventRule("result", (), ()),
            },
        )
        for _ in range(10):
            collector.record("test")
        sink.finish(execution_completed=True)
        return EvidenceReader().read(sink.directory)

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(run, range(4)))
    assert len({s["trace_id"] for _, s in results}) == 4
    assert all(
        [e["sequence"] for e in events] == list(range(1, 11)) for events, _ in results
    )
    assert all(state["status"] == "COMPLETE" for _, state in results)


def test_precreated_association_and_partial_trace_after_exception(
    dataset_path, tmp_path
):
    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]

    class CrashedClient:
        def classify_intent(self, user_input):
            assert list(tmp_path.glob("*/evidence/*/association.json"))
            raise RuntimeError("interrupted")

    result = run_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test"),
        lambda execution: CrashedClient(),
        output_dir=tmp_path,
    )
    case = result.cases[0]
    assert case.execution_status != "COMPLETED"
    assert case.trace_events and case.agent_run_ids
    assert case.evidence_status == "STILL_OPEN"
    assert all(a.passed is None and a.applicable for a in case.assertion_results)
    assert case.quality_conclusion == "INCONCLUSIVE" and case.score is None


def test_independent_failure_never_falls_back_to_complete_embedded_events(
    dataset_path,
    tmp_path,
    monkeypatch,
):
    original = LocalEvidenceSink.record

    def fail_write(self, *args, **kwargs):
        monkeypatch.setattr(
            "agent_trace_sdk.native.write_eval_log",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
        )
        return original(self, *args, **kwargs)

    monkeypatch.setattr(LocalEvidenceSink, "record", fail_write)
    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    result = run_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test"),
        lambda execution: DeterministicModelClient([intent()]),
        output_dir=tmp_path,
    )
    case = result.cases[0]
    assert case.module_output is not None  # Agent business result survives
    assert case.execution_status == "COMPLETED"
    assert case.trace_events == []
    assert case.evidence_status == "EXPORT_FAILED"
    assert case.evaluation_validity == "INVALID"
    assert case.quality_conclusion != "PASS" and case.score is None


def test_positive_violation_decides_failure_after_exception():
    from conftest import assertion, link_case

    raw = link_case()
    raw["oracle"]["forbidden_tools"] = ["forbidden"]
    raw["oracle"]["evaluation"]["checks"] = [
        assertion("tool_not_called"),
        assertion("status_match"),
        assertion("tool_call_count"),
    ]
    case = EvalCase.model_validate(raw)
    output = AdapterOutput(
        None,
        [],
        None,
        [],
        None,
        [
            {
                "event_id": "event-1",
                "run_id": "run-1",
                "event_type": "tool_requested",
                "validation_status": "VALID",
                "payload": {"call_id": "call-1", "name": "forbidden", "arguments": {}},
            }
        ],
        "STILL_OPEN",
        False,
    )
    assertions = run_assertions(case, output, None)
    assert [a.passed for a in assertions] == [False, None, None]
    assert score_assertions(assertions, 100) == (None, "FAIL")
    assert score_assertions(
        [
            AssertionResult(
                name="unknown",
                weight=1,
                critical=False,
                applicable=True,
                passed=None,
            )
        ],
        0,
    ) == (None, "INCONCLUSIVE")


def test_process_death_preserves_flushed_events(tmp_path):
    directory = tmp_path / "killed"
    script = """
import os, sys
from agent_trace_sdk import LocalEvidenceSink, TraceContext, TraceCollector, EventRule
context = TraceContext('killed-trial')
sink = LocalEvidenceSink(sys.argv[1], context)
collector = TraceCollector('run', context=context, sink=sink,
                           rules={'test': EventRule('result', ())})
collector.record('test')
os._exit(7)
"""
    result = subprocess.run([sys.executable, "-c", script, str(directory)], check=False)
    assert result.returncode == 7
    events, state = EvidenceReader().read(directory)
    assert len(events) == 1 and state["status"] == "STILL_OPEN"
    with (directory / "trace.inspect.json").open("wb") as stream:
        stream.write(b'{"broken":\xff')
    events, state = EvidenceReader().read(directory)
    assert events == [] and state["status"] == "EXPORT_FAILED"


def test_new_contract_gate_rejects_unavailable_evidence_and_preserves_legacy():
    from conftest import assertion, link_case

    raw = link_case()
    raw["oracle"]["evaluation"]["checks"] = [assertion("tool_called")]
    case = EvalCase.model_validate(raw)
    payload = {
        "availability": {"support_status": "supported"},
        "event_types": [],
        "payload_schema": {
            "x-evidence-delivery": {
                "version": "1.0",
                "protocol_version": "1.0",
                "event_rules_version": "fixture-v1",
                "independent_interface": "agent_trace_sdk.EvidenceReader.read",
                "correlation": ["trace_id", "run_id", "turn_index"],
                "events": {
                    "tool_requested": {
                        "required_fields": ["call_id", "name", "arguments"],
                        "allowed_fields": ["call_id", "name", "arguments"],
                    }
                },
            }
        },
    }
    registry = SimpleNamespace(
        bundle=SimpleNamespace(
            documents=[
                SimpleNamespace(
                    snapshot_id="evidence.tool_trace",
                    snapshot_type="evidence",
                    payload=payload,
                )
            ]
        )
    )
    assert evidence_requirement_issues(case, registry)
    payload["event_types"] = ["tool_requested"]
    assert not evidence_requirement_issues(case, registry)
    delivery = payload["payload_schema"]["x-evidence-delivery"]
    delivery["events"]["tool_requested"]["required_fields"].remove("name")
    assert evidence_requirement_issues(case, registry)
    delivery["events"]["tool_requested"]["required_fields"].append("name")
    delivery["protocol_version"] = "unknown"
    assert evidence_requirement_issues(case, registry)
    delivery["protocol_version"] = "1.0"
    payload["availability"]["support_status"] = "unsupported"
    assert evidence_requirement_issues(case, registry)
    payload["payload_schema"] = {}
    assert not evidence_requirement_issues(case, registry)


def test_runner_keeps_observed_failure_after_agent_exception(tmp_path):
    from conftest import assertion, link_case
    from minimal_agent.runtime.trace import TraceCollector as AgentCollector

    from eval_framework.diagnostics import DiagnosticRegistry
    from eval_framework.provider import ProviderExceptionInfo
    from eval_framework.runner import _run_case

    class Provider:
        capabilities = None
        diagnostics = DiagnosticRegistry()

        def create_observed_runtime(self, execution, session_id, scope, sink):
            return sink

        def runtime_metadata(self, runtime):
            return {}

        def run_full(self, sink, execution, scope):
            trace = AgentCollector("run-1", sink=sink, context=sink.context)
            trace.record(
                "tool_requested",
                {
                    "call_id": "call-1",
                    "name": "forbidden",
                    "arguments": {},
                },
            )
            raise RuntimeError("interrupted after forbidden request")

        def classify_exception(self, exc):
            return ProviderExceptionInfo(
                execution_status="AGENT_EXCEPTION", exception={}
            )

        def cleanup(self, runtime):
            pass

        def tool_version(self, runtime):
            return "fixture-v1"

    raw = link_case()
    raw["oracle"]["forbidden_tools"] = ["forbidden"]
    raw["oracle"]["evaluation"]["checks"] = [
        assertion("tool_not_called"),
        assertion("status_match"),
    ]
    case, _ = _run_case(
        EvalCase.model_validate(raw),
        RunConfig(),
        Provider(),
        evaluator_run_id="eval",
        trial_id="trial",
        run_directory=tmp_path,
    )
    assert case.execution_status == "AGENT_EXCEPTION"
    assert case.evidence_status == "STILL_OPEN"
    assert case.quality_conclusion == "FAIL" and case.score is None
    assert [a.passed for a in case.assertion_results] == [False, None]
    assert case.assertion_results[0].evidence_refs == [
        f"event:{case.trace_events[0]['event_id']}"
    ]
    assert not any(
        i.code == "EVIDENCE_REF_UNRESOLVED" for i in case.trace_analysis.issues
    )


def test_full_agent_embedded_trace_cannot_rescue_failed_channel(tmp_path, monkeypatch):
    from conftest import assertion, link_case
    from minimal_agent.runtime import MinimalAgent, ToolRegistry

    from eval_framework.diagnostics import DiagnosticRegistry
    from eval_framework.runner import _run_case

    def execute(sink, execution, scope):
        monkeypatch.setattr(
            "agent_trace_sdk.native.write_eval_log",
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
        )
        agent = MinimalAgent(
            DeterministicModelClient(
                [intent(), {"type": "message", "content": "done"}]
            ),
            ToolRegistry(),
            evidence_sink=sink,
        )
        result = agent.run(execution.user_input)
        assert result.status == "SUCCESS"
        assert result.events[-1]["event_type"] == "run_finished"
        return AdapterOutput(None, [result.model_dump(mode="json")], None, [], None)

    provider = SimpleNamespace(
        capabilities=None,
        diagnostics=DiagnosticRegistry(),
        create_observed_runtime=lambda execution, session, scope, sink: sink,
        runtime_metadata=lambda runtime: {},
        run_full=execute,
        cleanup=lambda runtime: None,
        tool_version=lambda runtime: "fixture",
    )
    raw = link_case()
    raw["oracle"]["evaluation"]["checks"] = [
        assertion("status_match"),
        assertion("tool_not_called"),
    ]
    case, _ = _run_case(
        EvalCase.model_validate(raw),
        RunConfig(),
        provider,
        evaluator_run_id="eval",
        trial_id="trial",
        run_directory=tmp_path,
    )
    assert case.execution_status == "COMPLETED"
    assert case.turn_results[0]["events"]
    assert case.trace_events == [] and case.trace_analysis.timeline == []
    assert case.evidence_status == "EXPORT_FAILED"
    assert case.evaluation_validity == "INVALID"
    assert case.quality_conclusion == "INCONCLUSIVE" and case.score is None


def test_invalid_trial_cannot_pass_permissive_release_gate(case_result_factory):
    from test_comparison import loaded
    from test_gating import policy

    from eval_framework.gating import evaluate_gate

    case = case_result_factory().model_copy(update={"evaluation_validity": "INVALID"})
    result = evaluate_gate(loaded(case, sha="candidate"), policy())
    assert any(
        check.code == "EVALUATION_INVALID" and check.state == "FAIL"
        for check in result.checks
    )
