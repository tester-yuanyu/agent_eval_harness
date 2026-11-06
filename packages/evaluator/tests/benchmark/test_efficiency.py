from copy import deepcopy

import pytest

from .analysis_fixtures import run
from .test_analysis_populations import population


def cost_population(tmp_path):
    pop = population(tmp_path, run())
    pop["trials"] = [r for r in pop["trials"] if r["case_id"] == "a"]
    for row, cost in zip(pop["trials"], (10, 20, 30), strict=True):
        row["record"]["observation"]["usage"] = {"cost_usd": cost, "total_tokens": cost}
    pop["trials"][-1]["verdict"] = "FAIL"
    return pop


def test_cost_per_success_includes_failed_attempts_and_reports_coverage(tmp_path):
    from eval_framework.aggregator.efficiency import efficiency

    result = efficiency(cost_population(tmp_path))["by_layer"]["e2e"]["agent"][
        "cost_usd"
    ]
    assert result["successful_mean"] == 15
    assert result["per_success"] == 30
    assert result["coverage"] == {
        "known_trials": 3,
        "planned_trials": 3,
        "complete_tasks": 1,
        "planned_tasks": 1,
    }


def test_partial_usage_and_zero_success_stay_unknown(tmp_path):
    from eval_framework.aggregator.efficiency import efficiency

    pop = cost_population(tmp_path)
    pop["trials"][1]["record"]["observation"]["usage"]["cost_usd"] = None
    result = efficiency(pop)["by_layer"]["e2e"]["agent"]["cost_usd"]
    assert result["per_success"] is None
    assert result["known_subtotal"] == 40
    assert result["coverage"]["complete_tasks"] == 0
    for row in pop["trials"]:
        row["verdict"] = "FAIL"
    assert (
        efficiency(pop)["by_layer"]["e2e"]["agent"]["total_tokens"]["per_success"]
        is None
    )


@pytest.mark.parametrize("bad", [True, -1, float("nan"), float("inf")])
def test_invalid_numeric_usage_is_rejected(tmp_path, bad):
    from eval_framework.aggregator.efficiency import efficiency

    pop = cost_population(tmp_path)
    pop["trials"][0]["record"]["observation"]["usage"]["cost_usd"] = bad
    with pytest.raises(ValueError):
        efficiency(pop)


def test_aliases_and_judge_cost_are_not_double_counted(tmp_path):
    from eval_framework.aggregator.efficiency import efficiency

    pop = cost_population(tmp_path)
    pop["trials"] = pop["trials"][:1]
    row = pop["trials"][0]["record"]
    row["observation"]["usage"] = {}
    row["observation"]["events"] = [
        {
            "type": "generation",
            "id": "g1",
            "usage": {"input_tokens": 5, "prompt_tokens": 5, "cost_usd": 1},
        }
    ]
    judge = deepcopy(row)
    judge["observation"]["events"].append(
        {
            "type": "generation",
            "id": "j1",
            "is_judge": True,
            "usage": {"input_tokens": 20, "cost_usd": 2},
        }
    )
    pop["judge_trials"] = [judge]
    result = efficiency(pop)["by_layer"]["e2e"]
    assert result["agent"]["input_tokens"]["known_subtotal"] == 5
    assert result["agent"]["cost_usd"]["known_subtotal"] == 1
    assert result["judge"]["cost_usd"]["known_subtotal"] == 2


def test_missing_usage_in_a_recorded_call_is_not_zero(tmp_path):
    from eval_framework.aggregator.efficiency import efficiency

    pop = cost_population(tmp_path)
    pop["trials"] = pop["trials"][:1]
    obs = pop["trials"][0]["record"]["observation"]
    obs["usage"] = {}
    obs["events"] = [{"id": "g1", "type": "generation"}]
    result = efficiency(pop)["by_layer"]["e2e"]["agent"]
    assert result["total_tokens"]["known_subtotal"] is None
    assert result["generation_calls"]["known_subtotal"] == 1
    assert result["tool_calls"]["known_subtotal"] == 0


def test_judge_error_with_unknown_requests_does_not_report_zero_cost(tmp_path):
    from eval_framework.aggregator.efficiency import efficiency

    pop = cost_population(tmp_path)
    pop["trials"] = pop["trials"][:1]
    judge = deepcopy(pop["trials"][0]["record"])
    judge["assessment"]["metrics"] = [
        {
            "formal": False,
            "judge_repeat": 1,
            "status": "ERROR",
            "model_requests_unknown": True,
            "events": [],
        }
    ]
    pop["judge_trials"] = [judge]
    result = efficiency(pop)["by_layer"]["e2e"]["judge"]
    assert result["cost_usd"]["known_count"] == 0
    assert result["generation_calls"]["known_subtotal"] is None


def test_judge_missing_planned_trials_remain_in_coverage(tmp_path):
    from eval_framework.aggregator.efficiency import efficiency

    pop = cost_population(tmp_path)
    pop["judge_plan"] = [["a", 1], ["a", 2], ["a", 3]]
    judge = deepcopy(pop["trials"][0]["record"])
    judge["observation"]["events"] = [
        {"type": "generation", "is_judge": True, "usage": {"cost_usd": 2}}
    ]
    pop["judge_trials"] = [judge]
    value = efficiency(pop)["by_layer"]["e2e"]["judge"]["cost_usd"]
    assert value["coverage"]["known_trials"] == 1
    assert value["coverage"]["planned_trials"] == 3
    assert value["total"] is None
