"""Typed plugin roles and deterministic protocol-based dispatch."""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

PluginRole = Literal[
    "capability_adapter",
    "snapshot_loader",
    "capability_resolver",
    "source_pack_compiler",
    "coverage_planner",
    "case_generator",
    "validation_gate",
    "review_renderer",
    "dataset_freezer",
]


@runtime_checkable
class CapabilityAdapter(Protocol):
    def convert(self, bundle: Any, selection: Any, profile: Any) -> Any: ...


@runtime_checkable
class SnapshotLoader(Protocol):
    def load(self, root: Path) -> Any: ...


@runtime_checkable
class CapabilityResolver(Protocol):
    def resolve(self, bundle: Any, selection: Any) -> Any: ...


@runtime_checkable
class SourcePackCompiler(Protocol):
    def compile_source_pack(self, suite: Any, graph: Any) -> Any: ...


@runtime_checkable
class CoveragePlanner(Protocol):
    def plan_coverage(self, suite: Any, source_pack: Any) -> Any: ...


@runtime_checkable
class CaseGenerator(Protocol):
    def generate_cases(self, request: Any, client: Any) -> Any: ...


@runtime_checkable
class ValidationGate(Protocol):
    def validate(self, suite: Any, draft: Path) -> Any: ...


@runtime_checkable
class ReviewRenderer(Protocol):
    def render_review(
        self, suite: Any, draft: Path, report: Any
    ) -> str: ...


@runtime_checkable
class DatasetFreezer(Protocol):
    def freeze(
        self, suite: Any, draft: Path, approval: Any, output: Path
    ) -> Any: ...


ROLE_PROTOCOLS = {
    "capability_adapter": CapabilityAdapter,
    "snapshot_loader": SnapshotLoader,
    "capability_resolver": CapabilityResolver,
    "source_pack_compiler": SourcePackCompiler,
    "coverage_planner": CoveragePlanner,
    "case_generator": CaseGenerator,
    "validation_gate": ValidationGate,
    "review_renderer": ReviewRenderer,
    "dataset_freezer": DatasetFreezer,
}


class PluginRegistryError(ValueError):
    """A plugin key cannot be registered or resolved."""


class DuplicatePluginError(PluginRegistryError):
    """A plugin key was registered more than once."""


class MissingPluginError(PluginRegistryError):
    """A requested plugin key is unavailable."""


class PluginHashMismatchError(PluginRegistryError):
    """A plugin registration does not match the trusted implementation hash."""


@dataclass(frozen=True, order=True)
class PluginKey:
    role: PluginRole
    protocol: str
    version: str

    def __post_init__(self) -> None:
        if not self.protocol or not self.version:
            raise ValueError("plugin protocol and version must be non-empty")


@dataclass(frozen=True)
class PluginRegistration:
    key: PluginKey
    implementation_sha256: str
    plugin: object


def _implementation_sha256(plugin: object) -> str:
    path = inspect.getsourcefile(type(plugin))
    if path is not None and Path(path).is_file():
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    identity = f"{type(plugin).__module__}.{type(plugin).__qualname__}"
    return hashlib.sha256(identity.encode()).hexdigest()


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[PluginKey, PluginRegistration] = {}

    def register(
        self,
        key: PluginKey,
        plugin: object,
        *,
        implementation_sha256: str | None = None,
    ) -> None:
        if key in self._plugins:
            raise DuplicatePluginError(f"plugin already registered: {key}")
        expected = ROLE_PROTOCOLS[key.role]
        if not isinstance(plugin, expected):
            raise TypeError(f"plugin does not implement {key.role}: {plugin!r}")
        digest = implementation_sha256 or _implementation_sha256(plugin)
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("implementation_sha256 must be a lowercase SHA-256")
        self._plugins[key] = PluginRegistration(
            key=key,
            implementation_sha256=digest,
            plugin=plugin,
        )

    def resolve(self, key: PluginKey) -> object:
        return self.resolve_registration(key).plugin

    def resolve_registration(
        self,
        key: PluginKey,
        *,
        expected_sha256: str | None = None,
    ) -> PluginRegistration:
        try:
            registration = self._plugins[key]
        except KeyError as exc:
            raise MissingPluginError(f"plugin not registered: {key}") from exc
        if (
            expected_sha256 is not None
            and registration.implementation_sha256 != expected_sha256
        ):
            raise PluginHashMismatchError(
                f"plugin implementation hash mismatch: {key}"
            )
        return registration

    def keys(self) -> tuple[PluginKey, ...]:
        return tuple(sorted(self._plugins))
