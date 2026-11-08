"""Saved Judge prompts need not have the Agent's structured chat input shape."""

from copy import deepcopy

import pytest
from eval_framework.benchmark.report_insights import diagnose


@pytest.mark.parametrize(
    "request_value", ["saved judge prompt", None, ["legacy prompt"]]
)
def test_saved_judge_input_does_not_crash_or_invent_context_findings(request_value):
    row = {
        "assessment": {"verdict": "FAIL", "metrics": []},
        "observation": {
            "events": [
                {
                    "id": "judge-1",
                    "type": "generation",
                    "name": "deepeval_response_judge",
                    "input": request_value,
                    "output": '{"score": 0.5}',
                }
            ]
        },
    }
    original = deepcopy(row)
    assert diagnose(row, {}) == []
    assert row == original
