import copy
from pathlib import Path

from eval_framework.benchmark.oracle import evaluate_oracle, reference_observation
from eval_framework.benchmark.tasks import load_tasks

DATASET = Path(__file__).resolve().parents[4] / "data/benchmarks/file-tools-v1"


def test_independent_reference_executor_solves_every_frozen_case():
    for task in load_tasks(DATASET):
        verdict = evaluate_oracle(task, reference_observation(task))
        assert verdict["success"], (task["id"], verdict)


def test_reference_executor_does_not_read_oracle_expected_files():
    task = next(t for t in load_tasks(DATASET) if t["category"] == "create_edit")
    correct = reference_observation(task)
    mutated = copy.deepcopy(task)
    mutated["oracle"] = {"expected_files": {"poison.txt": "LEAK"}}
    assert reference_observation(mutated)["final_files"] == correct["final_files"]


def test_unrequested_write_and_fixture_mutation_fail_policy():
    task = load_tasks(DATASET)[0]
    observation = reference_observation(task)
    observation["final_files"]["unrequested.txt"] = "oops"
    verdict = evaluate_oracle(task, observation)
    assert not verdict["success"]
    assert verdict["violations"]


def test_evidence_missing_or_timeout_never_passes():
    task = load_tasks(DATASET)[0]
    for observation in ({}, {"status": "timeout", "final_files": task["fixtures"]}):
        assert not evaluate_oracle(task, observation)["success"]


def test_changed_initial_state_fails_even_with_correct_final_files():
    task = load_tasks(DATASET)[0]
    observation = reference_observation(task)
    observation["before_files"] = {}
    assert not evaluate_oracle(task, observation)["success"]


def test_skipped_followups_cannot_pass():
    task = next(t for t in load_tasks(DATASET) if t["followups"])
    observation = reference_observation(task)
    observation["turns"] = observation["turns"][:1]
    assert not evaluate_oracle(task, observation)["success"]


def test_response_token_cannot_be_a_prefix_of_a_wrong_answer():
    task = next(
        t for t in load_tasks(DATASET) if t["family"] == "read_search/active_count"
    )
    observation = reference_observation(task)
    observation["turns"][-1]["output"] += "0"
    assert not evaluate_oracle(task, observation)["success"]
