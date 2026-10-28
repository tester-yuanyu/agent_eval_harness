"""Versioned, injectable semantic Judge orchestration."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from time import monotonic
from typing import Any, Protocol, runtime_checkable

from pydantic import Field, ValidationError

from .phase2_schemas import (
    JudgeAttempt,
    JudgeCaseSpec,
    JudgeDimensionResult,
    JudgeRequest,
    JudgeResult,
    JudgeRubric,
    JudgeRunConfig,
)
from .schema_base import StrictModel
from .schemas import AssertionResult, CaseResult, EvalCase, QualityConclusion

_SECRET_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


class JudgeInvocationError(RuntimeError):
    def __init__(self, message: str, *, temporary: bool = False) -> None:
        super().__init__(message)
        self.temporary = temporary


class JudgeTimeoutError(JudgeInvocationError):
    def __init__(self, message: str) -> None:
        super().__init__(message, temporary=True)


class JudgeOutputError(ValueError):
    pass


@runtime_checkable
class JudgeClient(Protocol):
    def evaluate(self, request: JudgeRequest) -> object: ...

    def metadata(self) -> dict[str, Any]: ...


class _CandidateDimension(StrictModel):
    name: str
    score: float = Field(ge=0, le=100)
    reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class _Candidate(StrictModel):
    dimensions: list[_CandidateDimension]
    token_usage: dict[str, int] = Field(default_factory=dict)


def load_judge_rubric(path: str | Path) -> JudgeRubric:
    return JudgeRubric.model_validate_json(Path(path).read_bytes())


def validate_judge_case_spec(spec: JudgeCaseSpec, rubric: JudgeRubric) -> None:
    _validate_rubric(spec, rubric)


def evaluate_trial_with_judge(
    case: EvalCase,
    result: CaseResult,
    config: JudgeRunConfig,
    client: JudgeClient,
    rubric: JudgeRubric,
) -> JudgeResult:
    spec = case.oracle.judge
    if spec is None or not config.enabled:
        return JudgeResult(status="NOT_APPLICABLE")
    _validate_rubric(spec, rubric)
    request = _build_request(case, result, spec, rubric)
    metadata = client.metadata()
    attempts: list[JudgeAttempt] = []
    total_started = monotonic()
    for number in range(1, config.max_retries + 2):
        started = monotonic()
        try:
            candidate = _Candidate.model_validate(client.evaluate(request))
            attempt = JudgeAttempt(
                attempt=number,
                status="COMPLETED",
                latency_ms=round((monotonic() - started) * 1000),
            )
            attempts.append(attempt)
            dimensions = _score_dimensions(spec, candidate)
            weighted = sum(
                Decimal(str(item.score)) * Decimal(str(dimension.weight))
                for item, dimension in zip(dimensions, spec.dimensions, strict=True)
            )
            total_weight = sum(
                Decimal(str(dimension.weight)) for dimension in spec.dimensions
            )
            score = (weighted / total_weight).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            return JudgeResult(
                status="COMPLETED",
                model=str(metadata.get("model", "unknown")),
                prompt_version=rubric.prompt_version,
                rubric_id=rubric.rubric_id,
                rubric_version=rubric.version,
                output_schema_version=rubric.output_schema_version,
                dimensions=dimensions,
                score=float(score),
                passed=all(item.passed for item in dimensions),
                attempts=attempts,
                latency_ms=round((monotonic() - total_started) * 1000),
                token_usage=candidate.token_usage,
            )
        except JudgeTimeoutError as exc:
            attempts.append(_failed_attempt(number, "MODEL_TIMEOUT", started, exc))
            if number <= config.max_retries:
                continue
            return _failed_result(
                "MODEL_TIMEOUT", metadata, rubric, attempts, total_started, exc
            )
        except JudgeInvocationError as exc:
            attempts.append(
                _failed_attempt(number, "MODEL_INVOCATION_ERROR", started, exc)
            )
            if exc.temporary and number <= config.max_retries:
                continue
            return _failed_result(
                "MODEL_INVOCATION_ERROR",
                metadata,
                rubric,
                attempts,
                total_started,
                exc,
            )
        except (ValidationError, ValueError, TypeError) as exc:
            attempts.append(
                _failed_attempt(number, "MODEL_OUTPUT_ERROR", started, exc)
            )
            return _failed_result(
                "MODEL_OUTPUT_ERROR", metadata, rubric, attempts, total_started, exc
            )
    raise AssertionError("unreachable")


def resolve_quality_conclusion(
    deterministic: QualityConclusion,
    assertions: Sequence[AssertionResult],
    judge_spec: JudgeCaseSpec | None,
    judge: JudgeResult | None,
) -> QualityConclusion:
    if deterministic == "FAIL" or any(
        item.critical and item.passed is False for item in assertions
    ):
        return "FAIL"
    if judge_spec is None or not judge_spec.required:
        return deterministic
    if judge is None or judge.status != "COMPLETED":
        return "INCONCLUSIVE"
    return "PASS" if judge.passed else "FAIL"


def _validate_rubric(spec: JudgeCaseSpec, rubric: JudgeRubric) -> None:
    if (spec.rubric_id, spec.rubric_version) != (
        rubric.rubric_id,
        rubric.version,
    ):
        raise ValueError("case Judge rubric identity does not match loaded rubric")
    available = {item.name for item in rubric.dimensions}
    unknown = [item.name for item in spec.dimensions if item.name not in available]
    if unknown:
        raise ValueError(f"case references unknown rubric dimensions: {unknown}")


def _build_request(
    case: EvalCase,
    result: CaseResult,
    spec: JudgeCaseSpec,
    rubric: JudgeRubric,
) -> JudgeRequest:
    final_response = ""
    if result.turn_results:
        final_response = str(result.turn_results[-1].get("final_response") or "")
    tool_summaries = [
        _redact(
            {
                "name": call.get("name"),
                "status": call.get("status"),
                "output": call.get("output"),
                "error": call.get("error"),
            }
        )
        for call in result.tool_calls
    ]
    instructions_by_dimension = {
        dimension.name: dimension.instruction for dimension in rubric.dimensions
    }
    return JudgeRequest(
        user_input=case.execution.user_input[: rubric.max_text_chars],
        final_response=final_response[: rubric.max_text_chars],
        tool_result_summaries=tool_summaries,
        reference_facts=_redact(spec.reference_facts),
        dimensions=spec.dimensions,
        dimension_instructions={
            dimension.name: instructions_by_dimension[dimension.name]
            for dimension in spec.dimensions
        },
        rubric_id=rubric.rubric_id,
        rubric_version=rubric.version,
        prompt_version=rubric.prompt_version,
    )


def _score_dimensions(
    spec: JudgeCaseSpec, candidate: _Candidate
) -> list[JudgeDimensionResult]:
    received = {item.name: item for item in candidate.dimensions}
    expected = [item.name for item in spec.dimensions]
    if set(received) != set(expected) or len(candidate.dimensions) != len(expected):
        raise JudgeOutputError(
            "Judge output dimensions do not match requested dimensions"
        )
    return [
        JudgeDimensionResult(
            name=dimension.name,
            score=received[dimension.name].score,
            passed=received[dimension.name].score >= dimension.threshold,
            reason=received[dimension.name].reason,
            evidence_refs=received[dimension.name].evidence_refs,
        )
        for dimension in spec.dimensions
    ]


def _failed_attempt(number, status, started, exc) -> JudgeAttempt:
    return JudgeAttempt(
        attempt=number,
        status=status,
        latency_ms=round((monotonic() - started) * 1000),
        error=_safe_error(exc),
    )


def _failed_result(status, metadata, rubric, attempts, started, exc) -> JudgeResult:
    return JudgeResult(
        status=status,
        model=str(metadata.get("model", "unknown")),
        prompt_version=rubric.prompt_version,
        rubric_id=rubric.rubric_id,
        rubric_version=rubric.version,
        output_schema_version=rubric.output_schema_version,
        attempts=attempts,
        latency_ms=round((monotonic() - started) * 1000),
        error=_safe_error(exc),
    )


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]"
                if any(marker in str(key).lower() for marker in _SECRET_MARKERS)
                else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _safe_error(exc: Exception) -> str:
    return json.dumps(_redact({"message": str(exc)}), ensure_ascii=False)
