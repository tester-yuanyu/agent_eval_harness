import pytest
from eval_framework.benchmark.request_policy import (
    RequestCircuitOpen,
    RequestPolicy,
    classify_error,
)


class Failure(Exception):
    def __init__(self, status=None, body=None):
        self.status_code = status
        self.body = body


def test_configuration_error_opens_circuit_without_retries():
    calls = []
    policy = RequestPolicy(retries=2, sleep=lambda _: None)

    def request():
        calls.append(1)
        raise Failure(401)

    with pytest.raises(Failure):
        policy.call(request)
    with pytest.raises(RequestCircuitOpen):
        policy.call(request)
    assert len(calls) == 1


def test_transient_retry_is_bounded_and_preserves_attempts():
    calls = []
    policy = RequestPolicy(retries=2, sleep=lambda _: None)

    def request():
        calls.append(1)
        raise TimeoutError()

    with pytest.raises(TimeoutError):
        policy.call(request)
    assert len(calls) == 3
    assert len(policy.attempts) == 3
    assert all(a["failure_kind"] == "transient" for a in policy.attempts)


def test_case_request_error_does_not_open_global_circuit():
    assert (
        classify_error(Failure(400, {"code": "context_length_exceeded"})) == "request"
    )
    assert classify_error(Failure(400, {"type": "MissingSessionID"})) == "configuration"
