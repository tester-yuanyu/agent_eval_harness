"""Trusted, provider-neutral capability protocol profiles."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _safe_relative_path(value: str) -> str:
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or any(part in {"", "."} for part in candidate.parts)
        or "\\" in value
    ):
        raise ValueError("path must be relative and contain no parent segments")
    return value


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class AdapterReference(ProfileModel):
    protocol: str = Field(min_length=1)
    version: str = Field(min_length=1)


class TrustedSchemaProfile(ProfileModel):
    schema_path: str = Field(min_length=1)
    schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("schema_path")
    @classmethod
    def safe_schema_path(cls, value: str) -> str:
        return _safe_relative_path(value)


class SnapshotTypeProfile(TrustedSchemaProfile):
    reference_fields: list[str]

    @field_validator("reference_fields")
    @classmethod
    def unique_reference_fields(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("reference_fields must be unique")
        return value


class ProtocolProfile(ProfileModel):
    schema_version: Literal["1.0"]
    profile_id: str = Field(min_length=1)
    protocol_id: str = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    root_filename: str = Field(min_length=1)
    root_snapshot_type: str = Field(min_length=1)
    snapshot_types: dict[str, SnapshotTypeProfile] = Field(min_length=1)
    supporting_schemas: dict[str, TrustedSchemaProfile] = Field(
        default_factory=dict
    )
    canonical_json_algorithm: Literal["sorted-json-v1"]
    bundle_hash_algorithm: Literal["sorted-reference-projection-v1"]
    extension_policy: Literal["reject", "declared"]
    adapter: AdapterReference

    @field_validator("root_filename")
    @classmethod
    def safe_root_filename(cls, value: str) -> str:
        return _safe_relative_path(value)

    @model_validator(mode="after")
    def root_type_is_declared(self) -> Self:
        if self.root_snapshot_type not in self.snapshot_types:
            raise ValueError("root_snapshot_type must be declared")
        schema_paths = [
            item.schema_path
            for item in (
                *self.snapshot_types.values(),
                *self.supporting_schemas.values(),
            )
        ]
        if len(schema_paths) != len(set(schema_paths)):
            raise ValueError("schema paths must be unique")
        return self


class TrustedProfileBinding(ProfileModel):
    profile_id: str = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        return _safe_relative_path(value)


class ProfileTrustStore(ProfileModel):
    schema_version: Literal["1.0"]
    profiles: list[TrustedProfileBinding] = Field(min_length=1)

    @model_validator(mode="after")
    def profile_keys_are_unique(self) -> Self:
        keys = [(item.profile_id, item.protocol_version) for item in self.profiles]
        if len(keys) != len(set(keys)):
            raise ValueError("trusted profile keys must be unique")
        return self


@dataclass(frozen=True)
class LoadedProtocolProfile:
    profile: ProtocolProfile
    path: Path
    sha256: str


@dataclass(frozen=True)
class TrustedSchemaBinding:
    schema_id: str
    relative_path: str
    sha256: str


def _read_json(path: Path) -> object:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text())


def load_trust_store(path: Path) -> ProfileTrustStore:
    return ProfileTrustStore.model_validate(_read_json(path))


def load_trusted_profile(
    profile_id: str,
    protocol_version: str,
    trust_store: Path,
) -> LoadedProtocolProfile:
    store = load_trust_store(trust_store)
    matches = [
        item
        for item in store.profiles
        if item.profile_id == profile_id
        and item.protocol_version == protocol_version
    ]
    if not matches:
        raise ValueError(
            f"profile is not trusted: {profile_id!r} {protocol_version!r}"
        )
    binding = matches[0]
    root = trust_store.resolve().parent
    path = (root / binding.path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("trusted profile path escapes trust-store root")
    payload = _read_json(path)
    actual = canonical_sha256(payload)
    if actual != binding.sha256:
        raise ValueError(
            "trusted profile hash mismatch: "
            f"expected {binding.sha256}, found {actual}"
        )
    profile = ProtocolProfile.model_validate(payload)
    if (
        profile.profile_id != profile_id
        or profile.protocol_version != protocol_version
    ):
        raise ValueError("trusted profile identity mismatch")
    return LoadedProtocolProfile(profile=profile, path=path, sha256=actual)


def verify_bundle_schemas(
    loaded: LoadedProtocolProfile,
    bundle_root: Path,
) -> tuple[TrustedSchemaBinding, ...]:
    root = bundle_root.resolve()
    bindings: list[TrustedSchemaBinding] = []
    expected_paths: set[str] = set()
    for snapshot_type, definition in sorted(
        loaded.profile.snapshot_types.items()
    ):
        path = (root / definition.schema_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(
                f"trusted schema is missing or unsafe: {definition.schema_path}"
            )
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != definition.schema_sha256:
            raise ValueError(
                "trusted schema hash mismatch: "
                f"{definition.schema_path}: expected "
                f"{definition.schema_sha256}, found {actual}"
            )
        expected_paths.add(definition.schema_path)
        bindings.append(
            TrustedSchemaBinding(
                schema_id=f"snapshot_type:{snapshot_type}",
                relative_path=definition.schema_path,
                sha256=actual,
            )
        )
    for schema_id, definition in sorted(
        loaded.profile.supporting_schemas.items()
    ):
        path = (root / definition.schema_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(
                f"trusted schema is missing or unsafe: {definition.schema_path}"
            )
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != definition.schema_sha256:
            raise ValueError(
                "trusted schema hash mismatch: "
                f"{definition.schema_path}: expected "
                f"{definition.schema_sha256}, found {actual}"
            )
        expected_paths.add(definition.schema_path)
        bindings.append(
            TrustedSchemaBinding(
                schema_id=f"supporting:{schema_id}",
                relative_path=definition.schema_path,
                sha256=actual,
            )
        )
    if loaded.profile.extension_policy == "reject":
        actual_paths = {
            path.relative_to(root).as_posix()
            for path in (root / "schemas").glob("*.json")
            if path.is_file()
        }
        extras = sorted(actual_paths - expected_paths)
        if extras:
            raise ValueError(f"untrusted schema files are not allowed: {extras}")
    return tuple(bindings)


def write_profile_schemas(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "protocol_profile.schema.json": ProtocolProfile.model_json_schema(),
        "trust_store.schema.json": ProfileTrustStore.model_json_schema(),
    }
    for filename, schema in outputs.items():
        (root / filename).write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
        )
