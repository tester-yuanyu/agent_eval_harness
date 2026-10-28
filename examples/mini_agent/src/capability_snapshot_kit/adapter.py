"""Agent adapter boundary for portable capability compilation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from capability_snapshot_kit.facts import (
    AgentFactsV3,
    EvidenceFactV3,
    IntentFactV3,
    ModuleFactV3,
    ToolFactV3,
)


@runtime_checkable
class CapabilityAdapterV3(Protocol):
    def agent_facts(self) -> AgentFactsV3: ...

    def module_facts(self) -> tuple[ModuleFactV3, ...]: ...

    def intent_facts(self) -> tuple[IntentFactV3, ...]: ...

    def tool_facts(self) -> tuple[ToolFactV3, ...]: ...

    def evidence_facts(self) -> tuple[EvidenceFactV3, ...]: ...
