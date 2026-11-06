import json

import pytest
from pydantic import ValidationError


def test_task_execution_projection_separates_private_expectations():
    from eval_contracts.benchmark import TaskSpec

    task = TaskSpec.model_validate({
        "task_id": "edit-1",
        "prompt": "Update the file",
        "initial_state": {"files": {"a.txt": "before"}},
        "tools": ["write_file"],
        "expected_delta": {"files": {"a.txt": "PRIVATE_DELTA"}},
        "reference_answer": "PRIVATE_REFERENCE",
        "oracle": {"contains": "PRIVATE_ORACLE"},
        "checkpoints": [{"expected": "PRIVATE_CHECKPOINT"}],
    })
    execution = task.execution_input()
    assert execution["initial_state"] == {"files": {"a.txt": "before"}}
    assert "PRIVATE" not in json.dumps(execution)
    execution["initial_state"]["files"]["a.txt"] = "mutated"
    assert task.initial_state["files"]["a.txt"] == "before"


def test_generic_task_rejects_unknown_fields_and_invalid_limits():
    from eval_contracts.benchmark import TaskSpec

    with pytest.raises(ValidationError):
        TaskSpec(task_id="x", prompt="hello", hidden_answer="wrong field")
    for value in (0, -1, True):
        with pytest.raises(ValidationError):
            TaskSpec(task_id="x", prompt="hello", max_steps=value)
