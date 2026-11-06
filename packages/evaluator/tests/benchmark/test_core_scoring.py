"""Scoring tests mutate real evidence shapes rather than trusting verdict claims."""

import copy
import importlib.util

import pytest


def case():
    task = {
        "id": "case",
        "contract_version": "nanobot-core-task-v1",
        "family": "memory_history_integrity",
        "split": "dev",
        "component": "memory",
        "description": "read",
        "fixtures": {},
        "settings": {},
        "operations": [{"id": "r", "operation": "memory.read_long", "input": {}}],
        "oracle": {
            "assertions": [
                {"event": "r", "path": ["output"], "kind": "equals", "value": ""}
            ]
        },
    }
    obs = {
        "status": "completed",
        "execution_kind": "real_core_module",
        "errors": [],
        "usage": {},
        "events": [
            {
                "id": "r",
                "type": "module",
                "operation": "memory.read_long",
                "input": {},
                "output": "",
                "error": None,
                "start_time": 1.0,
                "end_time": 2.0,
                "incomplete": False,
            }
        ],
        "before_files": {},
        "final_files": {},
        "session_files": {},
        "evidence_complete": True,
        "runtime_identity": {"source_digest": "test-source"},
    }
    return task, obs


def test_scoring_implementation_exists():
    assert importlib.util.find_spec("eval_framework.benchmark.core_scoring") is not None


def test_private_oracle_controls_deepeval_verdict():
    from deepeval.metrics import BaseMetric

    from eval_framework.benchmark.core_scoring import (
        CoreAssertionsMetric,
        score_core_task,
    )

    assert issubclass(CoreAssertionsMetric, BaseMetric)
    task, obs = case()
    assert score_core_task(task, obs)["verdict"] == "PASS"
    obs["events"][0]["output"] = "wrong"
    result = score_core_task(task, obs)
    assert result["validity"] == "VALID" and result["verdict"] == "FAIL"
    assert result["metrics"][0]["score"] == 0


@pytest.mark.parametrize(
    "mutate",
    [
        lambda o: o.pop("session_files"),
        lambda o: o.update(evidence_complete=False),
        lambda o: o.update(events=[]),
        lambda o: o["events"].append(copy.deepcopy(o["events"][0])),
        lambda o: o["events"][0].update(incomplete=True),
        lambda o: o["events"][0].pop("output"),
        lambda o: o["events"][0].update(input={"extra": 1}),
        lambda o: o["events"][0].update(end_time=0),
        lambda o: o.update(runtime_identity={}),
        lambda o: o.update(before_files={"unexpected": "secret"}),
        lambda o: o.update(final_files={"../escape": "bad"}),
    ],
)
def test_missing_or_misbound_evidence_never_passes(mutate):
    from eval_framework.benchmark.core_scoring import score_core_task

    task, obs = case()
    mutate(obs)
    assert score_core_task(task, obs)["verdict"] in {"INVALID", "INCONCLUSIVE"}


def test_fatal_error_is_invalid_and_unexpected_step_error_is_fail():
    from eval_framework.benchmark.core_scoring import score_core_task

    task, obs = case()
    obs["events"][0].update(
        output=None, error={"type": "RuntimeError", "message": "boom"}
    )
    assert score_core_task(task, obs)["verdict"] == "FAIL"
    task["oracle"]["assertions"] = [
        {
            "event": "r",
            "path": ["error", "type"],
            "kind": "equals",
            "value": "RuntimeError",
        }
    ]
    assert score_core_task(task, obs)["verdict"] == "PASS"
    obs.update(status="error", errors=[{"type": "RuntimeError", "message": "fatal"}])
    assert score_core_task(task, obs)["verdict"] == "INVALID"


def test_missing_null_path_and_persisted_evidence_are_not_fabricated():
    from eval_framework.benchmark.core_scoring import score_core_task

    task, obs = case()
    task["oracle"]["assertions"].append(
        {
            "scope": "session_files",
            "path": ["sessions/missing.jsonl"],
            "kind": "equals",
            "value": None,
        }
    )
    assert score_core_task(task, obs)["verdict"] == "FAIL"


def test_session_persistence_requires_independent_file_content():
    from eval_framework.benchmark.core_scoring import score_core_task

    task, obs = case()
    task["oracle"]["assertions"].append(
        {
            "scope": "session_files",
            "path": [],
            "kind": "any_file_contains",
            "value": "persisted-marker",
        }
    )
    assert score_core_task(task, obs)["verdict"] == "FAIL"
    obs["session_files"] = {
        "sessions/namespace/encoded.jsonl": '{"content":"persisted-marker"}\n'
    }
    assert score_core_task(task, obs)["verdict"] == "PASS"


def test_session_persistence_cannot_be_satisfied_by_request_or_config_files():
    from eval_framework.benchmark.core_scoring import score_core_task

    task, obs = case()
    task["oracle"]["assertions"].append(
        {
            "scope": "session_files",
            "path": [],
            "kind": "any_file_contains",
            "value": "persisted-marker",
        }
    )
    obs["session_files"] = {
        "request.json": '{"input":"persisted-marker"}',
        "config.json": '{"text":"persisted-marker"}',
        "sessions/namespace/lock.txt": "persisted-marker",
    }
    assert score_core_task(task, obs)["verdict"] == "FAIL"
