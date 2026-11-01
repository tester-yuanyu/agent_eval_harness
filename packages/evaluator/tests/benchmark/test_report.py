from __future__ import annotations

import json
from html.parser import HTMLParser

import pytest
from eval_framework.benchmark.report import evidence_summary, write_report


def saved_run():
    return {
        "run_id": "example-run",
        "mode": "real_agent",
        "identity": {
            "dataset": {"dataset_id": "example-v1"},
            "runtime": {"agent": "nanobot"},
        },
        "planned_case_ids": ["case-one", "case-two"],
        "trials_per_case": 1,
        "trials": [
            {
                "case_id": "case-one",
                "trial": 1,
                "split": "dev",
                "category": "read",
                "latency_seconds": 2.0,
                "assessment": {"verdict": "PASS", "validity": "VALID", "metrics": []},
                "observation": {
                    "status": "completed",
                    "before_files": {},
                    "final_files": {},
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 4,
                        "total_tokens": 24,
                    },
                    "turns": [{"input": "read", "output": "done"}],
                    "events": [],
                },
            }
        ],
        "summary": {
            "completed_trials": 1,
            "missing_trials": 1,
            "verdicts": {"PASS": 1},
        },
    }


def test_counts_denominators_and_usage_aliases_are_evidence_based(tmp_path):
    run = saved_run()
    summary = evidence_summary(run)
    assert summary["planned_trials"] == 2
    assert summary["completed_trials"] == 1
    assert summary["all_trials_pass_tasks"] == 1
    assert summary["usage"]["input_tokens"]["total"] == 20
    assert summary["usage"]["output_tokens"]["total"] == 4
    assert summary["usage"]["cost_usd"]["total"] is None
    (tmp_path / "results.json").write_text(json.dumps(run))
    original = (tmp_path / "results.json").read_bytes()
    path = write_report(tmp_path)
    assert "50.0%" in path.read_text()
    assert "费用 USD：未知" in path.read_text()
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "results.json").read_bytes() == original


def test_report_escapes_all_agent_content_and_marks_offline(tmp_path):
    run = saved_run()
    attack = '</script><img src=x onerror="alert(1)">'
    run["run_id"] = attack
    run["mode"] = "offline_reference_smoke"
    row = run["trials"][0]
    row["observation"]["turns"][0]["output"] = attack
    row["observation"]["events"] = [
        {
            "type": "tool",
            "name": attack,
            "input": {"path": attack},
            "output": attack,
            "execution_started": False,
        }
    ]
    (tmp_path / "results.json").write_text(json.dumps(run))
    rendered = write_report(tmp_path).read_text()
    assert attack not in rendered
    assert "&lt;/script&gt;&lt;img" in rendered
    assert "离线参考验证 · 非真实 Agent 成绩" in rendered
    assert "非真实 Agent 成绩" in rendered
    assert "调用被拒绝，未执行" in rendered
    assert rendered.count("<script>") == 1


def test_report_rejects_summary_contradiction_and_duplicate_trial(tmp_path):
    run = saved_run()
    run["summary"]["verdicts"] = {"PASS": 2}
    with pytest.raises(ValueError, match="disagrees"):
        evidence_summary(run)
    run = saved_run()
    run["trials"].append(run["trials"][0])
    with pytest.raises(ValueError, match="duplicate"):
        evidence_summary(run)


def test_partial_usage_remains_unknown_instead_of_zero():
    run = saved_run()
    second = json.loads(json.dumps(run["trials"][0]))
    second["case_id"] = "case-two"
    second["observation"]["usage"] = {}
    run["trials"].append(second)
    run.pop("summary")
    usage = evidence_summary(run)["usage"]["total_tokens"]
    assert usage == {"total": None, "known_subtotal": 24, "known_trials": 1}


def test_diagnostic_metric_does_not_appear_as_formal_failure(tmp_path):
    run = saved_run()
    run["trials"][0]["assessment"]["metrics"] = [
        {
            "name": "tool_correctness",
            "score": 0,
            "threshold": 1,
            "success": False,
            "formal": False,
            "reason": "alternative allowed tool path",
        }
    ]
    (tmp_path / "results.json").write_text(json.dumps(run))
    rendered = write_report(tmp_path).read_text()
    assert "诊断（不决定 verdict）" in rendered
    assert '<p class="failure-reason">' not in rendered


def test_900_trials_have_small_index_and_complete_offline_detail_pages(tmp_path):
    run = saved_run()
    template = run["trials"][0]
    run.pop("summary")
    run["planned_case_ids"] = [f"case/{index:03d}" for index in range(300)]
    run["trials_per_case"] = 3
    run["trials"] = []
    large_payload = "LARGE_TRACE_PAYLOAD_" + "x" * 8000
    for case_id in run["planned_case_ids"]:
        for trial in (1, 2, 3):
            row = json.loads(json.dumps(template))
            row.update(case_id=case_id, trial=trial)
            row["observation"]["events"] = [
                {
                    "type": "generation",
                    "name": "offline-test-model",
                    "input": {"messages": [{"role": "user", "content": large_payload}]},
                    "output": {"content": "done"},
                    "usage": {"total_tokens": 24},
                }
            ]
            run["trials"].append(row)
    results = tmp_path / "results.json"
    results.write_text(json.dumps(run), encoding="utf-8")
    original_bytes = results.read_bytes()
    report = write_report(tmp_path)
    markup = report.read_text()
    assert report.stat().st_size < 5_000_000
    assert large_payload not in markup
    assert "report-trials/" in markup
    assert results.read_bytes() == original_bytes

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.details = []

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == "a" and attributes.get("class") == "detail-link":
                self.details.append(attributes["href"])

    links = Links()
    links.feed(markup)
    assert len(links.details) == len(set(links.details)) == 900
    for href in links.details:
        target = (tmp_path / href).resolve()
        assert target.is_relative_to(tmp_path.resolve())
        detail = target.read_text()
        assert large_payload in detail
        assert 'href="../report.html"' in detail
        assert "独立文件证据" in detail
    # Filenames are reproducible; regenerating a report does not create a new
    # set of pages for the same case/trial identities.
    write_report(tmp_path)
    assert len(list((tmp_path / "report-trials").glob("*.html"))) == 900
