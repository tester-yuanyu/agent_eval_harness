import json
from pathlib import Path

from capability_snapshot_kit import (
    CapabilitySelection,
    collect_snapshot_references,
    load_capability_bundle,
    resolve_capability_graph,
)
from minimal_agent.capabilities import export_capability_bundle
from minimal_agent.contracts.intents import build_default_intent_registry
from minimal_agent.runtime.tool_registry import ToolRegistry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKED_IN_ROOT = PROJECT_ROOT / "capabilities"
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "capability_v3"


def _files(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_frozen_bundle_is_valid_and_current_exports_are_reproducible(
    tmp_path: Path,
) -> None:
    fresh = tmp_path / "capabilities"
    repeated = tmp_path / "repeated"
    export_capability_bundle(
        fresh,
        build_default_intent_registry(),
        ToolRegistry(),
    )

    export_capability_bundle(
        repeated,
        build_default_intent_registry(),
        ToolRegistry(),
    )
    frozen = load_capability_bundle(CHECKED_IN_ROOT)
    assert frozen.agent.capability_bundle_sha256 == (
        "99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8"
    )
    assert _files(fresh) == _files(repeated)
    current = load_capability_bundle(fresh)
    assert (
        "x-evidence-delivery"
        in current.evidence["evidence.intent_result"].payload_schema
    )
    assert len(list((CHECKED_IN_ROOT / "chains" / "critical").glob("*.json"))) == 2
    assert len(list((CHECKED_IN_ROOT / "chains" / "end_to_end").glob("*.json"))) == 1


def test_builder_fixture_resolves_and_recursively_closes_references() -> None:
    bundle = load_capability_bundle(CHECKED_IN_ROOT)
    selection = CapabilitySelection.model_validate_json(
        (FIXTURE_ROOT / "query_user_understanding.selection.json").read_text(
            encoding="utf-8"
        )
    )
    expected = json.loads(
        (FIXTURE_ROOT / "query_user_understanding.resolved.json").read_text(
            encoding="utf-8"
        )
    )

    result = resolve_capability_graph(bundle, selection)
    snapshots = {
        bundle.agent.snapshot_id: bundle.agent,
        **{item.snapshot_id: item for item in bundle.child_snapshots},
    }
    pending = [selection.scope_or_chain_id, selection.intent_id]
    closure: set[str] = set()
    while pending:
        snapshot_id = pending.pop()
        if snapshot_id in closure:
            continue
        closure.add(snapshot_id)
        pending.extend(
            reference.snapshot_id
            for reference in collect_snapshot_references(snapshots[snapshot_id])
        )

    assert result.model_dump(mode="json") == expected
    assert {
        "scope.understanding",
        "intent.query_user",
        "module.intent_router",
        "evidence.intent_result",
        "boundary.understanding",
    } <= closure
    assert all(snapshot_id in snapshots for snapshot_id in closure)


def test_builder_fixtures_contain_no_suite_or_evaluator_business_data() -> None:
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(FIXTURE_ROOT.glob("*.json"))
    ).lower()

    for forbidden in (
        "coverage_count",
        "expected_answer",
        "scoring",
        "judge",
        "fixture_user",
        "fixture-user",
    ):
        assert forbidden not in serialized
