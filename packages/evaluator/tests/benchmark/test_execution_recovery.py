import json
from copy import deepcopy

import pytest
from eval_framework.benchmark.runner import digest, save_json


def source_run(tmp_path):
    identity = {"case_ids": ["a", "b"], "repeats": 2}
    rows = []
    for case in ["a", "b"]:
        for trial in [1, 2]:
            retry = case == "b" and trial == 2
            rows.append(
                {
                    "identity_hash": digest(identity),
                    "case_id": case,
                    "trial": trial,
                    "assessment": {
                        "verdict": "INVALID" if retry else "FAIL",
                        "validity": "INVALID" if retry else "VALID",
                    },
                    "observation": {
                        "errors": [{"code": "APIConnectionError"}] if retry else []
                    },
                }
            )
    result = {
        "identity": identity,
        "identity_hash": digest(identity),
        "planned_case_ids": ["a", "b"],
        "trials_per_case": 2,
        "trials": rows,
        "run_id": "old",
    }
    save_json(tmp_path / "source/results.json", result)
    return result


def test_recovery_only_retries_transient_invalid_preserves_valid_fail(tmp_path):
    from eval_framework.benchmark.execution_recovery import prepare_recovery

    result = source_run(tmp_path)
    original = (tmp_path / "source/results.json").read_bytes()
    manifest = prepare_recovery(tmp_path / "source", tmp_path / "retry")
    assert manifest["retry_trials"] == [{"case_id": "b", "trial": 2}]
    assert len(manifest["retained_trials"]) == 3
    rows = [
        json.loads(p.read_text())
        for p in sorted((tmp_path / "retry/trials").glob("*.json"))
    ]
    assert rows == result["trials"][:3]
    assert (tmp_path / "source/results.json").read_bytes() == original
    with pytest.raises(ValueError, match="empty"):
        prepare_recovery(tmp_path / "source", tmp_path / "retry")


def test_recovery_rejects_bad_identity_and_does_not_retry_config_failure(tmp_path):
    from eval_framework.benchmark.execution_recovery import prepare_recovery

    result = source_run(tmp_path)
    result["trials"][-1]["observation"]["errors"] = [{"code": "MissingSessionID"}]
    save_json(tmp_path / "source/results.json", result)
    assert (
        prepare_recovery(tmp_path / "source", tmp_path / "no-retry")["retry_trials"]
        == []
    )
    result["trials"][0]["identity_hash"] = "bad"
    save_json(tmp_path / "source/results.json", result)
    with pytest.raises(ValueError, match="identity"):
        prepare_recovery(tmp_path / "source", tmp_path / "bad")


def test_runner_seeded_epoch_is_not_executed(tmp_path, monkeypatch):
    from pathlib import Path

    from eval_framework.benchmark.execution_recovery import prepare_recovery
    from eval_framework.benchmark.runner import run_benchmark
    from eval_framework.benchmark.scorers import reference_runner
    from eval_framework.benchmark.tasks import load_tasks

    tasks = load_tasks(
        Path(__file__).resolve().parents[4] / "data/benchmarks/file-tools-v2"
    )[:1]
    config = dict(
        dataset={"id": "test"}, config={}, repeats=2, offline=True, concurrency=1
    )
    first = run_benchmark(tasks, output=tmp_path / "source", **config)
    # Simulate an interrupted transport result; the other epoch stays valid.
    saved = deepcopy(first)
    row = saved["trials"][1]
    row["assessment"].update(verdict="INVALID", validity="INVALID")
    row["observation"]["errors"] = [{"code": "APIConnectionError"}]
    save_json(tmp_path / "source/results.json", saved)
    prepare_recovery(tmp_path / "source", tmp_path / "retry")
    calls = []
    original = reference_runner.reference_observation

    def observe(task):
        calls.append(task["id"])
        return original(task)

    monkeypatch.setattr(reference_runner, "reference_observation", observe)
    recovered = run_benchmark(tasks, output=tmp_path / "retry", **config)
    assert calls == [tasks[0]["id"]]
    assert recovered["trials"][0] == first["trials"][0]
    assert recovered["provenance"]["operation"] == "retry_execution"


@pytest.mark.parametrize(
    "code,expected",
    [("AuthenticationError", "configuration"), ("APIConnectionError", "transient")],
)
def test_full_worker_error_projection_is_classified(code, expected):
    from eval_framework.benchmark.execution_recovery import observation_failure_kind

    observation = {"errors": [{"code": "WORKER_ERROR", "message": f"{code}: detail"}]}
    assert observation_failure_kind(observation) == expected
    assert (
        observation_failure_kind(
            {
                "errors": [
                    {
                        "code": "WORKER_ERROR",
                        "message": f"RuntimeError: tool said {code}",
                    }
                ]
            }
        )
        is None
    )


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Connection error.", "transient"),
        ("Error code: 401 - credentials rejected", "configuration"),
        ("Error code: 429 - throttled", "transient"),
    ],
)
def test_wrapped_model_failure_uses_native_evidence(message, expected):
    from eval_framework.benchmark.execution_recovery import observation_failure_kind

    observation = {
        "errors": [
            {
                "code": "WORKER_ERROR",
                "message": "ModelInvocationError: intent model invocation failed",
            }
        ],
        "events": [
            {"type": "generation", "source": "inspect_ai.ModelEvent", "error": message}
        ],
    }
    assert observation_failure_kind(observation) == expected
    observation["events"][0]["source"] = "agent_tool"
    assert observation_failure_kind(observation) is None


def test_missing_session_native_error_is_configuration_failure():
    from eval_framework.benchmark.execution_recovery import observation_failure_kind

    assert (
        observation_failure_kind(
            {
                "events": [
                    {
                        "type": "generation",
                        "source": "inspect_ai.ModelEvent",
                        "error": (
                            "Error code: 400 - {'error': {'type': 'MissingSessionID'}}"
                        ),
                    }
                ]
            }
        )
        == "configuration"
    )


def test_retained_native_evidence_is_bound_and_copied(tmp_path):
    import hashlib

    from eval_framework.benchmark.execution_recovery import prepare_recovery

    result = source_run(tmp_path)
    evidence = tmp_path / "source/evidence/a.json"
    evidence.parent.mkdir()
    evidence.write_bytes(b'{"evidence":true}\n')
    result["trials"][0]["observation"]["native_evidence"] = {
        "path": "evidence/a.json",
        "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
    }
    save_json(tmp_path / "source/results.json", result)
    prepare_recovery(tmp_path / "source", tmp_path / "retry")
    assert (tmp_path / "retry/evidence/a.json").read_bytes() == evidence.read_bytes()
    evidence.write_bytes(b"changed")
    with pytest.raises(ValueError, match="evidence Hash"):
        prepare_recovery(tmp_path / "source", tmp_path / "bad")
