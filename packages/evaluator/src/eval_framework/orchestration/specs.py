"""Strict, serializable configuration contracts for the benchmark composition root."""

from __future__ import annotations

import math
import re
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

EnvironmentName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
Nonempty = Annotated[str, Field(min_length=1)]


def validate_local_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "://" in value
        or "\0" in value
    ):
        raise ValueError("configuration paths must be nonempty local paths")
    return value


LocalPath = Annotated[str, AfterValidator(validate_local_path)]


def _secret_key(key: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", key.lower())
    return (
        compact
        in {
            "token",
            "auth",
            "credential",
            "credentials",
            "cookie",
            "cookies",
            "bearer",
        }
        or compact.endswith("token")
        or any(
            marker in compact
            for marker in (
                "apikey",
                "secret",
                "password",
                "accesstoken",
                "authtoken",
                "authorization",
                "privatekey",
                "clientkey",
            )
        )
    )


def validate_public_config(value: Any) -> None:
    """Reject raw credentials recursively before validation can echo an input."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("configuration keys must be strings")
            if key.endswith("_env"):
                if not isinstance(item, str) or not re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*", item
                ):
                    raise ValueError("*_env must contain an environment-variable name")
            elif _secret_key(key):
                raise ValueError("secret values are forbidden; use *_env references")
            validate_public_config(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            validate_public_config(item)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("configuration numbers must be finite")
    elif isinstance(value, str) and "://" in value:
        try:
            url = urlsplit(value)
            has_secret = (
                url.username is not None
                or url.password is not None
                or any(_secret_key(key) for key, _ in parse_qsl(url.query))
            )
        except ValueError as exc:
            raise ValueError("invalid configuration URL") from exc
        if has_secret:
            raise ValueError("secret values are forbidden in configuration URLs")


class StrictSpec(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )

    @model_validator(mode="before")
    @classmethod
    def no_secret_values(cls, value: Any) -> Any:
        validate_public_config(value)
        return value


class ModelSpec(StrictSpec):
    model: Nonempty | None = None
    inspect_model: Nonempty | None = None
    base_url: Nonempty | None = None
    api_key_env: EnvironmentName = "DEEPSEEK_API_KEY"
    temperature: Annotated[float, Field(ge=0)] = 0
    max_tokens: Annotated[int, Field(ge=1)] = 2048
    # Provider-specific request options are the sole open JSON extension point.
    extra_body: dict[str, JsonValue] | None = None


class HarnessSpec(StrictSpec):
    max_consecutive_errors: Annotated[int, Field(ge=1, le=300)] | None = None
    max_tool_calls: Annotated[int, Field(ge=1, le=300)] = 40
    prompt_version: Literal["harness-v1"] = "harness-v1"
    max_steps: Annotated[int, Field(ge=1, le=30)] = 12
    timeout_seconds: Annotated[float, Field(ge=1, le=600)] = 180
    module_timeout_seconds: Annotated[float, Field(gt=0, le=600)] = 30
    token_limit: Annotated[int, Field(ge=1)] | None = None
    message_limit: Annotated[int, Field(ge=1)] | None = None
    variant: Nonempty = "baseline"
    instructions: str = ""


class EnvironmentSpec(StrictSpec):
    provider: Literal["nanobot", "mini_agent", "raw_model", "nanobot_component"] = (
        "nanobot"
    )
    nanobot_root: LocalPath | None = None
    python: LocalPath | None = None
    sandbox: Literal["local", "docker"] = "docker"
    docker_base_image: Nonempty = "python:3.11-slim"
    tokenizer_mode: Literal["cl100k_base", "byte_fallback"] = "cl100k_base"
    tokenizer_cache_dir: LocalPath | None = None
    repository_root: LocalPath | None = None
    capability_bundle: LocalPath | None = None


class BenchmarkSpec(StrictSpec):
    dataset: LocalPath = "data/benchmarks/file-tools-v1/tasks.jsonl"
    level: Literal["module", "chain", "e2e"] | None = None
    split: Literal["dev", "holdout"] | None = None
    limit: Annotated[int, Field(ge=1)] | None = None


class ExecutionSpec(StrictSpec):
    repeats: Annotated[int, Field(ge=1, le=5)] = 1
    concurrency: Annotated[int, Field(ge=1, le=12)] = 4


class RunRequest(StrictSpec):
    schema_version: Literal["1.0"] = "1.0"
    model: ModelSpec
    harness: HarnessSpec
    environment: EnvironmentSpec
    benchmark: BenchmarkSpec
    execution: ExecutionSpec

    @model_serializer(mode="wrap")
    def serialize_explicit_specs(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, Any]:
        """Keep omitted options omitted, including in nested model serialization.

        Runtime defaults can depend on execution mode (for example, module
        tasks use a local sandbox). Materializing Spec defaults during a normal
        dump would turn those defaults into explicit overrides when reloaded.
        Filter the handler result so caller include/exclude options still apply.
        """
        serialized = handler(self)
        for section in ("model", "harness", "environment", "benchmark", "execution"):
            if section in serialized:
                explicit = getattr(self, section).model_fields_set
                serialized[section] = {
                    key: value
                    for key, value in serialized[section].items()
                    if key in explicit
                }
        return serialized

    def runtime_config(self) -> dict[str, Any]:
        """Project only explicitly supplied runtime keys into the existing runner."""
        config: dict[str, Any] = {}
        for spec in (self.model, self.harness, self.environment):
            values = spec.model_dump(exclude_unset=True)
            if config.keys() & values.keys():
                raise ValueError("conflicting runtime configuration keys")
            config.update(values)
        return config


class RuntimeControlSpec(StrictSpec):
    log_realtime: bool = False
    preflight: bool = False
    max_model_requests: Annotated[int, Field(ge=1)] | None = None


def validate_runtime_config(
    config: dict[str, Any],
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Validate shared Spec keys without adding defaults to legacy Provider configs.

    Strict mode rejects extension keys; legacy mode leaves external Provider keys
    untouched. Provider IDs remain open in legacy mode (registration owns them).
    Credentials are rejected before any validation error can echo their values.
    """
    validate_public_config(config)
    result = dict(config)
    known = set()
    for spec in (ModelSpec, HarnessSpec, EnvironmentSpec, RuntimeControlSpec):
        fields = set(spec.model_fields)
        if spec is EnvironmentSpec and not strict:
            fields.remove("provider")
            known.add("provider")
        known.update(fields)
        supplied = {key: value for key, value in config.items() if key in fields}
        spec.model_validate(supplied)
    if strict and (unknown := config.keys() - known):
        raise ValueError(
            "unknown runtime configuration fields: " + ", ".join(sorted(unknown))
        )
    return result
