from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dataset_builder.capability_profiles import (
    load_trust_store,
    load_trusted_profile,
    verify_bundle_schemas,
)
from dataset_builder.plugins import (
    DuplicatePluginError,
    PluginHashMismatchError,
    PluginKey,
    PluginRegistry,
)

ROOT = Path(__file__).resolve().parents[1]


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _write_profile(root: Path) -> tuple[Path, Path, Path]:
    schema_path = root / "bundle" / "schemas" / "agent.schema.json"
    schema_path.parent.mkdir(parents=True)
    schema_path.write_text('{"type":"object"}\n')
    schema_sha256 = hashlib.sha256(schema_path.read_bytes()).hexdigest()
    reference_schema = schema_path.parent / "snapshot-reference.schema.json"
    reference_schema.write_text('{"type":"object"}\n')
    reference_schema_sha256 = hashlib.sha256(
        reference_schema.read_bytes()
    ).hexdigest()
    profile = {
        "schema_version": "1.0",
        "profile_id": "capability-snapshot",
        "protocol_id": "capability-snapshot",
        "protocol_version": "3.0",
        "root_filename": "agent.json",
        "root_snapshot_type": "agent",
        "snapshot_types": {
            "agent": {
                "schema_path": "schemas/agent.schema.json",
                "schema_sha256": schema_sha256,
                "reference_fields": ["module_refs"],
            }
        },
        "supporting_schemas": {
            "snapshot_reference": {
                "schema_path": "schemas/snapshot-reference.schema.json",
                "schema_sha256": reference_schema_sha256,
            }
        },
        "canonical_json_algorithm": "sorted-json-v1",
        "bundle_hash_algorithm": "sorted-reference-projection-v1",
        "extension_policy": "reject",
        "adapter": {
            "protocol": "capability-snapshot",
            "version": "1.0",
        },
    }
    profile_path = root / "profiles" / "v3.json"
    profile_path.parent.mkdir()
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n")
    trust_store = {
        "schema_version": "1.0",
        "profiles": [
            {
                "profile_id": "capability-snapshot",
                "protocol_version": "3.0",
                "path": "profiles/v3.json",
                "sha256": _canonical_sha256(profile),
            }
        ],
    }
    trust_path = root / "trust_store.json"
    trust_path.write_text(json.dumps(trust_store, indent=2) + "\n")
    return trust_path, profile_path, root / "bundle"


def test_trust_store_loads_profile_and_verifies_bundle_schema(tmp_path):
    trust_path, _, bundle_root = _write_profile(tmp_path)

    store = load_trust_store(trust_path)
    loaded = load_trusted_profile(
        "capability-snapshot",
        "3.0",
        trust_path,
    )
    bindings = verify_bundle_schemas(loaded, bundle_root)

    assert store.schema_version == "1.0"
    assert loaded.profile.profile_id == "capability-snapshot"
    assert loaded.sha256 == store.profiles[0].sha256
    assert bindings[0].schema_id == "snapshot_type:agent"
    assert bindings[0].sha256 == (
        loaded.profile.snapshot_types["agent"].schema_sha256
    )
    assert bindings[1].schema_id == "supporting:snapshot_reference"


def test_profile_cannot_change_after_trust_approval(tmp_path):
    trust_path, profile_path, _ = _write_profile(tmp_path)
    payload = json.loads(profile_path.read_text())
    payload["extension_policy"] = "declared"
    profile_path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="trusted profile hash mismatch"):
        load_trusted_profile("capability-snapshot", "3.0", trust_path)


def test_bundle_schema_cannot_self_approve_tampering(tmp_path):
    trust_path, _, bundle_root = _write_profile(tmp_path)
    loaded = load_trusted_profile(
        "capability-snapshot",
        "3.0",
        trust_path,
    )
    (bundle_root / "schemas" / "agent.schema.json").write_text(
        '{"type":"string"}\n'
    )

    with pytest.raises(ValueError, match="trusted schema hash mismatch"):
        verify_bundle_schemas(loaded, bundle_root)


def test_profile_paths_and_algorithm_ids_are_strict(tmp_path):
    trust_path, profile_path, _ = _write_profile(tmp_path)
    trust = json.loads(trust_path.read_text())
    trust["profiles"][0]["path"] = "../outside.json"
    trust_path.write_text(json.dumps(trust))
    with pytest.raises(ValidationError, match="relative"):
        load_trust_store(trust_path)

    trust_path, profile_path, _ = _write_profile(tmp_path / "second")
    profile = json.loads(profile_path.read_text())
    profile["canonical_json_algorithm"] = "guess-json"
    profile_path.write_text(json.dumps(profile))
    trust = json.loads(trust_path.read_text())
    trust["profiles"][0]["sha256"] = _canonical_sha256(profile)
    trust_path.write_text(json.dumps(trust))
    with pytest.raises(ValidationError, match="sorted-json-v1"):
        load_trusted_profile("capability-snapshot", "3.0", trust_path)


def test_unapproved_and_duplicate_profiles_are_rejected(tmp_path):
    trust_path, _, _ = _write_profile(tmp_path)
    with pytest.raises(ValueError, match="profile is not trusted"):
        load_trusted_profile("other", "3.0", trust_path)

    trust = json.loads(trust_path.read_text())
    trust["profiles"].append(dict(trust["profiles"][0]))
    trust_path.write_text(json.dumps(trust))
    with pytest.raises(ValidationError, match="unique"):
        load_trust_store(trust_path)


class _Adapter:
    def convert(self, bundle, selection, profile):
        return bundle, selection, profile


def test_adapter_registration_is_hash_bound():
    registry = PluginRegistry()
    key = PluginKey("capability_adapter", "capability-snapshot", "1.0")
    registry.register(
        key,
        _Adapter(),
        implementation_sha256="a" * 64,
    )

    registration = registry.resolve_registration(key, expected_sha256="a" * 64)
    assert registration.plugin.convert(1, 2, 3) == (1, 2, 3)
    assert registration.implementation_sha256 == "a" * 64
    with pytest.raises(PluginHashMismatchError):
        registry.resolve_registration(key, expected_sha256="b" * 64)
    with pytest.raises(DuplicatePluginError):
        registry.register(
            key,
            _Adapter(),
            implementation_sha256="a" * 64,
        )


def test_checked_in_profile_trusts_the_standalone_bundle_schemas():
    loaded = load_trusted_profile(
        "capability-snapshot",
        "3.0",
        ROOT / "protocol_profiles" / "trust_store.json",
    )

    bindings = verify_bundle_schemas(
        loaded,
        ROOT.parent / "mini_agent" / "capabilities",
    )

    assert len(bindings) == 9
    assert {item.schema_id for item in bindings} == {
        "snapshot_type:agent",
        "snapshot_type:boundary",
        "snapshot_type:chain",
        "snapshot_type:evidence",
        "snapshot_type:intent",
        "snapshot_type:module",
        "snapshot_type:scope",
        "snapshot_type:tool",
        "supporting:snapshot_reference",
    }
