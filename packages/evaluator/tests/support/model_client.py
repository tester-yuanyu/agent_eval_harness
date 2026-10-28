"""Deterministic model client used only by evaluator self-tests."""

from collections import deque
from collections.abc import Iterable

from minimal_agent.contracts.agent import ToolLoopRequest
from minimal_agent.runtime.model_client import ScriptExhaustedError


class DeterministicModelClient:
    def __init__(self, responses: Iterable[object]) -> None:
        self._responses = deque(responses)

    def classify_intent(self, user_input: str) -> object:
        del user_input
        return self._next()

    def next_tool_step(self, request: ToolLoopRequest) -> object:
        del request
        return self._next()

    def metadata(self) -> dict[str, str]:
        return {"model": "deterministic-test-client"}

    def _next(self) -> object:
        if not self._responses:
            raise ScriptExhaustedError("test model responses are exhausted")
        response = self._responses.popleft()
        if isinstance(response, BaseException):
            raise response
        return response
