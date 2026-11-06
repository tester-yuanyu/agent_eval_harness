from copy import deepcopy

import pytest
from capability_snapshot_kit.hashing import sha256_json

from .analysis_fixtures import run


def controlled():
    value = run()
    value["identity"].update(
        scoring_identity={"v": "score"},
        harness_source={"v": "harness"},
        tools={"v": "tools"},
        environment={"v": "local"},
        prompt={"v": "prompt"},
        repeat_protocol={"v": "protocol"},
    )
    return value


def test_exploratory_comparison_needs_no_spec_and_redacts_config():
    from eval_framework.aggregator.experiment import validate_experiment

    left = controlled()
    right = deepcopy(left)
    right["identity"]["config"]["model"] = "SECRET_SENTINEL"
    result = validate_experiment(left, right, None)
    assert result["status"] == "descriptive_only"
    assert "model" in [d["field"] for d in result["differences"]]
    assert "SECRET_SENTINEL" not in str(result)


def test_only_prespecified_model_change_is_controlled():
    from eval_framework.aggregator.experiment import (
        REQUIRED_CONTROLS,
        validate_experiment,
    )

    left = controlled()
    right = deepcopy(left)
    right["run_id"] = "candidate"
    right["identity"]["config"]["model"] = "candidate"
    spec = {"control_fields": list(REQUIRED_CONTROLS), "variable_fields": ["model"]}
    assert validate_experiment(left, right, spec)["status"] == "compatible"
    right["identity"]["tools"] = {"v": "changed"}
    assert validate_experiment(left, right, spec)["status"] == "descriptive_only"
    assert "tools" in validate_experiment(left, right, spec)["mismatches"]


@pytest.mark.parametrize(
    "field", ["dataset", "scoring_identity", "harness_source", "environment", "prompt"]
)
def test_control_changes_cannot_be_hidden_by_experiment_spec(field):
    from eval_framework.aggregator.experiment import (
        REQUIRED_CONTROLS,
        validate_experiment,
    )

    left = controlled()
    right = deepcopy(left)
    right["run_id"] = "candidate"
    right["identity"][field] = {"changed": True}
    result = validate_experiment(
        left,
        right,
        {"control_fields": list(REQUIRED_CONTROLS), "variable_fields": ["model"]},
    )
    assert result["status"] == "descriptive_only"
    assert result["mismatches"]


def test_same_execution_regrade_is_scoring_only():
    from eval_framework.aggregator.experiment import validate_experiment

    left = controlled()
    right = deepcopy(left)
    right["execution_run_id"] = left["run_id"]
    right["execution_identity"] = deepcopy(left["identity"])
    right["identity"]["scoring_identity"] = {"v": "new-score"}
    right["identity_hash"] = sha256_json(right["identity"])
    result = validate_experiment(left, right, None)
    assert result["comparison_kind"] == "scoring_only"
    assert result["new_executions"] == 0


def test_missing_historical_control_is_not_assumed_equal():
    from eval_framework.aggregator.experiment import (
        REQUIRED_CONTROLS,
        validate_experiment,
    )

    left = run()
    right = deepcopy(left)
    right["run_id"] = "candidate"
    result = validate_experiment(
        left,
        right,
        {"control_fields": list(REQUIRED_CONTROLS), "variable_fields": ["model"]},
    )
    assert result["status"] == "descriptive_only"
    assert "tools" in result["unknown_controls"]
