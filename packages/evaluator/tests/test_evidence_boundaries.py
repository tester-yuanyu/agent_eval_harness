"""Failure boundaries for the independent channel and portable artifacts."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_trace_sdk import EventRule, TraceCollector
from conftest import assertion, link_case

from eval_framework.assertions import run_assertions
from eval_framework.diagnostics import DiagnosticRegistry
from eval_framework.provider import AdapterOutput, ProviderExceptionInfo
from eval_framework.runner import _run_case
from eval_framework.schemas import EvalCase, RunConfig


def case_spec():
    raw = link_case()
    raw["oracle"]["evaluation"]["checks"] = [assertion("tool_not_called")]
    raw["oracle"]["forbidden_tools"] = ["forbidden"]
    return EvalCase.model_validate(raw)


def observed_provider():
    def execute(sink, execution, scope):
        collector = TraceCollector(
            "run",
            sink=sink,
            context=sink.context,
            rules={
                "tool_requested": EventRule(
                    "planning_execution", ("call_id", "name", "arguments")
                )
            },
        )
        collector.record(
            "tool_requested",
            {
                "call_id": "call",
                "name": "forbidden",
                "arguments": {},
            },
        )
        return AdapterOutput(None, [], None, [], None)

    return SimpleNamespace(
        capabilities=None,
        diagnostics=DiagnosticRegistry(),
        create_observed_runtime=lambda execution, session, scope, sink: sink,
        runtime_metadata=lambda runtime: {},
        run_full=execute,
        classify_exception=lambda exc: ProviderExceptionInfo(
            execution_status="AGENT_EXCEPTION",
            exception={"type": type(exc).__name__, "message": str(exc)},
        ),
        cleanup=lambda runtime: None,
        tool_version=lambda runtime: "fixture",
    )


def execute(tmp_path, provider):
    return _run_case(
        case_spec(),
        RunConfig(),
        provider,
        evaluator_run_id="eval",
        trial_id="trial",
        run_directory=tmp_path,
    )[0]


@pytest.mark.parametrize("agent_crashes", [False, True])
def test_cleanup_failure_preserves_execution_and_observed_violation(
    tmp_path, agent_crashes
):
    provider = observed_provider()
    original = provider.run_full

    def run(*args):
        result = original(*args)
        if agent_crashes:
            raise RuntimeError("agent crashed")
        return result

    def cleanup(runtime):
        raise RuntimeError("cleanup crashed")

    provider.run_full, provider.cleanup = run, cleanup
    result = execute(tmp_path, provider)
    assert result.execution_status == (
        "AGENT_EXCEPTION" if agent_crashes else "COMPLETED"
    )
    assert result.cleanup_status == "CLEANUP_FAILED"
    assert result.evaluation_validity == "INVALID" and result.score is None
    assert result.quality_conclusion == "FAIL"
    assert any(i["code"] == "CLEANUP_FAILED" for i in result.evaluation_issues)
    assert (result.exception or {}).get("message") != "cleanup crashed"


@pytest.mark.parametrize("boundary", ["read", "finish", "validation"])
def test_evidence_failure_is_contained_and_cleanup_runs(
    tmp_path, monkeypatch, boundary
):
    from agent_trace_sdk import EvidenceReader, LocalEvidenceSink

    provider = observed_provider()
    cleaned = []
    provider.cleanup = lambda runtime: cleaned.append(True)

    def broken(*args, **kwargs):
        raise OSError("evidence failure")

    if boundary == "read":
        monkeypatch.setattr(EvidenceReader, "read", broken)
    elif boundary == "finish":
        original = LocalEvidenceSink.finish

        def finish(self, **kwargs):
            original(self, **kwargs)
            broken()

        monkeypatch.setattr(LocalEvidenceSink, "finish", finish)
    else:
        provider.evidence_issues = broken
    result = execute(tmp_path, provider)
    assert cleaned == [True]
    assert result.execution_status == "COMPLETED"
    assert result.evaluation_validity == "INVALID" and result.score is None
    assert result.evidence_status == "EXPORT_FAILED"
    if boundary == "read":
        assert result.trace_events == []
        assert result.assertion_results[0].passed is None
    else:
        assert result.assertion_results[0].passed is False


def test_tampered_association_cannot_prove_a_violation(tmp_path):
    provider = observed_provider()
    original = provider.run_full

    def run(sink, *args):
        output = original(sink, *args)
        (sink.directory / "association.json").write_text("{}")
        return output

    provider.run_full = run
    result = execute(tmp_path, provider)
    assert result.evaluation_validity == "INVALID"
    assert result.trace_events == []
    assert result.quality_conclusion == "INCONCLUSIVE"
    assert list(tmp_path.glob("evidence/*/trace.inspect.json"))[0].read_text()


def test_unrelated_content_loss_does_not_hide_complete_tool_coverage():
    event = {
        "event_id": "e",
        "event_type": "final_response_generated",
        "sequence": 1,
        "validation_status": "INVALID",
        "payload": {},
    }
    output = AdapterOutput(
        None,
        [],
        None,
        [],
        None,
        [event],
        "PARTIAL",
        True,
        {
            "execution_completed": True,
            "collection_closed": True,
            "issues": [{"code": "INVALID_OR_TRUNCATED_EVENT", "sequence": 1}],
        },
    )
    assert run_assertions(case_spec(), output, None)[0].passed is True
    event["event_type"] = "tool_requested"
    assert run_assertions(case_spec(), output, None)[0].passed is None
    assert (
        run_assertions(case_spec(), replace(output, evidence_manifest=None), None)[
            0
        ].passed
        is None
    )


def test_unknown_check_is_applicable_and_inconclusive():
    case = case_spec()
    case.oracle.evaluation.checks[0].name = "unknown"
    result = run_assertions(case, AdapterOutput(None, [], None, [], None), None)[0]
    assert result.applicable and result.passed is None


def test_initialization_failure_retains_events_and_runs_supported_checks(tmp_path):
    provider = observed_provider()

    def initialize(execution, session, scope, sink):
        provider.run_full(sink, execution, scope)
        raise RuntimeError("initialization interrupted")

    provider.create_observed_runtime = initialize
    result = execute(tmp_path, provider)
    assert result.execution_status == "INITIALIZATION_ERROR"
    assert result.trace_events
    assert result.evidence_status == "STILL_OPEN"
    assert result.quality_conclusion == "FAIL"
    assert result.evaluation_validity == "INVALID"


def test_later_trial_runs_after_reader_failure(dataset_path, tmp_path, monkeypatch):
    from agent_trace_sdk import EvidenceReader
    from conftest import intent
    from support.model_client import DeterministicModelClient

    from eval_framework import load_dataset, run_evaluation

    original = EvidenceReader.read
    reads = []

    def read(self, *args, **kwargs):
        reads.append(True)
        if len(reads) == 1:
            raise OSError("reader interrupted")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(EvidenceReader, "read", read)
    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    result = run_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test", trials_per_case=2),
        lambda execution: DeterministicModelClient([intent()]),
        output_dir=tmp_path,
    )
    assert [c.execution_status for c in result.cases] == ["COMPLETED", "COMPLETED"]
    assert [c.evaluation_validity for c in result.cases] == ["INVALID", "VALID"]
    assert result.cases[1].evidence_status == "COMPLETE"


def test_incomplete_calls_do_not_change_first_call_semantics():
    case = case_spec()
    case.oracle.evaluation.checks[0].name = "tool_args_match"
    case.oracle.evaluation.checks[0].config = {"tool": "forbidden", "expected": {}}
    output = AdapterOutput(
        None,
        [],
        None,
        [],
        None,
        [
            {
                "event_id": "later",
                "event_type": "tool_requested",
                "sequence": 2,
                "validation_status": "VALID",
                "payload": {"call_id": "later", "name": "forbidden", "arguments": {}},
            }
        ],
        "PARTIAL",
    )
    assert run_assertions(case, output, None)[0].passed is None


def test_invalid_events_are_visible_but_not_sent_to_business_trace_rules(
    case_result_factory,
):
    from eval_framework.trace_analysis import analyze_case_trace

    case = case_result_factory().model_copy(
        update={
            "trace_id": "trace",
            "trace_events": [
                {
                    "event_id": "bad",
                    "sequence": 1,
                    "turn_index": -1,
                    "event_type": "tool_requested",
                    "validation_status": "INVALID",
                    "payload": None,
                }
            ],
        }
    )
    received = []
    rule = SimpleNamespace(
        analyze=lambda timeline, case: received.extend(timeline) or []
    )
    analysis = analyze_case_trace(case, [rule])
    assert len(analysis.timeline) == 1
    assert received == []


def test_copied_report_preserves_raw_evidence_and_can_be_reloaded(
    dataset_path,
    tmp_path,
):
    from conftest import intent
    from support.model_client import DeterministicModelClient

    from eval_framework import load_dataset, run_evaluation
    from eval_framework.reporting import write_report
    from eval_framework.result_loader import load_run_result

    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    result = run_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test"),
        lambda execution: DeterministicModelClient([intent()]),
        output_dir=tmp_path / "original",
    )
    paths = write_report(result, tmp_path / "copy")
    trace_id = result.cases[0].trace_id
    relative = Path("evidence") / trace_id
    for filename in ("trace.inspect.json", "association.json"):
        copied = Path(paths.output_dir) / relative / filename
        assert (
            copied.read_bytes()
            == (Path(result.run_directory) / relative / filename).read_bytes()
        )
        assert str(copied) in paths.evidence_files
    assert not list((Path(paths.output_dir) / "evidence").glob("*/*/trace.jsonl"))
    raw = json.loads(Path(paths.results).read_text())
    assert raw["run_directory"] == paths.output_dir
    # The stored absolute path can go stale after moving an archive.
    raw["run_directory"] = "/missing/original"
    Path(paths.results).write_text(json.dumps(raw))
    loaded = load_run_result(paths.results)
    assert loaded.result.run_directory == paths.output_dir
    assert str(relative / "trace.inspect.json") in Path(paths.report).read_text()


def test_invalid_trial_makes_run_verdict_and_comparison_invalid(case_result_factory):
    from test_comparison import loaded

    from eval_framework.comparison import check_comparability
    from eval_framework.reporting import _run_verdict

    baseline = loaded(case_result_factory(), sha="before")
    candidate = loaded(
        case_result_factory().model_copy(
            update={
                "evaluation_validity": "INVALID",
                "quality_conclusion": "FAIL",
            }
        ),
        sha="after",
    )
    assert _run_verdict(candidate.result) == "INVALID_RUN"
    assert check_comparability(baseline, candidate).status == "INVALID_COMPARISON"


def test_run_directory_and_trace_id_do_not_change_business_comparison(
    case_result_factory,
):
    from test_comparison import loaded

    from eval_framework.comparison import check_comparability
    from eval_framework.stability import observed_output_sha256

    before = loaded(case_result_factory(), sha="before")
    after = loaded(
        case_result_factory().model_copy(update={"trace_id": "different"}), sha="after"
    )
    after.result.run_directory = "/another/machine"
    assert check_comparability(before, after).status == "COMPARABLE"
    assert observed_output_sha256(before.result.cases[0]) == observed_output_sha256(
        after.result.cases[0]
    )
