from __future__ import annotations

from collections import deque
from collections.abc import Iterable


class ScriptedJudgeClient:
    def __init__(self, responses: Iterable[object]) -> None:
        self.responses = deque(responses)
        self.requests = []

    def metadata(self):
        return {"provider": "scripted", "model": "judge-fixture"}

    def evaluate(self, request):
        self.requests.append(request)
        response = self.responses.popleft()
        if isinstance(response, BaseException):
            raise response
        return response

