import pytest
from eval_framework.benchmark.runner import compare_runs, summarize, validate_config


def trial(case, verdict, trial=1, split="dev"):
    return {
        "case_id": case,
        "trial": trial,
        "split": split,
        "category": "read_search",
        "assessment": {
            "verdict": verdict,
            "validity": "VALID" if verdict != "INVALID" else "INVALID",
        },
        "observation": {"usage": {}, "events": []},
        "latency_seconds": 1.0,
    }


def test_missing_trials_do_not_inflate_all_trials_success():
    report = summarize([trial("a", "PASS"), trial("b", "FAIL")], ["a", "b"], 3)
    assert report["planned_trials"] == 6
    assert report["completed_trials"] == 2
    assert report["pass_rate_planned"] == 1 / 6
    assert report["all_trials_pass_rate"] == 0
    assert report["usage"]["cost_usd"] is None


def test_heldout_and_invalid_counts_are_visible():
    report = summarize(
        [trial("a", "PASS"), trial("b", "INVALID", split="holdout")], ["a", "b"], 1
    )
    assert report["by_split"]["holdout"]["verdicts"]["INVALID"] == 1
    assert report["valid_trials"] == 1
    assert report["pass_rate_valid"] == 1.0
    assert report["pass_rate_planned"] == 0.5


def test_secret_values_rejected_in_saved_config():
    with pytest.raises(ValueError, match="secret"):
        validate_config({"api_key": "not-a-real-key"})


def test_comparison_rejects_different_dataset_and_missing_trials():
    a = {
        "identity": {"dataset": "a", "scoring_version": "v1"},
        "planned_case_ids": ["a"],
        "trials_per_case": 1,
        "trials": [trial("a", "PASS")],
    }
    b = {**a, "identity": {**a["identity"], "dataset": "b"}}
    with pytest.raises(ValueError, match="dataset"):
        compare_runs(a, b)
    with pytest.raises(ValueError, match="incomplete"):
        compare_runs(a, {**a, "trials": []})
