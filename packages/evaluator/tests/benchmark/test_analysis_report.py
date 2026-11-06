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
