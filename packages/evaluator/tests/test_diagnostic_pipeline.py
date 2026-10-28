"""Inspect owns diagnostic execution and the persisted aggregate."""

import json
import runpy
from pathlib import Path

import httpx
from inspect_ai.log import read_eval_log
from test_comparison import loaded
from test_execution_scoring import scripts
from test_gating import policy
from test_langfuse_export import sdk

from eval_framework import RunConfig, load_dataset, run_evaluation
from eval_framework.comparison import check_comparability
from eval_framework.diagnostic_metrics import (
    METRIC_ID,
    ConversationMetricConfig,
    DiagnosticMetricResult,
)
from eval_framework.gating import evaluate_gate
from eval_framework.inspect_metrics import summarize
from eval_framework.reporting import write_report
from eval_framework.result_loader import load_run_result


def test_diagnostic_aggregates_keep_missing_denominator(
    case_result_factory, dataset_path
):
    cases = [
        case_result_factory(
            trial_id=f"trial_{i}",
            diagnostic_metrics={
                METRIC_ID: value,
            },
        )
        for i, value in enumerate(
            [
                DiagnosticMetricResult(status="SUCCESS", score=0),
                DiagnosticMetricResult(status="SUCCESS", score=1),
                DiagnosticMetricResult(status="ERROR"),
                DiagnosticMetricResult(status="NOT_APPLICABLE"),
            ]
        )
    ]
    summary = summarize(cases, load_dataset(dataset_path), "agent_benchmark")
    metric = summary.diagnostic_metrics[METRIC_ID]
    assert metric.status_counts == {"SUCCESS": 2, "ERROR": 1, "NOT_APPLICABLE": 1}
    assert metric.scored_trials == 2
    assert metric.mean_score == 0.5
    run = loaded(cases[0], cases=cases, summary=summary)
    assert evaluate_gate(run, policy()).conclusion == "PASS"
    run.result.diagnostic_metadata = {METRIC_ID: {"library_version": "other"}}
    old = loaded(cases[0], cases=cases, summary=summary)
    assert "DIAGNOSTIC_FINGERPRINT_MISMATCH" in {
        i.code for i in check_comparability(old, run).issues
    }


def test_inspect_persists_diagnostic_once_and_reports_snapshot(
    dataset_path, tmp_path, monkeypatch
):
    import eval_framework.inspect_engine as engine
    from eval_framework.judges.conversation import ConversationMetricClient

    calls = []

    async def evaluate(trial, result, client):
        calls.append(trial.key)
        return DiagnosticMetricResult(status="SUCCESS", score=0)

    monkeypatch.setattr(engine, "evaluate_conversation", evaluate)
    monkeypatch.setattr(
        ConversationMetricClient,
        "from_env",
        lambda config: type("Client", (), {"metadata": lambda self: {"test": True}})(),
    )
    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    result = run_evaluation(
        dataset,
        RunConfig(
            run_mode="framework_self_test",
            trials_per_case=2,
            conversation_completeness=ConversationMetricConfig(),
        ),
        scripts,
        output_dir=tmp_path / "execution",
    )
    assert len(calls) == 2 and len(set(calls)) == 2
    assert all(c.quality_conclusion == "PASS" for c in result.cases)
    metric = result.summary.diagnostic_metrics[METRIC_ID]
    assert metric.mean_score == 0
    log = read_eval_log(
        Path(result.run_directory) / result.native_artifacts["test_run"]
    )
    assert (
        log.results.scores[0].metrics[f"diagnostic.{METRIC_ID}.mean_score"].value == 0
    )
    assert (
        log.samples[0]
        .scores["agent_policy"]
        .metadata["diagnostic_metrics"][METRIC_ID]["score"]
        == 0
    )

    async def forbidden(*args):
        raise AssertionError("Report executed a metric")

    monkeypatch.setattr(engine, "evaluate_conversation", forbidden)
    paths = write_report(result, tmp_path / "report")
    saved = load_run_result(paths.results).result
    assert saved.summary.diagnostic_metrics[METRIC_ID] == metric
    assert "Conversation Completeness" in Path(paths.report).read_text()
    assert (
        json.loads(Path(paths.summary_json).read_text())["diagnostic_metrics"][
            METRIC_ID
        ]["mean_score"]
        == 0
    )


def test_export_consumes_snapshot_and_omits_unknown_score(
    case_result_factory, tmp_path
):
    from eval_framework.diagnostic_metrics import DiagnosticMetricSummary
    from eval_framework.observability import export_run

    case = case_result_factory(
        diagnostic_metrics={
            METRIC_ID: DiagnosticMetricResult(
                status="ERROR", reason="PRIVATE MODEL TEXT"
            )
        }
    )
    run = loaded(case).result
    run.summary.diagnostic_metrics = {
        METRIC_ID: DiagnosticMetricSummary(
            status_counts={"ERROR": 1}, scored_trials=0, mean_score=None
        )
    }
    path = tmp_path / "results.json"
    path.write_text(run.model_dump_json())
    before = path.read_bytes()
    scores = []

    def handler(request):
        if "scores" in request.url.path:
            scores.extend(json.loads(request.content))
            return httpx.Response(202, json={"message": "Accepted"})
        return httpx.Response(200, json={})

    export_run(tmp_path, client=sdk(handler))
    names = {s["name"]: s["value"] for s in scores}
    assert names[f"diagnostic.{METRIC_ID}.status"] == "ERROR"
    assert names[f"diagnostic.{METRIC_ID}.ERROR"] == 1
    assert f"diagnostic.{METRIC_ID}.score" not in names
    assert f"diagnostic.{METRIC_ID}.mean_score" not in names
    assert "PRIVATE" not in json.dumps(scores)
    assert path.read_bytes() == before


def test_cli_and_suite_preserve_explicit_config(dataset_path):
    from eval_framework.cli import _compile_cli_suite, _parser
    from eval_framework.contracts.models import SuiteDefinition

    args = _parser().parse_args(
        [
            "run",
            "--dataset",
            str(dataset_path),
            "--output-dir",
            "unused",
            "--conversation-completeness",
        ]
    )
    loaded_suite, _, compiled = _compile_cli_suite(args)
    assert compiled.run_config.conversation_completeness == ConversationMetricConfig()
    restored = SuiteDefinition.model_validate(loaded_suite.definition.model_dump())
    assert restored.run_config.conversation_completeness == ConversationMetricConfig()


def test_real_multiturn_solver_and_public_metric_share_one_inspect_run(
    tmp_path, monkeypatch
):
    from test_conversation_metric import mock_client

    from eval_framework import (
        ContractStore,
        compile_suite,
        execute_compiled_suite,
        load_suite_definition,
    )
    from eval_framework.composition import default_plugin_catalog
    from eval_framework.judges.conversation import ConversationMetricClient

    example = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "examples/stateful_gift.py")
    )
    suite_path = example["build_suite"](tmp_path)
    payload = json.loads(suite_path.read_text())
    payload["run_config"]["conversation_completeness"] = {}
    payload["run_config"]["trials_per_case"] = 1
    suite_path.write_text(json.dumps(payload))
    client, _ = mock_client()
    monkeypatch.setattr(ConversationMetricClient, "from_env", lambda config: client)
    catalog = default_plugin_catalog()
    compiled = compile_suite(
        load_suite_definition(suite_path), catalog, ContractStore(tmp_path)
    )
    result = execute_compiled_suite(
        compiled,
        catalog,
        model_client_factory=example["DemoModelClient"],
        output_dir=tmp_path / "run",
    )
    assert len(result.cases) == 4
    assert result.summary.diagnostic_metrics[METRIC_ID].status_counts == {
        "SUCCESS": 1,
        "ERROR": 2,
        "NOT_APPLICABLE": 1,
    }
    assert result.summary.quality_counts == {"FAIL": 2, "PASS": 2}
    assert result.summary.diagnostic_metrics[METRIC_ID].mean_score == 1
    for row in result.cases:
        diagnostic = row.diagnostic_metrics[METRIC_ID]
        if diagnostic.status == "SUCCESS":
            assert diagnostic.input_turn_count == 2 * len(row.turn_results)
