import pytest

from .analysis_fixtures import run
from .test_analysis_populations import population


def test_pass_k_matches_hand_computed_values(tmp_path):
    from eval_framework.aggregator.reliability import reliability

    value = reliability(
        population(tmp_path, run()), ks=(1, 2, 3, 4), repeat_protocol=None
    )["by_layer"]["e2e"]
    assert value["pass_hat_k"]["1"]["micro"] == pytest.approx(5 / 6)
    assert value["pass_hat_k"]["2"]["micro"] == pytest.approx(2 / 3)
    assert value["pass_hat_k"]["3"]["micro"] == 0.5
    assert value["pass_hat_k"]["4"] == {
        "status": "insufficient_trials",
        "micro": None,
        "family_macro": None,
    }
    assert value["repeat_protocol_status"] == "descriptive_not_verified_independent"


@pytest.mark.parametrize("kind", ["MISSING", "INVALID"])
def test_incomplete_population_has_no_primary_estimate(tmp_path, kind):
    from eval_framework.aggregator.reliability import reliability

    value = run()
    if kind == "MISSING":
        value["trials"].pop()
    else:
        value["trials"][-1]["assessment"].update(verdict="INVALID", validity="INVALID")
    result = reliability(population(tmp_path, value), ks=(1, 3), repeat_protocol=None)[
        "by_layer"
    ]["e2e"]
    assert result["pass_hat_k"]["1"]["micro"] is None
    assert result["pass_hat_k"]["3"]["status"] == "unavailable_incomplete_population"
    assert result["all_trials_pass_rate"] == 0.5


def test_inconclusive_is_non_success_and_macro_weights_families(tmp_path):
    from eval_framework.aggregator.reliability import reliability

    pop = population(tmp_path, run())
    for row in pop["trials"]:
        if row["case_id"] == "b" and row["trial"] == 3:
            row["verdict"] = "INCONCLUSIVE"
    assert (
        reliability(pop, ks=(3,), repeat_protocol=None)["by_layer"]["e2e"][
            "pass_hat_k"
        ]["3"]["micro"]
        == 0.5
    )
    # 两个 a 类家族任务全通过，另一家族失败：micro 2/3，family macro 1/2。
    extra = [{**r, "case_id": "a2"} for r in pop["trials"] if r["case_id"] == "a"]
    pop["trials"] += extra
    value = reliability(pop, ks=(3,), repeat_protocol=None)["by_layer"]["e2e"][
        "pass_hat_k"
    ]["3"]
    assert value["micro"] == pytest.approx(2 / 3)
    assert value["family_macro"] == 0.5


def test_reference_demo_never_gets_agent_reliability(tmp_path):
    from eval_framework.aggregator.reliability import reliability

    pop = population(tmp_path, run())
    pop["framework_only"] = True
    assert (
        reliability(pop, ks=(1,), repeat_protocol=None)["by_layer"]["e2e"][
            "pass_hat_k"
        ]["1"]["status"]
        == "framework_demo_only"
    )
