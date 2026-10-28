from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from dataset_builder.suite_config import PathReference, SuiteConfig
from dataset_builder.suite_definition import (
    ROOT as BUILDER_ROOT,
)
from dataset_builder.suite_definition import (
    discover_suite_configs,
    load_suite,
    resolve_path_reference,
)

ROOT = Path(__file__).resolve().parents[1]


def valid_suite_payload() -> dict:
    path = ROOT / "suites" / "mini_agent_query_user_intent_v1" / "suite.json"
    return json.loads(path.read_text())


def test_suite_config_binds_bundle_without_protocol_routing():
    payload = valid_suite_payload()
    config = SuiteConfig.model_validate(payload)
    assert config.capability_input.bundle_hash == (
        "99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8"
    )

    for old_field in (
        "capability_selection",
        "legacy_embedded_policy",
        "candidate_protocol",
        "compilation",
    ):
        changed = deepcopy(payload)
        changed[old_field] = {}
        with pytest.raises(ValidationError, match=old_field):
            SuiteConfig.model_validate(changed)


def test_suite_requires_external_policy_references():
    payload = valid_suite_payload()
    payload.pop("policies")
    with pytest.raises(ValidationError, match="policies"):
        SuiteConfig.model_validate(payload)


@pytest.mark.parametrize("path", ["", "/tmp/out", "../escape", "a/../escape"])
def test_suite_paths_are_safe(path):
    payload = valid_suite_payload()
    payload["capability_input"]["bundle"]["path"] = path
    with pytest.raises(ValidationError):
        SuiteConfig.model_validate(payload)


def test_execution_profiles_are_strict_and_unique():
    payload = valid_suite_payload()
    for invalid in (
        {"": {"allowed_tools": []}},
        {"shadow": {"allowed_tools": ["same", "same"]}},
        {"shadow": {"allowed_tools": [], "unexpected": True}},
    ):
        changed = deepcopy(payload)
        changed["execution_profiles"] = invalid
        with pytest.raises(ValidationError):
            SuiteConfig.model_validate(changed)


def test_checked_in_suites_are_portable_and_loadable():
    discovered = discover_suite_configs(BUILDER_ROOT / "suites")
    assert set(discovered) == {
        "mini_agent_add_backpack_gift_intent_v1",
        "mini_agent_add_backpack_gift_intent_v2",
        "mini_agent_intent_v1",
        "mini_agent_intent_v2",
        "mini_agent_query_gift_intent_v1",
        "mini_agent_query_gift_intent_v2",
        "mini_agent_query_user_intent_v1",
        "mini_agent_query_user_intent_v2",
        "mini_agent_query_user_intent_v3",
    }
    for suite_id, path in discovered.items():
        assert "/Users/yuanyu" not in path.read_text()
        suite = load_suite(suite_id)
        expected_bundle_name = (
            "capabilities" if suite_id.endswith("_v1") else "trace_v1"
        )
        assert suite.capability_bundle_path.name == expected_bundle_name
        assert suite.capability_ir.source_protocol_version == "3.0"
        assert suite.policy_set is not None


def test_discovery_rejects_duplicate_and_missing_configs(tmp_path):
    payload = valid_suite_payload()
    for name in ("first", "second"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "suite.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="duplicate suite_id"):
        discover_suite_configs(tmp_path)

    missing_root = tmp_path / "missing-root"
    (missing_root / "suite").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="suite.json"):
        discover_suite_configs(missing_root)


def test_resolve_path_reference_uses_declared_base_only(tmp_path):
    builder_root = tmp_path / "projects" / "builder"
    suite_dir = builder_root / "suites" / "sample"
    suite_dir.mkdir(parents=True)
    reference = PathReference(base="projects_root", path="agent/bundle")
    assert resolve_path_reference(
        reference, builder_root=builder_root, suite_dir=suite_dir
    ) == (builder_root.parent / "agent" / "bundle").resolve()


def test_unknown_suite_has_no_fallback():
    with pytest.raises(ValueError, match="unknown suite"):
        load_suite("missing")
