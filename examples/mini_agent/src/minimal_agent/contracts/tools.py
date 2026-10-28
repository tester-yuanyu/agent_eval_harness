"""Generic executable Tool contracts exposed by configured Agent runtimes."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from minimal_agent.contracts.agent import ProtocolModel


class ToolResult(ProtocolModel):
    """Uniform observable result returned by registered Tool handlers."""

    success: bool
    code: str
    message: str
    data: dict[str, Any]


@dataclass(frozen=True)
class ToolContract:
    """Immutable execution and capability metadata for one registered Tool."""

    name: str
    version: str
    description: str
    arguments_model: type[ProtocolModel]
    tool_type: Literal["read", "write"]
    parameter_rules: Mapping[str, Any]
    permission_requirements: tuple[str, ...]
    requires_confirmation: bool
    risk_level: Literal["low", "medium", "high"]
    idempotency_rules: Mapping[str, Any]
    side_effects: tuple[str, ...]
    result_contracts: Mapping[str, Mapping[str, Any]]
    empty_result_behavior: str
    partial_success_behavior: str
    trace_event_types: tuple[str, ...]
    implementation_profile: Literal[
        "production", "evaluation_adapter", "test_fixture"
    ] = "production"
    simulation_capabilities: tuple[str, ...] = ()
    observation_interfaces: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("name", "version", "description"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        for field_name in (
            "simulation_capabilities",
            "observation_interfaces",
        ):
            if any(not value.strip() for value in getattr(self, field_name)):
                raise ValueError(f"{field_name} entries must not be empty")

    @property
    def snapshot_id(self) -> str:
        return f"tool.{self.name}"
