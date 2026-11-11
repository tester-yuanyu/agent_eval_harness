import json

import pytest
from eval_framework.benchmark.runner import digest, save_json


def test_report_view_preserves_source_and_adds_calibration(tmp_path, monkeypatch):
    from eval_framework.benchmark.report_view import create_report_view

    original = {"trials": [], "judge_summary": {}, "run_id": "original"}
    save_json(tmp_path / "source/results.json", original)
    raw = (tmp_path / "source/results.json").read_bytes()

    def report(directory, **kwargs):
        path = directory / "report.html"
        path.write_text("report")
        return path

    monkeypatch.setattr("eval_framework.benchmark.report.write_report", report)
    assert create_report_view(tmp_path / "source", tmp_path / "view").exists()
    assert (tmp_path / "source/results.json").read_bytes() == raw
    assert (tmp_path / "view/results.json").read_bytes() == raw
    labels = json.loads(
        (tmp_path / "view/human-calibration-worksheet.json").read_text()
    )
    assert labels["status"] == "awaiting_independent_human_labels"
    assert (
        json.loads((tmp_path / "view/phase-timings.json").read_text())["events"][0][
            "phase"
        ]
        == "report"
    )
    with pytest.raises(ValueError, match="new empty"):
        create_report_view(tmp_path / "source", tmp_path / "view")


def test_judge_recovery_checks_execution_config_and_partial_journals(tmp_path):
    from eval_framework.benchmark.judge_recovery import load_judge_seeds

    row = {"case_id": "a", "trial": 1, "assessment": {"verdict": "FAIL"}}
    source = {"trials": [row]}
    identity = {
        "source_results_sha256": "sourcehash",
        "judge_config": {"model": "stub"},
        "judge_repeats": 2,
    }
    meta = {"identity": identity, "identity_hash": digest(identity)}
    save_json(tmp_path / "judge-run.json", meta)
    record = {"metric_id": "m", "score": 0.5, "status": "SCORED"}
    save_json(
        tmp_path / "judgments/1.json",
        {
            "identity_hash": digest(identity),
            "source_trial_sha256": digest(row),
            "judge_repeat": 2,
            "metrics": [record],
        },
    )
    seeds, _ = load_judge_seeds(tmp_path, source, "sourcehash", {"model": "stub"}, 2)
    assert seeds == {("a", 1, 2): [record]}
    with pytest.raises(ValueError, match="identical"):
        load_judge_seeds(tmp_path, source, "otherhash", {"model": "stub"}, 2)


def test_agent_canary_stops_remaining_cases_on_configuration_error(tmp_path):
    from eval_framework.benchmark.runner import run_benchmark
    from eval_framework.benchmark.tasks import load_tasks
    from eval_framework.provider_registry import ProviderRegistry
    from tests.benchmark.test_agent_adapters import ROOT, AdapterFactory, OfflineAdapter

    class CanaryAdapter(OfflineAdapter):
        fail = True

        def needs_model(self, mode):
            return True

        def inspect_model(self):
            return "mockllm/model"

        def sandbox_spec(self, output, *, needs_model):
            return "local"

        async def execute(self, task, *, mode, config):
            result = await super().execute(task, mode=mode, config=config)
            result["errors"] = [{"code": "MissingSessionID"}] if self.fail else []
            return result

    adapter = CanaryAdapter()
    registry = ProviderRegistry()
    registry.register(adapter.provider_id, AdapterFactory(adapter))
    tasks = load_tasks(ROOT / "data/benchmarks/file-tools-v2")[:3]
    with pytest.raises(RuntimeError, match="preflight configuration"):
        run_benchmark(
            tasks,
            dataset={"id": "canary-test"},
            config={"provider": adapter.provider_id, "preflight": True},
            output=tmp_path,
            provider_registry=registry,
        )
    assert len(adapter.received) == 1
    assert len(list((tmp_path / "trials").glob("*.json"))) == 1
    assert not (tmp_path / "results.json").exists()

    adapter.fail = False
    resumed = run_benchmark(
        tasks,
        dataset={"id": "canary-test"},
        config={"provider": adapter.provider_id, "preflight": True},
        output=tmp_path,
        provider_registry=registry,
    )
    assert len(adapter.received) == 3
    assert len(resumed["trials"]) == 3
    assert (
        resumed["trials"][0]["observation"]["errors"][0]["code"] == "MissingSessionID"
    )
