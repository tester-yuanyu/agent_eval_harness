from copy import deepcopy

from eval_framework.benchmark.report_insights import latency_details


def row(case="a", mode="agent", passed=True):
    return {
        "case_id": case,
        "trial": 1,
        "execution_mode": mode,
        "latency_seconds": 3,
        "assessment": {"verdict": "PASS" if passed else "FAIL", "metrics": []},
        "observation": {
            "execution_kind": "real_model_agent"
            if mode == "agent"
            else "deterministic_environment_check",
            "events": [],
            "turns": [],
        },
    }


def event(judge=False):
    return {
        "type": "generation",
        "is_judge": judge,
        "start_time": "2026-11-11T00:00:00+00:00",
        "end_time": "2026-11-11T00:00:01+00:00",
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }


def test_agent_latency_excludes_judge_calls():
    r = row()
    r["observation"]["events"] = [event(), event(True), event(True)]
    original = deepcopy(r)
    assert latency_details([r])[0]["calls"] == 1
    assert latency_details([r])[0]["model_seconds"] == 1
    assert r == original


def test_execution_groups_and_usage_not_applicable():
    from eval_framework.benchmark.report_evaluation import evaluation_summary

    a, b = row(), row("b", "module")
    a["observation"]["events"] = [event(), event(True)]
    summary = evaluation_summary({"trials": [a, b]}, {})
    assert summary["groups"]["agent"]["passed"] == 1
    assert summary["groups"]["deterministic"]["trials"] == 1
    assert summary["usage"]["agent"]["calls"] == 1
    assert summary["usage"]["judge"]["calls"] == 1
    assert summary["usage"]["agent"]["known_total_tokens"] == 6
    assert summary["deterministic_model_usage"] == "NOT_APPLICABLE"


def test_expected_failure_is_explained_without_rescoring():
    from eval_framework.benchmark.report_evaluation import evaluation_summary

    r = row()
    r["assessment"]["metrics"] = [
        {
            "name": "recovery_appropriateness",
            "status": "SCORED",
            "score": 0.2,
            "judge_repeat": 1,
        }
    ]
    tasks = {
        "a": {
            "plan": {"fault": "tool_error"},
            "oracle": {
                "checks": [
                    {
                        "actual": "agent_result.status",
                        "op": "equals",
                        "expected": "FAILED",
                    }
                ]
            },
        }
    }
    original = deepcopy(r)
    result = evaluation_summary({"trials": [r]}, tasks)
    assert result["recovery_context"]["expected_failure_cases"] == 1
    assert result["recovery_context"]["scored_items"] == 1
    assert r == original
