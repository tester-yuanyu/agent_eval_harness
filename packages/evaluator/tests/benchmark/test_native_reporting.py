"""Native viewer delivery must preserve evidence and the historical API."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import socket

import pytest
from inspect_ai import Task
from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.scorer import Score, scorer
from inspect_ai.solver import generate

from eval_framework.benchmark.report import write_report
from eval_framework.benchmark.runner import digest

from .test_report import saved_run


@pytest.fixture
def native_run(tmp_path, monkeypatch):
    # A real Inspect log and renderer, with only the model replaced by its
    # official mock provider. No HTTP client or hosted exporter is needed.
    monkeypatch.setenv("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    return make_native_run(tmp_path)


def make_native_run(tmp_path, reply="hi", count=1):
    tmp_path.mkdir(parents=True, exist_ok=True)
    run = saved_run()
    run["run_id"] = "run-" + tmp_path.name
    run["identity"]["scoring_version"] = "native-report-test-v1"
    run["identity"]["harness_version"] = "file-harness-inspect-v3"
    run["identity_hash"] = digest(run["identity"])
    run["planned_case_ids"] = ["case-one"]
    run.pop("summary")
    run["trials"][0]["assessment"]["verdict"] = "PASS" if reply == "hi" else "FAIL"
    run["trials"][0]["identity_hash"] = run["identity_hash"]
    if count == 2:
        run["planned_case_ids"].append("case-two")
        row = copy.deepcopy(run["trials"][0])
        row["case_id"] = "case-two"
        run["trials"].append(row)
    (tmp_path / "results.json").write_text(json.dumps(run), encoding="utf-8")

    @scorer(metrics=[])
    def saved_score():
        async def score(state, target):
            row = next(
                row for row in run["trials"] if row["case_id"] == state.sample_id
            )
            return Score(
                value=row["assessment"]["verdict"], metadata={"benchmark_record": row}
            )
        return score

    logs = inspect_eval(
        Task(
            name="native-report-fixture",
            dataset=[
                Sample(id=case_id, input="Say hi", target="hi")
                for case_id in run["planned_case_ids"]
            ],
            solver=generate(),
            scorer=saved_score(),
            metadata={"identity_hash": run["identity_hash"]},
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[ModelOutput.from_content("mockllm/model", reply)] * count,
        ),
        log_dir=str(tmp_path / "inspect"),
        display="none",
        notification=False,
        ctl_server=False,
        log_realtime=False,
    )
    assert logs[0].status == "success"
    return tmp_path


def test_auto_report_uses_native_viewer_and_preserves_source(native_run, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("report generation must not access the network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    sources = [
        native_run / "results.json", *native_run.joinpath("inspect").glob("*.eval")
    ]
    before = {path: path.read_bytes() for path in sources}
    path = write_report(native_run)
    assert path == native_run / "inspect-view" / "index.html"
    assert path.is_file()
    assert list(path.parent.joinpath("logs").rglob("*.eval"))
    manifest = json.loads((path.parent / "benchmark-source.json").read_text())
    assert manifest["viewer_backend"] == "inspect_ai"
    assert manifest["results_sha256"] == hashlib.sha256(before[sources[0]]).hexdigest()
    assert manifest["domain_summary"]["planned_trials"] == 1
    assert manifest["domain_summary"]["verdicts"] == {"PASS": 1}
    assert {source: source.read_bytes() for source in sources} == before
    # Regeneration uses the same saved evidence and does not append new runs.
    assert write_report(native_run) == path
    assert len(list(native_run.joinpath("inspect").glob("*.eval"))) == 1


def test_explicit_domain_report_remains_available(native_run):
    path = write_report(native_run, format="domain")
    assert path == native_run / "report.html"
    assert "逐条结果" in path.read_text()


def test_explicit_inspect_report_does_not_fabricate_logs(tmp_path):
    (tmp_path / "results.json").write_text(json.dumps(saved_run()))
    with pytest.raises(ValueError, match="Inspect"):
        write_report(tmp_path, format="inspect")
    assert not (tmp_path / "inspect-view").exists()


def test_native_report_rejects_inconsistent_saved_summary(native_run):
    path = native_run / "results.json"
    run = json.loads(path.read_text())
    run["summary"] = {"verdicts": {"PASS": 99}}
    path.write_text(json.dumps(run))
    with pytest.raises(ValueError, match="disagrees"):
        write_report(native_run)
    assert not (native_run / "inspect-view").exists()


def test_report_cli_selects_native_or_legacy_format(native_run, capsys):
    from eval_framework.benchmark.cli import main

    assert main(["report", "--run", str(native_run), "--format", "inspect"]) == 0
    assert str(native_run / "inspect-view" / "index.html") in capsys.readouterr().out
    assert main(["report", "--run", str(native_run), "--format", "domain"]) == 0
    assert str(native_run / "report.html") in capsys.readouterr().out


def test_comparison_bundles_both_native_logs_without_rescoring(tmp_path):
    from eval_framework.benchmark.native_reporting import write_comparison_report

    baseline = make_native_run(tmp_path / "baseline")
    candidate = make_native_run(tmp_path / "candidate", reply="bye")
    inputs = [
        *baseline.joinpath("inspect").glob("*.eval"),
        *candidate.joinpath("inspect").glob("*.eval"),
    ]
    before = {path: path.read_bytes() for path in inputs}
    output = tmp_path / "comparison"
    path = write_comparison_report(baseline, candidate, output)
    assert path == output / "index.html"
    assert path.is_file()
    assert len(list(output.joinpath("logs").rglob("*.eval"))) == 2
    comparison = json.loads((output / "comparison.json").read_text())
    assert comparison["pass_rate_delta"] == -1
    assert comparison["changed_trials"] == [
        {"case_id": "case-one", "trial": 1, "baseline": "PASS", "candidate": "FAIL"}
    ]
    assert {path: path.read_bytes() for path in inputs} == before
    candidate_results = candidate / "results.json"
    changed = json.loads(candidate_results.read_text())
    changed["identity"]["scoring_version"] = "different"
    changed["identity_hash"] = digest(changed["identity"])
    changed["trials"][0]["identity_hash"] = changed["identity_hash"]
    candidate_results.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="scoring_version"):
        write_comparison_report(baseline, candidate, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()


def test_compare_cli_saves_native_view_link(tmp_path):
    from eval_framework.benchmark.cli import main

    baseline = make_native_run(tmp_path / "baseline")
    candidate = make_native_run(tmp_path / "candidate", reply="bye")
    output = tmp_path / "comparison.json"
    view = tmp_path / "view"
    assert main([
        "compare", "--baseline", str(baseline), "--candidate", str(candidate),
        "--output", str(output), "--view-dir", str(view),
    ]) == 0
    result = json.loads(output.read_text())
    assert result["inspect_view"] == str(view / "index.html")
    assert result["pass_rate_delta"] == -1
    assert (view / "index.html").is_file()


def test_native_report_rejects_foreign_run_identity(tmp_path):
    from inspect_ai.log import read_eval_log, write_eval_log

    source = make_native_run(tmp_path / "source")
    foreign = make_native_run(tmp_path / "foreign")
    original_log = next(foreign.joinpath("inspect").glob("*.eval"))
    log = read_eval_log(str(original_log))
    log.eval.metadata["identity_hash"] = "another-configuration"
    write_eval_log(log, str(original_log))
    shutil.copyfile(original_log, source / "inspect" / original_log.name)
    with pytest.raises(ValueError, match="identity"):
        write_report(source)
    assert not (source / "inspect-view").exists()


def test_native_report_rejects_changed_saved_assessment(native_run):
    path = native_run / "results.json"
    run = json.loads(path.read_text())
    run["trials"][0]["assessment"]["verdict"] = "FAIL"
    path.write_text(json.dumps(run))
    with pytest.raises(ValueError, match="evidence|record|coverage"):
        write_report(native_run)
    assert not (native_run / "inspect-view").exists()


def test_comparison_checks_native_identity_before_output(tmp_path):
    from inspect_ai.log import read_eval_log, write_eval_log

    from eval_framework.benchmark.native_reporting import write_comparison_report

    baseline = make_native_run(tmp_path / "baseline")
    candidate = make_native_run(tmp_path / "candidate")
    path = next(candidate.joinpath("inspect").glob("*.eval"))
    log = read_eval_log(str(path))
    log.eval.metadata["identity_hash"] = "foreign"
    write_eval_log(log, str(path))
    with pytest.raises(ValueError, match="identity"):
        write_comparison_report(baseline, candidate, tmp_path / "comparison")
    assert not (tmp_path / "comparison").exists()


def test_native_view_excludes_superseded_attempt_but_preserves_hash(tmp_path):
    source = make_native_run(tmp_path / "source")
    earlier = make_native_run(tmp_path / "earlier", reply="bye")
    path = next(earlier.joinpath("inspect").glob("*.eval"))
    copied = source / "inspect" / path.name
    shutil.copyfile(path, copied)
    report = write_report(source)
    manifest = json.loads((report.parent / "benchmark-source.json").read_text())
    assert len(manifest["logs"]) == len(manifest["superseded_logs"]) == 1
    assert manifest["superseded_logs"][0]["sha256"] == hashlib.sha256(
        copied.read_bytes()
    ).hexdigest()
    assert len(list(report.parent.joinpath("logs").rglob("*.eval"))) == 1


def test_native_view_prefers_complete_log_over_newer_partial_attempt(tmp_path):
    from inspect_ai.log import read_eval_log, write_eval_log

    source = make_native_run(tmp_path, count=2)
    path = next(source.joinpath("inspect").glob("*.eval"))
    log = read_eval_log(str(path))
    log.samples = log.samples[:1]
    partial = path.with_name("2099-" + path.name[5:])
    write_eval_log(log, str(partial))
    report = write_report(source)
    manifest = json.loads((report.parent / "benchmark-source.json").read_text())
    assert len(manifest["logs"]) == len(manifest["superseded_logs"]) == 1
    assert manifest["domain_summary"]["planned_trials"] == 2


@pytest.mark.parametrize("damage", ["sample", "score"])
def test_native_view_rejects_sample_or_score_mismatched_to_record(native_run, damage):
    from inspect_ai.log import read_eval_log, write_eval_log

    path = next(native_run.joinpath("inspect").glob("*.eval"))
    log = read_eval_log(str(path))
    if damage == "sample":
        log.samples[0].id = "wrong-case"
    else:
        next(iter(log.samples[0].scores.values())).value = "FAIL"
    write_eval_log(log, str(path))
    with pytest.raises(ValueError, match="sample or score"):
        write_report(native_run)
