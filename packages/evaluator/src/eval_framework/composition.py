"""Application composition root for built-in evaluator integrations."""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from typing import Any

from .onboarding.loader import CandidateDatasetLoader
from .plugins.builtin import JsonDocumentDatasetLoader, LegacyJsonlDatasetLoader
from .plugins.catalog import PluginCatalog
from .plugins.models import PluginDescriptor
from .provider_registry import ProviderRegistry
from .providers.external import (
    ExternalProviderFactory,
    RuntimeBinding,
    RuntimeFileIdentity,
)
from .providers.mini_agent import MiniAgentProviderFactory

_EMPTY_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


def _implementation_fingerprint(implementation: Any) -> str:
    """Fingerprint the plugin's declared executable source closure."""
    implementation_type = type(implementation)
    source_path = inspect.getsourcefile(implementation_type)
    if source_path is None:
        raise RuntimeError(f"cannot locate implementation for {implementation_type!r}")
    roots = [Path(source_path)]
    declared = getattr(implementation, "fingerprint_sources", None)
    if callable(declared):
        roots.extend(Path(item) for item in declared())
    chunks = [
        f"{implementation_type.__module__}.{implementation_type.__qualname__}".encode()
    ]
    seen: set[Path] = set()
    for root in roots:
        candidates = [root] if root.is_file() else sorted(root.rglob("*"))
        for candidate in candidates:
            if (
                not candidate.is_file()
                or candidate.suffix in {".pyc", ".pyo"}
                or "__pycache__" in candidate.parts
                or candidate in seen
            ):
                continue
            seen.add(candidate)
            relative = (
                candidate.name if root.is_file() else str(candidate.relative_to(root))
            )
            chunks.extend((relative.encode(), candidate.read_bytes()))
    payload = b"\0".join(chunks)
    return hashlib.sha256(payload).hexdigest()


def _descriptor(plugin_id: str, kind: str, implementation: Any) -> PluginDescriptor:
    return PluginDescriptor(
        plugin_id=plugin_id,
        kind=kind,
        version="1.0.0",
        config_schema=_EMPTY_CONFIG_SCHEMA,
        supported_contract_versions=["1.0"],
        implementation_fingerprint=_implementation_fingerprint(implementation),
    )


def default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register("mini_agent", MiniAgentProviderFactory())
    return registry


def default_plugin_catalog() -> PluginCatalog:
    catalog = PluginCatalog()
    candidate_loader = CandidateDatasetLoader()
    catalog.register(
        _descriptor("candidate_delivery_v1", "dataset_loader", candidate_loader),
        candidate_loader,
    )
    external = ExternalProviderFactory()
    external_descriptor = _descriptor("external_provider_v1", "provider", external)
    external_descriptor = external_descriptor.model_copy(
        update={
            "config_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["binding"],
                "properties": {
                    "binding": RuntimeBinding.model_json_schema(),
                    "runtime_files": {
                        "type": "array",
                        "items": RuntimeFileIdentity.model_json_schema(),
                    },
                },
            }
        }
    )
    catalog.register(external_descriptor, external)
    legacy_loader = LegacyJsonlDatasetLoader()
    catalog.register(
        _descriptor("legacy_jsonl_eval_case_v1", "dataset_loader", legacy_loader),
        legacy_loader,
    )
    document_loader = JsonDocumentDatasetLoader()
    catalog.register(
        _descriptor("fixture_json_document_v1", "dataset_loader", document_loader),
        document_loader,
    )
    provider = MiniAgentProviderFactory()
    provider_descriptor = _descriptor("mini_agent_provider_v1", "provider", provider)
    provider_descriptor = provider_descriptor.model_copy(
        update={
            "config_schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"environment": {"enum": ["gift_sqlite_v1"]}},
            }
        }
    )
    catalog.register(
        provider_descriptor,
        provider,
    )
    return catalog
