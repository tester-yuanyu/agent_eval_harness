"""Opt-in paid smoke test for the real DeepSeek Judge boundary."""

from __future__ import annotations

import os

import pytest

from eval_framework.judges.inspect import InspectJudgeClient
from eval_framework.phase2_schemas import JudgeDimensionSpec, JudgeRequest

pytestmark = [
    pytest.mark.deepseek_judge_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_DEEPSEEK_JUDGE_SMOKE") != "1",
        reason="set RUN_DEEPSEEK_JUDGE_SMOKE=1 to run the paid DeepSeek smoke test",
    ),
]


def test_real_deepseek_judge_returns_declared_dimension() -> None:
    client = InspectJudgeClient.from_env(timeout_seconds=30)
    result = client.evaluate(
        JudgeRequest(
            user_input="Answer with one concise sentence: what is 2 + 2?",
            final_response="2 + 2 equals 4.",
            dimensions=[
                JudgeDimensionSpec(name="clarity", weight=1, threshold=70)
            ],
            dimension_instructions={
                "clarity": "Score whether the response is direct and unambiguous."
            },
            rubric_id="semantic-response",
            rubric_version="1.0",
            prompt_version="judge-prompt-v1",
        )
    )

    dimensions = result.get("dimensions", [])
    assert [item["name"] for item in dimensions] == ["clarity"]
    assert 0 <= dimensions[0]["score"] <= 100
