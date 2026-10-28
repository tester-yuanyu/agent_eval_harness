"""Versioned input format, independent of any Agent or model provider."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from capability_snapshot_kit.base import ProtocolModel
from capability_snapshot_kit.facts import (
    AgentFactsV3,
    EvidenceFactV3,
    IntentFactV3,
    ModuleFactV3,
    ToolFactV3,
)
from capability_snapshot_kit.models import SHA256_PATTERN


class SourceReference(ProtocolModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    kind: Literal["code", "config", "documentation", "prompt", "trace"]

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        if (
            PurePosixPath(value).is_absolute()
            or "\\" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("source path must be relative without dot segments")
        return value


class FactDocument(ProtocolModel):
    document_version: Literal["1.0"] = "1.0"
    agent: AgentFactsV3
    modules: tuple[ModuleFactV3, ...] = ()
    intents: tuple[IntentFactV3, ...] = ()
    tools: tuple[ToolFactV3, ...] = ()
    evidence: tuple[EvidenceFactV3, ...] = ()
    sources: dict[str, SourceReference] = Field(default_factory=dict)
    origins: dict[str, list[str]] = Field(default_factory=dict)

    def fact_index(self) -> dict[str, ProtocolModel]:
        index: dict[str, ProtocolModel] = {f"agent.{self.agent.agent_id}": self.agent}
        for prefix, facts, attribute in (
            ("module", self.modules, "module_id"),
            ("intent", self.intents, "intent_id"),
            ("tool", self.tools, "tool_name"),
            ("evidence", self.evidence, "evidence_id"),
        ):
            for fact in facts:
                key = f"{prefix}.{getattr(fact, attribute)}"
                if key in index:
                    raise ValueError(f"duplicate fact: {key}")
                index[key] = fact
        return index

    @model_validator(mode="after")
    def validate_document(self) -> Self:
        index = self.fact_index()
        for key, fact in index.items():
            claims = getattr(fact, "capabilities", ())
            names = [claim.capability_key for claim in claims]
            if len(names) != len(set(names)):
                raise ValueError(f"duplicate capability in {key}")
        for fact_id, source_ids in self.origins.items():
            if fact_id not in index:
                raise ValueError(f"unknown fact in origins: {fact_id}")
            if len(source_ids) != len(set(source_ids)):
                raise ValueError(f"duplicate source in origins: {fact_id}")
            for source_id in source_ids:
                if source_id not in self.sources:
                    raise ValueError(f"unknown source: {source_id}")
        return self

    # Implements the existing CapabilityAdapter protocol without importing an Agent.
    def agent_facts(self) -> AgentFactsV3:
        return self.agent

    def module_facts(self) -> tuple[ModuleFactV3, ...]:
        return self.modules

    def intent_facts(self) -> tuple[IntentFactV3, ...]:
        return self.intents

    def tool_facts(self) -> tuple[ToolFactV3, ...]:
        return self.tools

    def evidence_facts(self) -> tuple[EvidenceFactV3, ...]:
        return self.evidence
