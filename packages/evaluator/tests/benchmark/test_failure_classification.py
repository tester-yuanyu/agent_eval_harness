from copy import deepcopy

import pytest

from .analysis_fixtures import run


@pytest.mark.parametrize(
    "name,expected",
    [
        ("unknown_tool", "unknown_tool"),
        ("decision_tool:0", "tool_selection_error"),
        ("decision_arguments:0", "invalid_arguments"),
        ("expected_file:x", "state_mismatch"),
        ("preserved_file:x", "workspace_policy_violation"),
        ("checkpoint:one", "checkpoint_violation"),
    ],
)
def test_failed_checks_classify_with_evidence_without_mutating(name, expected):
    from eval_framework.aggregator.failures import classify_failure

    trial = run()["trials"][-1]
    trial["assessment"]["checks"] = [{"name": name, "passed": False}]
    original = deepcopy(trial)
    result = classify_failure(trial)
    assert result["domain"] == "agent"
    assert result["primary"] == expected
    assert result["evidence_refs"] == ["/assessment/checks/0"]
    assert trial == original


def test_recovered_tool_error_and_judge_error_do_not_make_agent_failure():
    from eval_framework.aggregator.failures import classify_failure

    trial = run()["trials"][0]
    trial["observation"]["events"] = [
        {"type": "tool", "error": {"code": "UNKNOWN_TOOL"}}
    ]
    trial["assessment"]["metrics"] = [
        {"formal": False, "status": "ERROR", "name": "judge"}
    ]
    result = classify_failure(trial)
    assert result["primary"] is None
    assert result["domain"] is None
    assert {d["primary"] for d in result["diagnostics"]} == {
        "recovered_error",
        "judge_error",
    }


@pytest.mark.parametrize(
    "kind,expected",
    [("harness", "infrastructure"), ("scoring", "scoring"), (None, "unknown")],
)
def test_timeout_domain_requires_explicit_origin(kind, expected):
    from eval_framework.aggregator.failures import classify_failure

    trial = run()["trials"][-1]
    trial["assessment"].update(verdict="INVALID", validity="INVALID")
    trial["observation"]["errors"] = [{"code": "TIMEOUT", "kind": kind}]
    result = classify_failure(trial)
    assert result["domain"] == expected
    assert result["primary"] == "timeout"


def test_judge_error_does_not_explain_formal_failure():
    from eval_framework.aggregator.failures import classify_failure

    trial = run()["trials"][-1]
    trial["assessment"]["errors"] = [{"code": "JUDGE_ERROR", "kind": "scoring"}]
    result = classify_failure(trial)
    assert result["domain"] == "unknown"
    assert result["primary"] == "unknown"
