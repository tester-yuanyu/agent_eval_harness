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
from .schemas import DatasetBundle, ValidationReport

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
    provider = _optional_mini_agent_factory()
    if provider is not None:
        registry.register("mini_agent", provider)
    return registry


def default_benchmark_registry() -> ProviderRegistry:
    """Explicit built-ins using the same registry as historical Suite Providers."""
    from .benchmark.adapters import NanobotAdapterFactory

    registry = default_provider_registry()
    registry.register("nanobot", NanobotAdapterFactory())
    return registry


def resolve_benchmark_adapter(config: dict, registry: ProviderRegistry | None = None):
    provider_id = config.get("provider", "nanobot")
    if not isinstance(provider_id, str) or not provider_id:
        raise ValueError("provider must be a nonempty registered identifier")
    return (registry or default_benchmark_registry()).create_adapter(
        provider_id, config=config
    )


class _LazyMiniAgentFactory:
    """Describe the optional integration without importing its runtime."""

    provider_id = "mini_agent"

    def __init__(self, package_root: Path) -> None:
        self._package_root = package_root

    def fingerprint_sources(self) -> list[Path]:
        return [Path(__file__).resolve().parent, self._package_root]

    @staticmethod
    def _factory() -> Any:
        from .providers.mini_agent import MiniAgentProviderFactory

        return MiniAgentProviderFactory()

    def create_adapter(self, *, config: dict[str, Any]):
        return self._factory().create_adapter(config=config)

    def validate_dataset(
        self, dataset: DatasetBundle, **config: Any
    ) -> ValidationReport:
        return self._factory().validate_dataset(dataset, **config)

    def create(
        self, dataset: DatasetBundle, model_client_factory: Any = None, **config: Any
    ) -> Any:
        return self._factory().create(dataset, model_client_factory, **config)


def _optional_mini_agent_factory() -> _LazyMiniAgentFactory | None:
    """Load the reference integration only when its optional package is present."""
    from importlib.util import find_spec

    try:
        spec = find_spec("minimal_agent")
    except ModuleNotFoundError as exc:
        if exc.name != "minimal_agent":
            raise
        spec = None
    if spec is None or spec.origin is None:
        return None
    return _LazyMiniAgentFactory(Path(spec.origin).resolve().parent)


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
    provider = _optional_mini_agent_factory()
    if provider is None:
        return catalog
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
