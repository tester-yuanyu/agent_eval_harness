"""Inspect owns actual execution, repetition, scoring and native logs."""

from pathlib import Path

from inspect_ai.log import read_eval_log
from test_execution_scoring import scripts

from eval_framework import RunConfig, load_dataset, run_evaluation


def test_inspect_dispatches_real_trials_and_records_domain_scores(
    dataset_path, tmp_path, monkeypatch
):
    import eval_framework.inspect_engine as engine

    aggregations = []
    original = engine.summarize

    def count_aggregation(*args):
        aggregations.append(True)
        return original(*args)

    monkeypatch.setattr(engine, "summarize", count_aggregation)
    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    executions = []

    def factory(execution):
        executions.append(execution)
        return scripts(execution)

    result = run_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test", trials_per_case=2),
        factory,
        output_dir=tmp_path,
    )
    assert result.evaluation_backend["name"] == "inspect_ai"
    assert len(executions) == len(result.cases) == 2
    assert len({row.trace_id for row in result.cases}) == 2
    assert aggregations == [True]
    assert all(r.execution_started_at and r.execution_finished_at for r in result.cases)
    log = read_eval_log(
        str(Path(result.run_directory) / result.native_artifacts["test_run"])
    )
    assert log.status == "success"
    assert log.eval.config.epochs == 2
    assert len(log.samples) == 2
    metrics = log.results.scores[0].metrics
    assert metrics["trial_pass_rate"].value == result.stability.trial_pass_rate
    assert metrics["framework_completion_rate"].value == 100
    for sample in log.samples:
        row = next(r for r in result.cases if r.trial_id == f"trial_{sample.epoch:03d}")
        score = sample.scores["agent_policy"]
        assert score.metadata["quality_conclusion"] == row.quality_conclusion
        assert score.metadata["evaluation_validity"] == row.evaluation_validity
        assert score.metadata["assertions"] == [
            a.model_dump(mode="json") for a in row.assertion_results
        ]
        assert sample.target == ""
        assert sample.metadata["trace_id"] == row.trace_id
        from inspect_ai.event import InfoEvent

        references = [
            event.data for event in sample.events
            if isinstance(event, InfoEvent)
            and event.source == "business_evidence_reference"
        ]
        assert len(references) == 1
        evidence = read_eval_log(Path(result.run_directory) / references[0]["path"])
        assert len(evidence.samples[0].events) == len(row.trace_events)
        assert not any(
            isinstance(event, InfoEvent) and event.source == "agent_trace_sdk"
            for event in sample.events
        )


def test_native_task_invokes_provider_only_inside_solver(
    dataset_path, tmp_path, monkeypatch
):
    import eval_framework.inspect_engine as engine

    entered, executions = [], []
    original = engine.inspect_eval

    def dispatch(task, **kwargs):
        assert executions == []
        assert all(sample.target == "" for sample in task.dataset)
        assert all("oracle" not in sample.metadata for sample in task.dataset)
        entered.append(True)
        return original(task, **kwargs)

    def factory(execution):
        assert entered
        assert not hasattr(execution, "oracle")
        executions.append(execution)
        return scripts(execution)

    monkeypatch.setattr(engine, "inspect_eval", dispatch)
    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[
        :1
    ]  # Remaining legacy fixtures require unavailable tools.
    result = run_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test", trials_per_case=2),
        factory,
        output_dir=tmp_path,
    )
    assert len(executions) == len(result.cases)


def test_inspect_artifact_survives_report_copy(dataset_path, tmp_path):
    from eval_framework.reporting import write_report
    from eval_framework.result_loader import load_run_result

    result = run_evaluation(
        load_dataset(dataset_path),
        RunConfig(run_mode="framework_self_test"),
        scripts,
        output_dir=tmp_path / "execution",
    )
    paths = write_report(result, tmp_path / "report")
    loaded = load_run_result(paths.results).result
    artifact = Path(loaded.run_directory) / loaded.native_artifacts["test_run"]
    assert read_eval_log(str(artifact)).status == "success"
    assert (
        artifact.read_bytes()
        == (
            Path(result.run_directory) / result.native_artifacts["test_run"]
        ).read_bytes()
    )
    assert loaded.native_artifacts["test_run"] in Path(paths.report).read_text()


def test_inspect_native_api_remains_usable_after_business_evaluation(
    dataset_path, tmp_path
):
    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import exact
    from inspect_ai.solver import generate

    run_evaluation(
        load_dataset(dataset_path),
        RunConfig(run_mode="framework_self_test"),
        scripts,
        output_dir=tmp_path / "business",
    )
    logs = eval(
        Task(
            dataset=[Sample(input="hello", target="hello")],
            solver=generate(),
            scorer=exact(),
        ),
        model="mockllm/model",
        log_dir=str(tmp_path / "native"),
        display="none",
        ctl_server=False,
    )
    assert logs[0].status == "success"
    assert len(logs[0].samples) == 1
    assert logs[0].samples[0].scores
