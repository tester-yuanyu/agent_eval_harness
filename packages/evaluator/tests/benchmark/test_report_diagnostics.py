import json

import pytest

from .test_report_insights import failure_run, render


def test_optional_profile_and_shared_diagnosis_are_bound_and_reproducible(tmp_path):
    from eval_framework.benchmark.report_diagnostics import (
        build_diagnostics,
        write_diagnostics,
    )

    run = failure_run(tmp_path)
    render(tmp_path, run)
    analysis = build_diagnostics(tmp_path)
    assert analysis["formal"] is False
    assert analysis["trials"][0]["findings"][0]["aliases"] == {"count": "num"}
    artifact = write_diagnostics(tmp_path)
    assert json.loads(artifact.read_text()) == analysis
    assert write_diagnostics(tmp_path).read_bytes() == artifact.read_bytes()
    (tmp_path / "report-diagnostics.json").unlink()
    generic = build_diagnostics(tmp_path)
    assert generic["trials"][0]["findings"][0]["aliases"] == {}
    assert "count→num" not in generic["trials"][0]["findings"][0]["action"]
    assert generic["analysis_id"] != analysis["analysis_id"]


def test_profile_hash_and_intent_scope_prevent_silent_alias_invention(tmp_path):
    from eval_framework.benchmark.report_diagnostics import (
        build_diagnostics,
        profile_hash,
    )

    run = failure_run(tmp_path)
    render(tmp_path, run)
    path = tmp_path / "report-diagnostics.json"
    profile = json.loads(path.read_text())
    profile["aliases"] = {"unrelated_intent": {"count": "num"}}
    path.write_text(json.dumps(profile))
    with pytest.raises(ValueError, match="profile Hash"):
        build_diagnostics(tmp_path)
    profile["sha256"] = profile_hash(profile)
    path.write_text(json.dumps(profile))
    assert build_diagnostics(tmp_path)["trials"][0]["findings"][0]["aliases"] == {}


def test_advice_follows_observed_aliases_and_prompt_evidence(tmp_path):
    from eval_framework.benchmark.report_diagnostics import build_diagnostics

    run = failure_run(tmp_path)
    render(tmp_path, run)
    finding = build_diagnostics(tmp_path)["trials"][0]["findings"][0]
    assert "count→num" in finding["action"]
    assert "validity_days" not in finding["action"]
    assert "先核对" in finding["action"]  # No request Schema evidence in this fixture.
    # No applicable failure means no stale finding/advice carried from the last run.
    run["trials"][0]["assessment"]["verdict"] = "PASS"
    render(tmp_path, run)
    assert build_diagnostics(tmp_path)["trials"][0]["findings"] == []


def test_report_links_require_matching_verified_receipts(tmp_path):
    from hashlib import sha256

    from eval_framework.benchmark.report_links import write_links

    run = failure_run(tmp_path)
    report = render(tmp_path, run)
    assert "Langfuse：未导出或未核验" in report
    source = sha256((tmp_path / "results.json").read_bytes()).hexdigest()
    receipt = {
        "source_hash": source,
        "destination": "dest",
        "traces": [{"case_id": "case-one", "trial": 1, "trace_id": "a" * 32}],
        "status": "ACCEPTED",
    }
    (tmp_path / "langfuse_export.json").write_text(json.dumps(receipt))
    (tmp_path / "langfuse_verification.json").write_text(
        json.dumps({"source_hash": source, "status": "VERIFIED"})
    )
    write_links(
        tmp_path,
        base_url="https://langfuse.example",
        project_id="project",
        destination="dest",
    )
    report = render(tmp_path, run)
    assert "https://langfuse.example/project/project/traces/" + "a" * 32 in report
    receipt["destination"] = "wrong-project"
    (tmp_path / "langfuse_export.json").write_text(json.dumps(receipt))
    assert "Langfuse：未导出或未核验" in render(tmp_path, run)


def test_links_reject_unsafe_destination(tmp_path):
    from eval_framework.benchmark.report_links import write_links

    with pytest.raises(ValueError):
        write_links(
            tmp_path, base_url="javascript:alert(1)", project_id="p", destination="d"
        )
