"""Catalog-driven tool profiles and execution contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import Field

from .capabilities import CapabilityRegistry
from .schemas import ExecutionProfile, StrictModel


class ToolCatalogError(ValueError):
    """Frozen Tool Catalog or tool snapshots are inconsistent."""


class ExecutionProfileError(ToolCatalogError):
    """A manifest execution profile cannot be bound to frozen tools."""


class ToolContract(StrictModel):
    name: str = Field(min_length=1)
    operation: Literal["read", "write"]
    fault_modes: frozenset[str]


class ToolCatalog:
    def __init__(
        self,
        *,
        profiles: dict[str, frozenset[str]],
        tools: dict[str, ToolContract],
    ) -> None:
        self._profiles = profiles
        self._tools = tools

    @classmethod
    def from_registry(
        cls,
        registry: CapabilityRegistry,
        *,
        profiles: Mapping[str, ExecutionProfile],
    ) -> ToolCatalog:
        catalog_documents = [
            item
            for item in registry.bundle.documents
            if item.snapshot_type == "tool_catalog"
        ]
        if len(catalog_documents) > 1:
            raise ToolCatalogError(
                "capability bundle must not contain multiple tool catalogs"
            )
        declared_ids = None
        if catalog_documents:
            catalog = catalog_documents[0].payload
            declared_ids = catalog.get("tool_snapshot_ids")
            if not isinstance(declared_ids, list):
                raise ToolCatalogError(
                    "tool catalog tool_snapshot_ids are required"
                )

        tools: dict[str, ToolContract] = {}
        snapshot_ids: set[str] = set()
        for document in registry.bundle.documents:
            if document.snapshot_type not in {"tool", "tool_capability"}:
                continue
            payload = document.payload
            name = payload.get("tool_name")
            operation = payload.get("tool_type")
            fault_modes = payload.get("fault_modes")
            if document.snapshot_format_version == "3.0":
                # v3 declares effects, not the legacy read/write discriminator.
                # A tool error contract does not imply injectable fault support.
                effects = payload.get("side_effects")
                if not isinstance(effects, list):
                    raise ToolCatalogError(
                        f"missing side_effects in v3 snapshot {document.snapshot_id!r}"
                    )
                operation = "write" if effects else "read"
                fault_modes = []
            if (
                not isinstance(name, str)
                or operation not in {"read", "write"}
                or not isinstance(fault_modes, list)
                or not all(isinstance(item, str) and item for item in fault_modes)
            ):
                raise ToolCatalogError(
                    f"invalid tool capability snapshot {document.snapshot_id!r}"
                )
            if name in tools:
                raise ToolCatalogError(f"duplicate tool name {name!r}")
            tools[name] = ToolContract(
                name=name,
                operation=operation,
                fault_modes=frozenset(fault_modes),
            )
            snapshot_ids.add(document.snapshot_id)

        if declared_ids is not None:
            if (
                not all(isinstance(item, str) and item for item in declared_ids)
                or len(declared_ids) != len(set(declared_ids))
                or set(declared_ids) != snapshot_ids
            ):
                raise ToolCatalogError(
                    "tool catalog tool_snapshot_ids do not match tool snapshots"
                )

        resolved_profiles: dict[str, frozenset[str]] = {}
        for profile, definition in profiles.items():
            names = definition.allowed_tools
            unknown = set(names) - set(tools)
            if unknown:
                raise ExecutionProfileError(
                    f"profile {profile!r} references unknown tools {sorted(unknown)}"
                )
            resolved_profiles[profile] = frozenset(names)
        return cls(profiles=resolved_profiles, tools=tools)

    def tools_for_profile(self, profile: str) -> frozenset[str]:
        try:
            return self._profiles[profile]
        except KeyError as exc:
            raise KeyError(f"unknown tool profile {profile!r}") from exc

    def get_tool(self, name: str) -> ToolContract:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool {name!r}") from exc
