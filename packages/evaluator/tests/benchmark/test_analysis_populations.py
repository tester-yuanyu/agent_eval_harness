from copy import deepcopy

import pytest

from .analysis_fixtures import dataset, run, save


def population(tmp_path, value):
    from eval_framework.aggregator.populations import build_population
    from eval_framework.benchmark.analysis_sources import load_analysis_source

    source = load_analysis_source(save(tmp_path / "run", value))
    return build_population(source, dataset=dataset(), annotations=None)


def test_missing_planned_trial_remains_in_denominator(tmp_path):
    value = run()
    value["trials"].pop()
    result = population(tmp_path, value)
    assert len(result["trials"]) == 6
    assert sum(r["verdict"] == "MISSING" for r in result["trials"]) == 1
    assert result["layers"]["e2e"]["planned_trials"] == 6


@pytest.mark.parametrize(
    "change", ["duplicate", "outside", "layer", "dataset", "bool_trial"]
)
def test_population_rejects_ambiguous_or_wrong_denominators(tmp_path, change):
    value = run()
    if change == "duplicate":
        value["trials"].append(deepcopy(value["trials"][0]))
    elif change == "outside":
        value["trials"][0]["case_id"] = "other"
    elif change == "layer":
        value["trials"][0]["evaluation_level"] = "module"
    elif change == "bool_trial":
        value["trials"][0]["trial"] = True
    else:
        from capability_snapshot_kit.hashing import sha256_json

        value["identity"]["dataset"] = {"id": "other"}
        value["identity_hash"] = sha256_json(value["identity"])
        for row in value["trials"]:
            row["identity_hash"] = value["identity_hash"]
    with pytest.raises(ValueError):
        population(tmp_path, value)
