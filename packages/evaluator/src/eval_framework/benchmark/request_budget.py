"""Run-local request reservations; adapters reserve before forwarding to a model."""

from threading import Lock


class RequestBudget:
    def __init__(self, limit: int | None):
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError("max_model_requests must be a positive integer")
        self.limit = limit
        self.used = 0
        self._lock = Lock()

    def reserve(self) -> None:
        with self._lock:
            if self.limit is not None and self.used >= self.limit:
                raise RuntimeError("MODEL_REQUEST_BUDGET_EXHAUSTED")
            self.used += 1
