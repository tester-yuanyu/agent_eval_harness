"""Interchangeable offline and OpenAI Responses generation clients."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any, Protocol

from .schemas import GenerationRequest, RawGeneration


class GenerationClient(Protocol):
    def generate(self, request: GenerationRequest) -> RawGeneration: ...


class ScriptedGenerationClient:
    def __init__(self, response: Any, *, error: Exception | None = None) -> None:
        self.response = response
        self.error = error

    def generate(self, request: GenerationRequest) -> RawGeneration:
        if self.error is not None:
            raise self.error
        return RawGeneration(
            request_id=request.request_id,
            mode="scripted",
            model="scripted-generation-client",
            prompt_version=request.prompt_version,
            created_at=datetime.now(UTC),
            attempts=1,
            response=self.response,
        )


class OpenAIResponsesGenerationClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        max_attempts: int = 2,
    ) -> None:
        if not api_key or not model:
            raise ValueError("OpenAI API key and generator model are required")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts

    @classmethod
    def from_env(cls) -> OpenAIResponsesGenerationClient:
        key = os.environ.get("OPENAI_API_KEY")
        model = os.environ.get("DATASET_GENERATOR_MODEL")
        if not key or not model:
            raise RuntimeError(
                "OPENAI_API_KEY and DATASET_GENERATOR_MODEL must both be set"
            )
        return cls(api_key=key, model=model)

    def generate(self, request: GenerationRequest) -> RawGeneration:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, timeout=self.timeout_seconds)
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = client.responses.create(
                    model=self.model,
                    input=request.prompt,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": request.suite_id,
                            "strict": True,
                            "schema": request.candidate_schema,
                        }
                    },
                )
                if not response.output_text:
                    raise RuntimeError("Responses API returned no output_text")
                return RawGeneration(
                    request_id=request.request_id,
                    mode="openai",
                    model=self.model,
                    prompt_version=request.prompt_version,
                    created_at=datetime.now(UTC),
                    attempts=attempt,
                    response=response.output_text,
                )
            except Exception as exc:
                last_error = exc
                if attempt < self.max_attempts:
                    time.sleep(0.25 * attempt)
        raise RuntimeError(
            f"OpenAI generation failed after {self.max_attempts} attempts"
        ) from last_error
