import json
from pathlib import Path

from eval_framework.benchmark.tasks import execution_task, load_tasks

ROOT = Path(__file__).resolve().parents[4]


def test_all_frozen_file_tasks_keep_legacy_execution_projection():
    from eval_framework.benchmark.schema import task_spec_from_legacy

    count = 0
    for name in ("file-tools-v1", "file-tools-v2", "model-decisions-v1"):
        for task in load_tasks(ROOT / "data" / "benchmarks" / name / "tasks.jsonl"):
            spec = task_spec_from_legacy(task)
            projected = execution_task(task)
            expected = {key: task[key] for key in (
                "id", "prompt", "followups", "fixtures", "allowed_tools", "max_steps"
            )}
            if task.get("execution_mode") == "module":
                expected["module_calls"] = task["module_calls"]
            if task.get("execution_mode") == "decision":
                expected["decision_context"] = task["decision_context"]
            assert projected == expected
            assert spec.oracle == task["oracle"]
            assert spec.task_id == task["id"]
            assert "oracle" not in spec.execution_input()
            assert spec.initial_state == {"files": task["fixtures"]}
            assert json.dumps(projected) == json.dumps(expected)
            count += 1
    assert count > 300
