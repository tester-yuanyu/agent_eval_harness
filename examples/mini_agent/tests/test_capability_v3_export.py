from pathlib import Path

import pytest

from capability_snapshot_kit import calculate_snapshot_sha256
from minimal_agent.capabilities.v3.bundle import (
    _write_capability_bundle_v3,
    build_capability_bundle_v3,
    build_capability_snapshot_v3,
    schema_artifacts_v3,
)
from minimal_agent.contracts.intents import build_default_intent_registry
from minimal_agent.runtime.tool_registry import ToolRegistry

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _default_bundle():
    return build_capability_bundle_v3(
        build_default_intent_registry(),
        ToolRegistry(),
    )


def _files(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_default_bundle_has_one_root_and_every_child_catalog() -> None:
    bundle = _default_bundle()

    assert len(bundle.modules) == 7
    assert len(bundle.intents) == 7
    assert bundle.tools == {}
    assert len(bundle.scopes) == 5
    assert len(bundle.chains) == 3
    assert len(bundle.evidence) == 5
    assert len(bundle.boundaries) == 7
    expected = {
        *bundle.modules,
        *bundle.intents,
        *bundle.tools,
        *bundle.scopes,
        *bundle.chains,
        *bundle.evidence,
        *bundle.boundaries,
    }
    assert {ref.snapshot_id for ref in bundle.child_references} == expected
    assert bundle.agent.snapshot_id == "agent.mini_agent"


def test_v3_has_nine_strict_schema_artifacts() -> None:
    schemas = schema_artifacts_v3()

    assert set(schemas) == {
        "agent.schema.json",
        "module.schema.json",
        "intent.schema.json",
        "tool.schema.json",
        "scope.schema.json",
        "chain.schema.json",
        "evidence.schema.json",
        "boundary.schema.json",
        "snapshot-reference.schema.json",
    }
    assert all(schema["additionalProperties"] is False for schema in schemas.values())


def test_snapshot_and_bundle_hashes_are_deterministic() -> None:
    first = _default_bundle()
    second = _default_bundle()

    assert first.agent == second.agent
    assert first.agent.capability_bundle_sha256 == second.agent.capability_bundle_sha256
    for snapshot in [first.agent, *first.child_snapshots]:
        assert snapshot.snapshot_sha256 == calculate_snapshot_sha256(
            snapshot.model_dump(mode="json")
        )
    selected = build_capability_snapshot_v3(
        "scope.context",
        build_default_intent_registry(),
        ToolRegistry(),
    )
    assert selected == first.scopes["scope.context"]
    with pytest.raises(ValueError, match="not exportable"):
        build_capability_snapshot_v3(
            "tool.missing",
            build_default_intent_registry(),
            ToolRegistry(),
        )


def test_two_fresh_serializations_are_byte_identical_and_keep_empty_tools(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first" / "capabilities"
    second_root = tmp_path / "second" / "capabilities"

    _write_capability_bundle_v3(first_root, _default_bundle())
    _write_capability_bundle_v3(second_root, _default_bundle())

    assert _files(first_root) == _files(second_root)
    assert [path.name for path in (first_root / "tools").iterdir()] == [".gitkeep"]
    artifact_files = [
        path for path in first_root.rglob("*.json") if path.parent.name != "schemas"
    ]
    assert len(artifact_files) == 35
