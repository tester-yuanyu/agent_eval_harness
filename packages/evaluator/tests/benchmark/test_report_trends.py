import copy

import pytest
from capability_snapshot_kit.hashing import sha256_json


def source(run_id="r1", day="01", verdict="FAIL"):
    identity = {
        "dataset": {"id": "fixed", "version": "1"},
        "scoring_version": "v1",
        "scoring_identity": {"version": "v1"},
        "harness_version": "v1",
        "harness_source": "h",
        "inspect_ai": "v",
        "config": {
            "model": "m",
            "timeout_seconds": 120,
            "temperature": 0,
            "max_steps": 4,
        },
        "runtime": {
            "provider_id": "agent",
            "source_sha256": "a",
            "isolation": "docker",
        },
        "runtime_modes": {},
    }
    run = {
        "run_id": run_id,
        "identity": identity,
        "identity_hash": sha256_json(identity),
        "config": copy.deepcopy(identity["config"]),
        "planned_case_ids": ["a", "b"],
        "trials_per_case": 1,
        "execution_backend": "inspect",
        "scoring_backend": "deepeval",
        "mode": "real_agent",
        "finished_at": f"2026-11-{day}T01:00:00Z",
        "trials": [],
    }
    for case, mode, result in [("a", "read", "PASS"), ("b", "write", verdict)]:
        run["trials"].append(
            {
                "case_id": case,
                "trial": 1,
                "identity_hash": run["identity_hash"],
                "assessment": {
                    "verdict": result,
                    "metrics": [],
                    "validity": "VALID" if result != "INVALID" else "INVALID",
                },
                "latency_seconds": 1.0,
                "observation": {},
                "category": mode,
                "evaluation_level": "e2e",
                "execution_mode": "agent",
            }
        )
    analysis = {
        "source_hash": "source-" + run_id,
        "trials": [
            {
                "case_id": r["case_id"],
                "trial": 1,
                "operation": r["category"],
                "goal_bound": True,
                "verdict": r["assessment"]["verdict"],
            }
            for r in run["trials"]
        ],
    }
    receipt = {"traces": [{"experiment_id": "exp-" + run_id}]}
    return {"run": run, "analysis": analysis, "receipt": receipt}


def test_trend_has_one_point_per_run_and_keeps_invalid_in_denominator():
    from eval_framework.benchmark.report_trends import build_trend

    trend = build_trend([source(verdict="INVALID"), source("r2", "02", "PASS")])
    assert len(trend["runs"]) == 2
    assert trend["runs"][0]["groups"]["write"] == {
        "passed": 0,
        "total": 1,
        "invalid": 1,
        "pass_rate_percent": 0.0,
    }
    assert trend["runs"][1]["groups"]["write"]["pass_rate_percent"] == 100
    assert trend["formal"] is False


@pytest.mark.parametrize(
    "change", ["dataset", "selection", "timeout", "duplicate", "incomplete", "unbound"]
)
def test_trend_rejects_incompatible_or_ambiguous_sources(change):
    from eval_framework.benchmark.report_trends import build_trend

    a, b = source(), source("r2", "02")
    if change == "dataset":
        b["run"]["identity"]["dataset"]["version"] = "2"
    if change == "selection":
        b["run"]["planned_case_ids"] = ["a"]
    if change == "timeout":
        b["run"]["identity"]["config"]["timeout_seconds"] = 240
    if change == "duplicate":
        b = a
    if change == "incomplete":
        b["run"]["trials"].pop()
    if change == "unbound":
        b["analysis"]["trials"][0]["goal_bound"] = False
    b["run"]["identity_hash"] = sha256_json(b["run"]["identity"])
    for row in b["run"]["trials"]:
        row["identity_hash"] = b["run"]["identity_hash"]
    with pytest.raises(ValueError):
        build_trend([a, b])


def test_model_change_is_recorded_and_does_not_change_comparison_group():
    from eval_framework.benchmark.report_trends import build_trend

    a, b = source(), source("r2", "02")
    b["run"]["identity"]["config"]["model"] = "new-model"
    b["run"]["config"]["model"] = "new-model"
    b["run"]["identity"]["runtime"]["source_sha256"] = "new-implementation"
    b["run"]["identity_hash"] = sha256_json(b["run"]["identity"])
    for row in b["run"]["trials"]:
        row["identity_hash"] = b["run"]["identity_hash"]
    assert build_trend([a])["cohort_id"] == build_trend([a, b])["cohort_id"]
    assert (
        build_trend([a, b])["runs"][1]["runtime"]["source_sha256"]
        == "new-implementation"
    )
