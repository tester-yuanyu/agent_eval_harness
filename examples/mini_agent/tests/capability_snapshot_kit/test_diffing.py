from __future__ import annotations

from pathlib import Path

from capability_snapshot_kit.diffing import diff_capability_bundles_v3
from capability_snapshot_kit.exporting import export_capability_bundle_v3
from capability_snapshot_kit.spec_loader import load_capability_spec_pack_v3
from tests.capability_snapshot_kit.test_resolution import ToolCapabilityAdapter
from tests.support.capability_adapter import FakeCapabilityAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPECS = load_capability_spec_pack_v3(PROJECT_ROOT / "capability_specs")


def _export(root: Path, configured: bool) -> None:
    adapter = ToolCapabilityAdapter() if configured else FakeCapabilityAdapter()
    export_capability_bundle_v3(root, SPECS, adapter)


def _files(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_diff_reports_directional_ids_and_affected_selection_roots(
    tmp_path: Path,
) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    _export(old_root, configured=False)
    _export(new_root, configured=True)
    old_before = _files(old_root)
    new_before = _files(new_root)

    result = diff_capability_bundles_v3(old_root, new_root)

    assert result.added_ids == ["tool.query_user_info"]
    assert result.removed_ids == []
    assert "agent.example_agent" in result.changed_ids
    assert "intent.query_user" in result.changed_ids
    assert "scope.planning_execution" in result.affected_selection_roots
    assert "chain.end_to_end" in result.affected_selection_roots
    assert "intent.query_user" in result.affected_selection_roots
    assert _files(old_root) == old_before
    assert _files(new_root) == new_before


def test_diff_reports_removed_ids_in_reverse_direction(tmp_path: Path) -> None:
    configured = tmp_path / "configured"
    default = tmp_path / "default"
    _export(configured, configured=True)
    _export(default, configured=False)

    result = diff_capability_bundles_v3(configured, default)

    assert result.added_ids == []
    assert result.removed_ids == ["tool.query_user_info"]
