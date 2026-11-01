from copy import deepcopy

from eval_framework.benchmark.metrics import score_task
from eval_framework.benchmark.oracle import evaluate_oracle
from eval_framework.benchmark.runner import summarize


def example():
    task = {
        "id": "chain",
        "family": "chain",
        "category": "create_edit",
        "split": "dev",
        "prompt": "Write x",
        "followups": [],
        "fixtures": {"x": "old"},
        "oracle": {"expected_files": {"x": "new"}},
        "allowed_tools": ["write_file"],
        "required_tools": ["write_file"],
        "evaluation_level": "chain",
        "execution_mode": "agent",
        "checkpoints": [
            {
                "id": "first",
                "kind": "turn_files",
                "turn": 1,
                "expected_files": {"x": "new"},
                "required": True,
            }
        ],
    }
    observation = {
        "status": "completed",
        "evidence_complete": True,
        "before_files": {"x": "old"},
        "final_files": {"x": "new"},
        "turns": [{"input": "Write x", "output": "done", "snapshot": {"x": "wrong"}}],
        "events": [
            {
                "id": "t1",
                "type": "turn",
                "input": "Write x",
                "output": "done",
                "snapshot": {"x": "wrong"},
            },
            {
                "id": "w1",
                "type": "tool",
                "parent_id": "t1",
                "name": "write_file",
                "input": {"path": "x", "content": "new"},
                "output": "written",
                "execution_started": True,
            },
        ],
        "errors": [],
        "usage": {},
    }
    return task, observation


def test_correct_final_state_does_not_rescue_failed_required_turn():
    task, observation = example()
    assert score_task(task, observation)["verdict"] == "FAIL"


def test_missing_required_turn_evidence_is_not_pass():
    task, observation = example()
    observation["turns"][0].pop("snapshot")
    observation["events"][0].pop("snapshot")
    assert score_task(task, observation)["verdict"] == "INCONCLUSIVE"


def test_module_expected_error_is_checked_against_actual_tool_result():
    task, observation = example()
    task["oracle"]["module_results"] = [
        {"call": 1, "error": True, "output_contains": ["missing"]}
    ]
    assert evaluate_oracle(task, observation)["success"] is False
    observation["events"][1].update(
        is_error=True, tool_error=True, output="missing parameter"
    )
    assert evaluate_oracle(task, observation)["success"] is True


def test_summary_exposes_separate_module_and_agent_populations():
    records = []
    for level, kind, verdict in [
        ("module", "real_module", "PASS"),
        ("e2e", "real_agent", "FAIL"),
    ]:
        _, observation = example()
        observation["execution_kind"] = kind
        records.append(
            {
                "case_id": level,
                "trial": 1,
                "split": "dev",
                "category": "create_edit",
                "evaluation_level": level,
                "execution_mode": "module" if level == "module" else "agent",
                "assessment": {"verdict": verdict, "validity": "VALID", "metrics": []},
                "latency_seconds": 1,
                "observation": deepcopy(observation),
            }
        )
    result = summarize(records, ["module", "e2e"], 1)
    assert result["by_evaluation_level"]["module"]["verdicts"] == {"PASS": 1}
    assert result["by_evaluation_level"]["e2e"]["verdicts"] == {"FAIL": 1}
    assert result["mixed_execution_populations"] is True


def test_decision_oracle_checks_actual_model_call_arguments():
    task, observation = example()
    task["oracle"]["decision"] = {
        "acceptable_tools": ["write_file"],
        "arguments": {"path": "x", "content": "new"},
        "allow_no_tool": False,
        "max_calls": 1,
    }
    observation["events"].append(
        {
            "id": "g1",
            "type": "generation",
            "output": {
                "tool_calls": [
                    {
                        "name": "write_file",
                        "arguments": {"path": "x", "content": "wrong"},
                    }
                ]
            },
        }
    )
    assert evaluate_oracle(task, observation)["success"] is False
    observation["events"][-1]["output"]["tool_calls"][0]["arguments"]["content"] = "new"
    observation["events"][-1]["input"] = {
        "tools": [
            {
                "function": {
                    "name": "write_file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                    },
                }
            }
        ]
    }
    assert evaluate_oracle(task, observation)["success"] is True


def test_abstention_task_does_not_accept_an_unrequested_tool_call():
    task, observation = example()
    task["oracle"]["decision"] = {
        "acceptable_tools": [],
        "arguments": {},
        "allow_no_tool": True,
        "max_calls": 0,
    }
    observation["events"].append(
        {
            "id": "g1",
            "type": "generation",
            "output": {
                "tool_calls": [{"name": "read_file", "arguments": {"path": "x"}}]
            },
        }
    )
    assert evaluate_oracle(task, observation)["success"] is False


def test_model_decision_boolean_argument_does_not_accept_integer():
    task, observation = example()
    task["oracle"] = {
        "decision": {
            "acceptable_tools": ["list_dir"],
            "arguments": {"recursive": True},
            "max_calls": 1,
            "allow_no_tool": False,
        }
    }
    event = {
        "id": "g1",
        "type": "generation",
        "input": {
            "tools": [
                {
                    "function": {
                        "name": "list_dir",
                        "parameters": {
                            "type": "object",
                            "properties": {"recursive": {"type": "boolean"}},
                        },
                    }
                }
            ]
        },
        "output": {
            "tool_calls": [{"name": "list_dir", "arguments": {"recursive": True}}]
        },
    }
    observation["events"] = [event]
    observation["final_files"] = dict(task["fixtures"])
    assert evaluate_oracle(task, observation)["success"] is True
    event["output"]["tool_calls"][0]["arguments"]["recursive"] = 1
    assert evaluate_oracle(task, observation)["success"] is False


def test_missing_model_decision_is_not_interpreted_as_abstention():
    task, observation = example()
    task["execution_mode"] = "decision"
    observation["events"] = [{"id": "g1", "type": "generation", "output": {}}]
    result = score_task(task, observation)
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["metrics"] == []
