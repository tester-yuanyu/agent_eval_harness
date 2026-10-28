"""Explicit, exact-version registry for trusted evaluator plugins."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from jsonschema import Draft202012Validator

from ..contracts.models import ResolvedPluginSnapshot
from .models import PluginDescriptor, PluginKind, PluginReference

T = TypeVar("T")


class PluginCatalogError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        field_path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field_path = field_path


@dataclass(frozen=True)
class PluginRegistration(Generic[T]):
    descriptor: PluginDescriptor
    implementation: T
    config: Mapping[str, Any] = field(default_factory=dict)


class PluginCatalog:
    def __init__(self) -> None:
        self._registrations: dict[
            tuple[PluginKind, str, str], PluginRegistration[Any]
        ] = {}

    def register(self, descriptor: PluginDescriptor, implementation: Any) -> None:
        key = (descriptor.kind, descriptor.plugin_id, descriptor.version)
        if key in self._registrations:
            raise PluginCatalogError(
                "DUPLICATE_PLUGIN",
                f"plugin {key!r} is already registered",
            )
        Draft202012Validator.check_schema(descriptor.config_schema)
        self._registrations[key] = PluginRegistration(descriptor, implementation)

    def resolve(
        self,
        reference: PluginReference,
        *,
        expected_kind: PluginKind,
        contract_version: str,
        field_path: str,
    ) -> PluginRegistration[Any]:
        key = (expected_kind, reference.plugin_id, reference.version)
        registration = self._registrations.get(key)
        if registration is None:
            known_identity = any(
                plugin_id == reference.plugin_id and version == reference.version
                for _, plugin_id, version in self._registrations
            )
            code = "PLUGIN_KIND_MISMATCH" if known_identity else "PLUGIN_NOT_FOUND"
            raise PluginCatalogError(
                code,
                f"plugin {key!r} is not registered",
                field_path=field_path,
            )
        if contract_version not in registration.descriptor.supported_contract_versions:
            raise PluginCatalogError(
                "PLUGIN_CONTRACT_INCOMPATIBLE",
                f"plugin {key!r} does not support contract {contract_version!r}",
                field_path=field_path,
            )
        validator = Draft202012Validator(registration.descriptor.config_schema)
        errors = sorted(
            validator.iter_errors(reference.config),
            key=lambda item: (list(item.absolute_path), item.message),
        )
        if errors:
            error = errors[0]
            config_path = f"{field_path}.config"
            for component in error.absolute_path:
                config_path += (
                    f"[{component}]"
                    if isinstance(component, int)
                    else f".{component}"
                )
            if error.validator == "additionalProperties":
                allowed = set(error.schema.get("properties", {}))
                extras = sorted(set(error.instance) - allowed)
                if extras:
                    config_path += f".{extras[0]}"
            raise PluginCatalogError(
                "PLUGIN_CONFIG_INVALID",
                error.message,
                field_path=config_path,
            )
        return PluginRegistration(
            registration.descriptor,
            registration.implementation,
            dict(reference.config),
        )

    @staticmethod
    def snapshot(
        registration: PluginRegistration[Any],
    ) -> ResolvedPluginSnapshot:
        descriptor = registration.descriptor
        return ResolvedPluginSnapshot(
            kind=descriptor.kind,
            plugin_id=descriptor.plugin_id,
            version=descriptor.version,
            implementation_fingerprint=descriptor.implementation_fingerprint,
            config=dict(registration.config),
        )
