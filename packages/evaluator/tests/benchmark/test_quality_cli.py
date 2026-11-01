"""Public offline calibration commands must produce usable, non-overwriting output."""

import json

import pytest

from eval_framework.benchmark.cli import main
from eval_framework.benchmark.judge_calibration import create_calibration_worksheet


def test_blind_page_and_empty_calibration_report_from_cli(tmp_path):
    records = [
        {
            "record_id": "a",
            "metric_id": "m",
            "name": "response_groundedness",
            "version": "trajectory-geval-v1",
            "scope": "turn",
            "event_id": "t1",
            "status": "SCORED",
            "score": 0.9,
            "reason": "HIDDEN_PREDICTION",
            "events": [{"input": "visible evidence", "output": "HIDDEN_PREDICTION"}],
        }
    ]
    source = tmp_path / "source"
    source.mkdir()
    (source / "results.json").write_text(json.dumps(records))
    sheet = tmp_path / "worksheet.json"
    sheet.write_text(json.dumps(create_calibration_worksheet(records)))
    page = tmp_path / "page.html"
    assert (
        main(["calibration-page", "--worksheet", str(sheet), "--output", str(page)])
        == 0
    )
    assert "visible evidence" in page.read_text()
    assert "HIDDEN_PREDICTION" not in page.read_text()
    output, report = tmp_path / "checked.json", tmp_path / "report.md"
    assert (
        main(
            [
                "calibration-check",
                "--run",
                str(source),
                "--labels",
                str(sheet),
                "--threshold",
                "0.8",
                "--threshold-version",
                "exploratory-only",
                "--output",
                str(output),
                "--report",
                str(report),
            ]
        )
        == 0
    )
    checked = json.loads(output.read_text())
    assert checked["labeled"] == checked["paired"] == 0
    assert checked["agreement"] is None
    assert checked["threshold_status"] == "requires_independent_validation"
    assert report.exists()
    with pytest.raises(SystemExit):
        main(["calibration-page", "--worksheet", str(sheet), "--output", str(page)])


def test_existing_report_prevents_partial_calibration_outputs(tmp_path):
    report = tmp_path / "existing.md"
    report.write_text("keep")
    output = tmp_path / "new.json"
    with pytest.raises(SystemExit):
        main(
            [
                "calibration-check",
                "--run",
                str(tmp_path),
                "--labels",
                str(tmp_path / "labels"),
                "--threshold",
                "0.8",
                "--threshold-version",
                "candidate",
                "--output",
                str(output),
                "--report",
                str(report),
            ]
        )
    assert not output.exists()
    assert report.read_text() == "keep"
