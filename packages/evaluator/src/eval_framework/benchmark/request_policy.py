"""模型请求的有界重试和批次熔断；不保存凭据或服务端错误正文。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime


class RequestCircuitOpen(RuntimeError):
    pass


def classify_error(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    code = str(body.get("type", body.get("code", ""))) if isinstance(body, dict) else ""
    if status in {401, 403, 404} or code in {
        "MissingSessionID",
        "model_not_found",
        "invalid_api_key",
        "unsupported_model",
    }:
        return "configuration"
    if status == 429:
        return "rate_limit"
    if (
        status in {408, 500, 502, 503, 504}
        or isinstance(exc, (TimeoutError, ConnectionError))
        or type(exc).__name__
        in {
            "APIConnectionError",
            "APITimeoutError",
            "ConnectTimeout",
            "ReadTimeout",
            "ConnectError",
        }
    ):
        return "transient"
    return "request"


class RequestPolicy:
    def __init__(self, retries: int = 1, *, sleep: Callable = time.sleep):
        if type(retries) is not int or not 0 <= retries <= 3:
            raise ValueError("request retries must be 0–3")
        self.retries, self.sleep = retries, sleep
        self.stopped = threading.Event()
        self.attempts: list[dict] = []
        self.model_requests = 0
        self._lock = threading.Lock()

    def record_model_request(self):
        with self._lock:
            self.model_requests += 1

    def call(self, request: Callable):
        for attempt in range(self.retries + 1):
            if self.stopped.is_set():
                raise RequestCircuitOpen("Batch stopped after a configuration error")
            started = time.monotonic()
            try:
                return request()
            except Exception as exc:
                kind = classify_error(exc)
                with self._lock:
                    self.attempts.append(
                        {
                            "at": datetime.now(UTC).isoformat(),
                            "seconds": time.monotonic() - started,
                            "failure_kind": kind,
                            "error_type": type(exc).__name__,
                            "attempt": attempt + 1,
                        }
                    )
                if kind == "configuration":
                    self.stopped.set()
                if kind not in {"transient", "rate_limit"} or attempt == self.retries:
                    raise
                delay = 0.5 * 2**attempt
                response = getattr(exc, "response", None)
                try:
                    delay = max(delay, float(response.headers.get("retry-after", 0)))
                except (AttributeError, TypeError, ValueError):
                    pass
                # Do not violate a long Retry-After by retrying early.
                if delay > 60:
                    raise
                self.sleep(delay)
