from __future__ import annotations

import os

import pytest
from minimal_agent.runtime import OpenAIModelClient

from eval_framework import RunConfig, load_dataset, run_evaluation


@pytest.mark.openai_eval_smoke
@pytest.mark.skipif(
    os.getenv("RUN_OPENAI_EVAL_SMOKE") != "1",
    reason="set RUN_OPENAI_EVAL_SMOKE=1 to allow a paid API request",
)
def test_real_openai_module_smoke():
    dataset = load_dataset("datasets/fixtures/module_valid.jsonl")
    result = run_evaluation(
        dataset,
        RunConfig(run_mode="agent_benchmark"),
        lambda execution: OpenAIModelClient.from_env(
            timeout_seconds=execution.timeout_seconds
        ),
    )
    assert result.cases[0].execution_status == "COMPLETED"
