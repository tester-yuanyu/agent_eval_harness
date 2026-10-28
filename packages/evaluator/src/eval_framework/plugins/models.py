"""Strict identities used by the explicit plugin catalog."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from ..schema_base import StrictModel

PluginKind = Literal[
    "provider",
    "dataset_loader",
    "assertion_rule",
    "trace_rule",
    "judge_backend",
    "pipeline_stage",
    "report_renderer",
    "gate_check",
]


class PluginReference(StrictModel):
    plugin_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class PluginDescriptor(StrictModel):
    plugin_id: str = Field(min_length=1)
    kind: PluginKind
    version: str = Field(min_length=1)
    config_schema: dict[str, Any]
    supported_contract_versions: list[str] = Field(min_length=1)
    implementation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_config_schema(self) -> Self:
        if self.config_schema.get("type") != "object":
            raise ValueError("plugin config_schema must describe an object")
        if self.config_schema.get("additionalProperties") is not False:
            raise ValueError("plugin config_schema must reject additional properties")
        if len(self.supported_contract_versions) != len(
            set(self.supported_contract_versions)
        ):
            raise ValueError("supported_contract_versions must be unique")
        return self
