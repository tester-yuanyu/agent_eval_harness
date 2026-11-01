"""Offline annotation remains blind and exports strict, independently entered labels."""

import importlib
import json
import shutil
import subprocess
from html.parser import HTMLParser

import pytest

from eval_framework.benchmark.judge_calibration import (
    compare_human_labels,
    create_calibration_worksheet,
)


class Page(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.scripts, self.controls, self.external = [], [], []
        self.in_script = False
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.in_script = True
            self.scripts.append("")
        if tag in {"input", "textarea"}:
            self.controls.append(attrs)
        if "src" in attrs or (tag == "link" and "href" in attrs):
            self.external.append(attrs)

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            self.scripts[-1] += data


def reporting():
    # Missing module should appear as an explicit feature failure in the RED phase.
    try:
        return importlib.import_module("eval_framework.benchmark.calibration_reporting")
    except ModuleNotFoundError:
        pytest.fail("Offline calibration reporting is not implemented")


def source():
    return [
        {
            "record_id": 'a"</script><img src=x onerror=alert(1)>',
            "metric_id": "m1",
            "name": "response_groundedness",
            "status": "SCORED",
            "score": 0.9,
            "reason": "SECRET_PREDICTION",
            "events": [
                {
                    "input": "<svg onload=alert(2)>证据 & 原文</svg>",
                    "output": "SECRET_JUDGE_OUTPUT",
                }
            ],
        }
    ]


def test_annotation_escapes_evidence_and_omits_predictions_and_prefilled_labels():
    sheet = create_calibration_worksheet(source())
    sheet["rows"][0].update(
        {
            "score": 0.9,
            "reason": "SECRET_PREDICTION",
            "human_score": 0.8,
            "annotator": "AUTO_PERSON",
            "independent": True,
        }
    )
    sheet["judge_output"] = "SECRET_JUDGE_OUTPUT"
    html = reporting().render_annotation_html(sheet)
    page = Page(html)
    assert not page.external
    assert "SECRET_PREDICTION" not in html and "SECRET_JUDGE_OUTPUT" not in html
    assert "AUTO_PERSON" not in html
    assert "&lt;svg onload=alert(2)&gt;证据 &amp; 原文&lt;/svg&gt;" in html
    assert "<img src=x" not in html
    assert len(page.scripts) == 1
    assert {item["name"] for item in page.controls} >= {
        "human_score",
        "human_reason",
        "annotator",
        "independent",
    }
    assert all(
        not item.get("value") and "checked" not in item for item in page.controls
    )


def export_with_node(html, cards):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed to execute the offline export script")
    script = Page(html).scripts[0]
    harness = r"""
const vm = require('node:vm');
const payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
let exported = null, handler, error = null;
const cards = payload.cards.map(row => ({
  dataset: {recordId: row.record_id},
  querySelector: selector => {
    const field = selector.match(/name=["']?([^"'\]]+)/)[1];
    return {value: row[field] ?? '', checked: row[field] === true};
  }
}));
const context = {
  document: {
    querySelectorAll: () => cards,
    getElementById: () => ({addEventListener: (_, cb) => {handler = cb;}}),
    createElement: () => ({click: () => {}, remove: () => {}}),
    body: {appendChild: () => {}},
  },
  Blob: function(parts) { exported = JSON.parse(parts.join('')); },
  URL: {createObjectURL: () => 'blob:offline', revokeObjectURL: () => {}},
  alert: message => { error = message; },
  setTimeout: callback => callback(),
};
vm.runInNewContext(payload.script, context);
handler();
process.stdout.write(JSON.stringify({exported, error}));
"""
    run = subprocess.run(
        [node, "-e", harness],
        input=json.dumps({"script": script, "cards": cards}),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(run.stdout)


def test_export_roundtrips_zero_blank_and_human_provenance_into_compare():
    rows = source() + [{**source()[0], "record_id": "blank"}]
    html = reporting().render_annotation_html(create_calibration_worksheet(rows))
    exported = export_with_node(
        html,
        [
            {
                "record_id": rows[0]["record_id"],
                "human_score": "0",
                "human_reason": "人工核查",
                "annotator": "reviewer",
                "independent": True,
            },
            {"record_id": "blank", "human_score": "", "independent": False},
        ],
    )
    assert exported["error"] is None
    labels = exported["exported"]
    assert labels["rows"][0]["human_score"] == 0
    assert labels["rows"][0]["human_reason"] == "人工核查"
    assert labels["rows"][0]["annotation_source"] == "human"
    assert labels["rows"][1]["human_score"] is None
    assert labels["rows"][1]["independent"] is not True
    result = compare_human_labels(rows, labels, threshold=0.7, threshold_version="v1")
    assert result["labeled"] == 1
    assert result["false_accept_rate"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"independent": False},
        {"annotator": " "},
        {"human_score": "1.5"},
        {"human_score": "not a number"},
        {"human_reason": ""},
    ],
)
def test_export_rejects_completed_scores_without_manual_provenance(change):
    html = reporting().render_annotation_html(create_calibration_worksheet(source()))
    row = {
        "record_id": "a",
        "human_score": "0",
        "human_reason": "核对证据",
        "annotator": "reviewer",
        "independent": True,
        **change,
    }
    output = export_with_node(html, [row])
    assert output["exported"] is None
    assert output["error"]


def test_report_discloses_missing_labels_denominators_and_unvalidated_threshold():
    result = compare_human_labels(source(), [], threshold=0.7, threshold_version="v1")
    report = reporting().render_calibration_report(result)
    assert report.startswith("# ")
    assert "awaiting_independent_human_labels" in report
    assert "requires_independent_validation" in report
    assert "response_groundedness" in report
    assert "未标注" in report and "分母" in report
    assert result["source_summary"]["sha256"] in report
    assert "<img src=x" not in report


def test_markdown_report_has_traceable_false_accept_case():
    rows = source()
    result = compare_human_labels(
        rows,
        [
            {
                "record_id": rows[0]["record_id"],
                "human_score": 0,
                "annotator": "human",
                "independent": True,
                "annotation_source": "human",
                "human_reason": "<script>坏</script> | 理由",
            }
        ],
        threshold=0.7,
        threshold_version="v1",
    )
    report = reporting().render_calibration_report(result)
    assert "false_accept" in report
    assert "&lt;script&gt;" in report
    assert "<script>" not in report
    assert "1 / 1" in report
