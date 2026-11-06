import json

import pytest

from .test_regrade import DATASET, saved_run  # noqa: F401


def test_report_is_stable_private_and_does_not_overwrite_evidence(saved_run, tmp_path):  # noqa: F811
    from eval_contracts.benchmark_analysis import AnalysisPolicy

    from eval_framework.benchmark.analysis_report import write_analysis

    source, run = saved_run
    run["trials"][0]["observation"]["private_prompt"] = "PRIVATE_SENTINEL"
    (source / "results.json").write_text(json.dumps(run))
    before = (source / "results.json").read_bytes()
    a = write_analysis(
        source, dataset_path=DATASET, output=tmp_path / "a", policy=AnalysisPolicy()
    )
    b = write_analysis(
        source, dataset_path=DATASET, output=tmp_path / "b", policy=AnalysisPolicy()
    )
    assert a["json"].read_bytes() == b["json"].read_bytes()
    result = json.loads(a["json"].read_text())
    assert result["layers"]["e2e"]["planned_trials"] == 1
    assert result["failures"]["by_domain"]["unknown"] == 1
    assert "PRIVATE_SENTINEL" not in "".join(p.read_text() for p in a.values())
    assert (source / "results.json").read_bytes() == before
    with pytest.raises(ValueError):
        write_analysis(
            source, dataset_path=DATASET, output=source, policy=AnalysisPolicy()
        )
    with pytest.raises(ValueError):
        write_analysis(
            source, dataset_path=DATASET, output=tmp_path / "a", policy=AnalysisPolicy()
        )


def test_analysis_cli_offline_and_html_escapes_saved_ids(saved_run, tmp_path, capsys):  # noqa: F811
    from eval_framework.benchmark.analysis_report import render_html
    from eval_framework.benchmark.cli import main

    source, _ = saved_run
    main(
        [
            "analyze",
            "--run",
            str(source),
            "--dataset",
            str(DATASET),
            "--output",
            str(tmp_path / "report"),
        ]
    )
    assert (tmp_path / "report/analysis.json").is_file()
    assert "PRIVATE_SENTINEL" not in capsys.readouterr().out
    html = render_html(
        {"layers": {}, "trials": [{"case_id": "<script>alert(1)</script>"}]}
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_report_exposes_reliability_cost_coverage_and_unlabeled_counts(
    saved_run,  # noqa: F811
    tmp_path,  # noqa: F811
):
    from eval_contracts.benchmark_analysis import AnalysisPolicy

    from eval_framework.benchmark.analysis_report import write_analysis

    source, _ = saved_run
    paths = write_analysis(
        source,
        dataset_path=DATASET,
        output=tmp_path / "report",
        policy=AnalysisPolicy(),
    )
    for key in ("markdown", "html"):
        text = paths[key].read_text()
        assert "pass^k" in text
        assert "known_trials" in text or "已知 trial" in text
        assert "未审/未标注" in text
        assert "--run" in text


def test_cli_comparison_of_regrade_is_scoring_only_and_preserves_sources(
    saved_run,  # noqa: F811
    tmp_path,  # noqa: F811
):
    from eval_framework.benchmark.cli import main
    from eval_framework.benchmark.regrade import regrade_run

    source, _ = saved_run
    graded = tmp_path / "graded"
    regrade_run(source, DATASET, graded)
    before = (graded / "results.json").read_bytes()
    main(
        [
            "analyze",
            "--run",
            str(graded),
            "--compare-with",
            str(source),
            "--dataset",
            str(DATASET),
            "--output",
            str(tmp_path / "analysis"),
        ]
    )
    result = json.loads((tmp_path / "analysis/analysis.json").read_text())
    assert result["comparison"]["comparison_kind"] == "scoring_only"
    assert result["comparison"]["new_executions"] == 0
    assert len(result["identity"]["source_hashes"]) == 2
    assert (graded / "results.json").read_bytes() == before


def test_comparison_includes_each_saved_population_without_pooling(saved_run, tmp_path):  # noqa: F811
    from eval_contracts.benchmark_analysis import AnalysisPolicy

    from eval_framework.benchmark.analysis_report import write_analysis
    from eval_framework.benchmark.regrade import regrade_run

    source, _ = saved_run
    graded = tmp_path / "graded"
    regrade_run(source, DATASET, graded)
    files = write_analysis(
        graded,
        dataset_path=DATASET,
        compare_with=source,
        output=tmp_path / "analysis",
        policy=AnalysisPolicy(),
    )
    value = json.loads(files["json"].read_text())
    assert value["comparison"]["baseline"]["layers"]["e2e"]["planned_trials"] == 1
    assert value["layers"]["e2e"]["planned_trials"] == 1
    assert value["identity"]["comparison_analysis_identity_hash"]
    assert "基线" in files["markdown"].read_text()
