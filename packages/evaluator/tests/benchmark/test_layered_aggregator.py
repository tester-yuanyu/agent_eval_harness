"""五层视图只分组保存的证据，不把缺失记录或诊断转成正式通过。"""

from copy import deepcopy
from importlib import import_module, util

import pytest


def aggregator():
    name = "eval_framework.aggregator"
    assert util.find_spec(name) is not None, "Aggregator implementation is required"
    return import_module(name)


def saved_run():
    return {
        "planned_case_ids": ["a", "b"],
        "trials_per_case": 2,
        "trials": [
            {
                "case_id": "a",
                "trial": 1,
                "latency_seconds": 2,
                "assessment": {
                    "verdict": "INCONCLUSIVE",
                    "validity": "VALID",
                    "metrics": [
                        {
                            "name": "hard",
                            "scope": "task",
                            "formal": True,
                            "score": None,
                            "success": None,
                        },
                        {
                            "name": "diagnostic",
                            "scope": "tool",
                            "event_id": "tool-1",
                            "formal": False,
                            "score": 0,
                            "success": False,
                        },
                        {
                            "name": "checkpoint",
                            "scope": "turn",
                            "event_id": "turn-1",
                            "formal": True,
                            "score": 1,
                            "success": True,
                        },
                    ],
                },
                "observation": {
                    "usage": {"prompt_tokens": 10},
                    "events": [
                        {"id": "turn-1", "type": "turn", "turn": 1},
                        {
                            "id": "tool-1",
                            "type": "tool",
                            "parent_id": "turn-1",
                            "turn": 1,
                        },
                        {"id": "orphan", "type": "generation", "parent_id": "missing"},
                    ],
                },
            }
        ],
    }


def test_five_levels_retain_metrics_orphans_and_saved_verdict():
    run = saved_run()
    before = deepcopy(run)
    view = aggregator().aggregate_benchmark(run)
    assert view.level == "benchmark"
    assert view.summary["missing_trials"] == 3
    assert view.summary["pass_rate_planned"] == 0
    assert view.summary["all_trials_pass_rate"] == 0
    assert view.summary["usage"]["cost_usd"] is None
    trial = view.trials[0]
    assert trial.level == "trial"
    assert trial.verdict == "INCONCLUSIVE"
    assert trial.task.level == "task"
    assert trial.task.metrics[0]["score"] is None
    turn = trial.task.turns[0]
    assert turn.level == "turn"
    assert turn.metrics[0]["name"] == "checkpoint"
    assert turn.steps[0].level == "step"
    assert turn.steps[0].metrics[0]["name"] == "diagnostic"
    assert trial.task.unbound_steps[0].event["id"] == "orphan"
    turn.steps[0].metrics[0]["score"] = 1
    assert run == before


def test_aggregation_rejects_duplicate_trial_without_inflating_success():
    run = saved_run()
    run["trials"].append(deepcopy(run["trials"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        aggregator().aggregate_benchmark(run)


def test_legacy_summary_keeps_old_unknown_groups_and_usage_shapes():
    run = saved_run()
    module = aggregator()
    summary = module.summarize(run["trials"], run["planned_case_ids"], 2)
    report = module.evidence_summary(run)
    assert summary["by_category"]["agent"]["trials"] == 1
    assert report["by_category"]["unknown"]["trials"] == 1
    assert summary["usage"]["input_tokens"] == 10
    assert report["usage"]["input_tokens"] == {
        "total": 10,
        "known_subtotal": 10,
        "known_trials": 1,
    }


def test_conflicting_turn_binding_and_unbound_metric_are_retained_as_unknown():
    run = saved_run()
    row = run["trials"][0]
    row["observation"]["events"][1]["turn"] = 2
    row["assessment"]["metrics"].append(
        {
            "name": "missing-node",
            "scope": "tool",
            "event_id": "absent",
            "score": None,
            "success": None,
        }
    )
    task = aggregator().aggregate_benchmark(run).trials[0].task
    assert task.turns[0].steps == []
    assert len(task.unbound_steps) == 2
    assert task.unbound_steps[0].metrics[0]["name"] == "diagnostic"
    assert task.unbound_metrics[0]["name"] == "missing-node"
