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


def test_offline_runner_uses_native_epochs_and_resumes_without_new_logs(tmp_path):
    from pathlib import Path

    from inspect_ai.log import list_eval_logs, read_eval_log

    from eval_framework.benchmark.runner import run_benchmark
    from eval_framework.benchmark.tasks import load_tasks

    root = Path(__file__).resolve().parents[4]
    tasks = load_tasks(root / "data/benchmarks/file-tools-v2")[:1]
    arguments = dict(
        dataset={"identity": "offline-test"},
        config={},
        output=tmp_path,
        repeats=2,
        concurrency=1,
        offline=True,
    )
    first = run_benchmark(tasks, **arguments)
    logs = list_eval_logs(str(tmp_path / "inspect"))
    assert len(logs) == 1
    log = read_eval_log(logs[0].name)
    assert {(s.id, s.epoch) for s in log.samples} == {
        (tasks[0]["id"], 1),
        (tasks[0]["id"], 2),
    }
    assert log.eval.config.epochs == 2
    assert first["summary"]["completed_trials"] == 2
    assert run_benchmark(tasks, **arguments) == first
    assert len(list_eval_logs(str(tmp_path / "inspect"))) == 1
    with pytest.raises(ValueError, match="identity changed"):
        run_benchmark(tasks, **{**arguments, "config": {"variant": "changed"}})
    (tmp_path / "results.json").unlink()
    for path in (tmp_path / "trials").glob("*.json"):
        path.unlink()
    resumed = run_benchmark(tasks, **arguments)
    assert resumed["trials"] == first["trials"]
    assert len(list_eval_logs(str(tmp_path / "inspect"))) == 1


@pytest.mark.parametrize(
    "corrupt", ["duplicate", "trial", "identity", "row_identity", "inspect", "backend"]
)
def test_comparison_rejects_corrupt_rows_and_incompatible_execution(corrupt):
    from copy import deepcopy

    from eval_framework.benchmark.runner import digest

    left = {
        "identity": {"dataset": "a", "scoring_version": "v1", "inspect_ai": "0.3.280"},
        "planned_case_ids": ["a"],
        "trials_per_case": 1,
        "trials": [trial("a", "PASS")],
        "execution_backend": "inspect_ai",
    }
    left["identity_hash"] = digest(left["identity"])
    left["trials"][0]["identity_hash"] = left["identity_hash"]
    right = deepcopy(left)
    if corrupt == "duplicate":
        right["trials"].append(deepcopy(right["trials"][0]))
    elif corrupt == "trial":
        right["trials"][0]["trial"] = True
    elif corrupt == "identity":
        right["identity_hash"] = "different"
    elif corrupt == "row_identity":
        right["trials"][0]["identity_hash"] = "different"
    elif corrupt == "inspect":
        del right["identity"]["inspect_ai"]
    else:
        right["execution_backend"] = "other"
    with pytest.raises(ValueError):
        compare_runs(left, right)


@pytest.mark.parametrize("error_type", ["source", "environment"])
def test_identity_drift_cannot_finalize_a_run(tmp_path, monkeypatch, error_type):
    from pathlib import Path

    from eval_framework.benchmark import module_runtime
    from eval_framework.benchmark.inspect_docker import SandboxEnvironmentChanged
    from eval_framework.benchmark.runner import RuntimeIdentityChanged, run_benchmark
    from eval_framework.benchmark.tasks import load_tasks

    root = Path(__file__).resolve().parents[4]
    source = Path("/Users/yuanyu/Desktop/nanobot")
    if not source.exists():
        pytest.skip("optional local nanobot source identity")
    task = next(
        t
        for t in load_tasks(root / "data/benchmarks/file-tools-v2")
        if t.get("execution_mode") == "module"
    )

    async def changed(*args, **kwargs):
        raise (
            RuntimeIdentityChanged
            if error_type == "source"
            else SandboxEnvironmentChanged
        )("drift")

    monkeypatch.setattr(module_runtime, "execute_module_task", changed)
    with pytest.raises(RuntimeIdentityChanged, match="new run directory"):
        run_benchmark(
            [task],
            dataset={"identity": "drift-test"},
            config={"nanobot_root": str(source), "model": "mockllm/model"},
            output=tmp_path,
            concurrency=1,
        )
    assert not (tmp_path / "results.json").exists()
    assert list((tmp_path / "inspect").glob("*.eval"))
