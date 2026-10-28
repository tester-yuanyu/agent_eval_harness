"""Trusted, explicitly selected plugins; no imports are read from input data."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from capability_snapshot_kit.adapter import CapabilityAdapterV3

from .models import FactDocument, SourceReference

if TYPE_CHECKING:
    from .requests import ExtractionRequest


class FactCollector(Protocol):
    def collect(self, source_root: Path) -> FactDocument: ...


class FactExtractor(Protocol):
    def extract(self, request: ExtractionRequest) -> FactDocument: ...


class AdapterCollector:
    def __init__(
        self,
        adapter: CapabilityAdapterV3,
        *,
        sources: dict[str, SourceReference] | None = None,
        origins: dict[str, list[str]] | None = None,
    ) -> None:
        self.adapter = adapter
        self.sources = sources or {}
        self.origins = origins or {}

    def collect(self, source_root: Path) -> FactDocument:
        return FactDocument(
            agent=self.adapter.agent_facts(),
            modules=self.adapter.module_facts(),
            intents=self.adapter.intent_facts(),
            tools=self.adapter.tool_facts(),
            evidence=self.adapter.evidence_facts(),
            sources=self.sources,
            origins=self.origins,
        )


def load_plugin(factory_path: str, method: str) -> FactCollector | FactExtractor:
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", factory_path):
        raise ValueError("plugin must be an explicit module:factory")
    module, factory = factory_path.split(":")
    try:
        instance = getattr(importlib.import_module(module), factory)()
    except Exception as exc:
        raise ValueError(
            f"cannot load plugin {factory_path}: {type(exc).__name__}"
        ) from exc
    if not callable(getattr(instance, method, None)):
        raise ValueError(f"plugin {factory_path} must implement {method}()")
    return instance


def collect_document(collector: FactCollector, root: Path) -> FactDocument:
    result = collector.collect(root)
    if not isinstance(result, FactDocument):
        raise ValueError("collector must return FactDocument")
    # Revalidate even if a plugin bypassed Pydantic using model_construct/copy.
    return FactDocument.model_validate(result.model_dump(mode="json"))
