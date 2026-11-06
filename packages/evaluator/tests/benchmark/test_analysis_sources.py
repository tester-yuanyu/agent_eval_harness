import hashlib
from copy import deepcopy

import pytest
from capability_snapshot_kit.hashing import sha256_json

from .analysis_fixtures import run, save
from .test_regrade import DATASET, saved_run  # noqa: F401


def test_original_and_actual_regrade_share_execution_keys(saved_run, tmp_path):  # noqa: F811
    from eval_framework.benchmark.analysis_sources import load_analysis_source
    from eval_framework.benchmark.regrade import regrade_run

    original, _ = saved_run
    graded = tmp_path / "graded"
    regrade_run(original, DATASET, graded)
    a = load_analysis_source(original)
    with pytest.raises(ValueError, match="source"):
        load_analysis_source(graded)
    b = load_analysis_source(graded, source_artifacts=(original / "results.json",))
    assert a["canonical_keys"] == b["canonical_keys"]
    assert b["execution_result"] == a["execution_result"]
    assert len(b["verified_source_hashes"]) == 2


@pytest.mark.parametrize("change", ["identity", "observation", "source_trial", "plan"])
def test_regrade_tampering_rejected(saved_run, tmp_path, change):  # noqa: F811
    from eval_framework.benchmark.analysis_sources import load_analysis_source
    from eval_framework.benchmark.regrade import regrade_run

    original, _ = saved_run
    graded = tmp_path / "graded"
    value = regrade_run(original, DATASET, graded)
    if change == "identity":
        value["identity"]["offline"] = True
    elif change == "observation":
        value["trials"][0]["observation"]["status"] = "fabricated"
    elif change == "source_trial":
        value["trials"][0]["source_trial_sha256"] = "0" * 64
    else:
        value["planned_case_ids"].append("invented")
    save(graded, value)
    with pytest.raises(ValueError):
        load_analysis_source(graded, source_artifacts=(original,))


def test_judge_subset_attaches_without_becoming_new_execution(tmp_path):
    from eval_framework.benchmark.analysis_sources import load_analysis_source

    original = run()
    source = save(tmp_path / "source", original)
    judge = deepcopy(original)
    h = hashlib.sha256((source / "results.json").read_bytes()).hexdigest()
    judge["identity"].update(source_results_sha256=h, case_ids=["a"])
    judge["identity_hash"] = sha256_json(judge["identity"])
    judge["planned_case_ids"] = ["a"]
    judge["trials"] = [r for r in judge["trials"] if r["case_id"] == "a"]
    judge["provenance"] = {
        "operation": "judge_saved_evidence",
        "source_results_sha256": h,
        "source_identity_hash": original["identity_hash"],
        "source_run_id": original["run_id"],
    }
    for row, before in zip(judge["trials"], original["trials"], strict=False):
        row.update(
            identity_hash=judge["identity_hash"],
            source_trial_sha256=sha256_json(before),
            source_assessment=deepcopy(before["assessment"]),
        )
    path = save(tmp_path / "judge", judge)
    with pytest.raises(ValueError, match="judge"):
        load_analysis_source(path)
    attached = load_analysis_source(source, judge_dir=path)
    assert len(attached["canonical_keys"]) == 6
    assert len(attached["judge_trials"]) == 3


def test_missing_upstream_never_follows_recorded_source_dir(tmp_path):
    from eval_framework.benchmark.analysis_sources import load_analysis_source

    value = run()
    value["regrade"] = {
        "operation": "regrade_saved_evidence",
        "source_results_sha256": "0" * 64,
        "source_identity_hash": value["identity_hash"],
        "source_dir": "https://example.invalid",
    }
    with pytest.raises(ValueError, match="source"):
        load_analysis_source(save(tmp_path / "run", value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("offline", True),
        ("runtime", {"id": "changed"}),
        ("config", {"model": "changed"}),
    ],
)
def test_regrade_cannot_reseal_a_changed_execution_identity(
    saved_run,  # noqa: F811
    tmp_path,
    field,
    value,  # noqa: F811
):
    from eval_framework.benchmark.analysis_sources import load_analysis_source
    from eval_framework.benchmark.regrade import regrade_run

    original, _ = saved_run
    graded = tmp_path / "graded"
    result = regrade_run(original, DATASET, graded)
    result["identity"][field] = value
    result["identity_hash"] = sha256_json(result["identity"])
    for row in result["trials"]:
        row["identity_hash"] = result["identity_hash"]
    save(graded, result)
    with pytest.raises(ValueError, match="execution identity"):
        load_analysis_source(graded, source_artifacts=(original,))


def test_attached_judge_error_and_missing_trial_are_not_scored(tmp_path):
    from eval_contracts.benchmark_analysis import AnalysisPolicy

    from eval_framework.aggregator.analysis import analyze_run
    from eval_framework.benchmark.analysis_sources import load_analysis_source

    from .analysis_fixtures import dataset

    original = run()
    path = save(tmp_path / "source", original)
    judge = deepcopy(original)
    digest = hashlib.sha256((path / "results.json").read_bytes()).hexdigest()
    judge["identity"].update(source_results_sha256=digest, case_ids=["a"])
    judge["identity_hash"] = sha256_json(judge["identity"])
    judge["planned_case_ids"] = ["a"]
    judge["trials"] = judge["trials"][:2]
    judge["provenance"] = {
        "operation": "judge_saved_evidence",
        "source_results_sha256": digest,
        "source_identity_hash": original["identity_hash"],
        "source_run_id": original["run_id"],
    }
    for row, old, status in zip(
        judge["trials"], original["trials"], ["SCORED", "ERROR"], strict=False
    ):
        row.update(
            identity_hash=judge["identity_hash"],
            source_trial_sha256=sha256_json(old),
            source_assessment=deepcopy(old["assessment"]),
        )
        row["assessment"]["metrics"].append(
            {"formal": False, "judge_repeat": 1, "status": status}
        )
    source = load_analysis_source(path, judge_dir=save(tmp_path / "judge", judge))
    result = analyze_run(source, dataset=dataset(), policy=AnalysisPolicy())
    assert result["judge_coverage"]["planned_trials"] == 3
    assert result["judge_coverage"]["scored_trials"] == 1
    assert result["judge_coverage"]["error_trials"] == 1
    assert result["judge_coverage"]["missing_trials"] == 1
    assert result["layers"]["e2e"]["planned_trials"] == 6


@pytest.mark.parametrize("marker", ["identity", "row"])
def test_orphan_derived_markers_cannot_become_an_execution(tmp_path, marker):
    from eval_framework.benchmark.analysis_sources import load_analysis_source

    result = run()
    if marker == "identity":
        result["identity"]["source_results_sha256"] = "0" * 64
        result["identity_hash"] = sha256_json(result["identity"])
        for row in result["trials"]:
            row["identity_hash"] = result["identity_hash"]
    else:
        result["trials"][0]["source_trial_sha256"] = "0" * 64
        result["trials"][0]["source_assessment"] = deepcopy(
            result["trials"][0]["assessment"]
        )
    with pytest.raises(ValueError, match="provenance"):
        load_analysis_source(save(tmp_path / "orphan", result))
