from __future__ import annotations

import pytest
from pydantic import ValidationError

from eval_framework.phase2_schemas import JudgeCaseSpec, JudgeDimensionSpec
from eval_framework.schemas import ExecutionSpec, OracleSpec, RunConfig


def test_run_config_rejects_non_positive_trials():
    with pytest.raises(ValidationError):
        RunConfig(trials_per_case=0)


def test_judge_case_rejects_duplicate_dimensions():
    dimension = JudgeDimensionSpec(name="clarity", weight=1, threshold=80)

    with pytest.raises(ValidationError):
        JudgeCaseSpec(
            rubric_id="semantic-response",
            rubric_version="1.0",
            dimensions=[dimension, dimension],
        )


def test_judge_dimension_rejects_out_of_range_threshold():
    with pytest.raises(ValidationError):
        JudgeDimensionSpec(name="clarity", weight=1, threshold=101)


def test_oracle_accepts_judge_but_execution_rejects_it():
    judge = {
        "rubric_id": "semantic-response",
        "rubric_version": "1.0",
        "dimensions": [{"name": "clarity", "weight": 1, "threshold": 80}],
        "reference_facts": {"outcome": "success"},
        "required": True,
    }
    oracle = OracleSpec.model_validate(
        {
            "evaluation": {
                "checks": [{"name": "response_consistent", "weight": 1}]
            },
            "judge": judge,
        }
    )

    assert oracle.judge is not None
    assert oracle.judge.reference_facts == {"outcome": "success"}
    with pytest.raises(ValidationError):
        ExecutionSpec.model_validate(
            {
                "user_input": "hello",
                "tool_profile": "read_only",
                "judge": judge,
            }
        )

