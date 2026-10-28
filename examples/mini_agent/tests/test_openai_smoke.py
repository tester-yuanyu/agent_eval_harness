import os

import pytest

from minimal_agent.contracts.agent import IntentResult
from minimal_agent.runtime.openai_client import OpenAIModelClient


@pytest.mark.openai_smoke
def test_real_openai_intent_smoke() -> None:
    if os.getenv("RUN_OPENAI_SMOKE") != "1":
        pytest.skip("set RUN_OPENAI_SMOKE=1 to permit a paid API request")

    result = OpenAIModelClient.from_env().classify_intent(
        "Query fixture information in the test environment."
    )

    assert isinstance(result, IntentResult)
