from pathlib import Path

from minimal_agent.capabilities.v3.bundle import export_capability_bundle_v3
from minimal_agent.capabilities.v3.diffing import diff_capability_bundles_v3
from minimal_agent.contracts.intents import build_default_intent_registry
from minimal_agent.contracts.tools import ToolResult
from minimal_agent.runtime.tool_registry import ToolRegistry
from minimal_agent.testing.query_user_tool import query_user_evaluation_definition


def _handler(**arguments) -> ToolResult:
    return ToolResult(success=True, code="OK", message="ok", data=arguments)


def _export(root: Path, configured: bool) -> None:
    registry = ToolRegistry()
    if configured:
        registry.register(query_user_evaluation_definition(_handler))
    export_capability_bundle_v3(root, build_default_intent_registry(), registry)


def _files(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_diff_reports_ids_and_in_memory_affected_selection_roots(
    tmp_path: Path,
) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    _export(old_root, configured=False)
    _export(new_root, configured=True)
    before_old = _files(old_root)
    before_new = _files(new_root)

    result = diff_capability_bundles_v3(old_root, new_root)

    assert result.added_ids == ["tool.query_user_info"]
    assert result.removed_ids == []
    assert "agent.mini_agent" in result.changed_ids
    assert "intent.query_user" in result.changed_ids
    assert "scope.planning_execution" in result.affected_selection_roots
    assert "chain.end_to_end" in result.affected_selection_roots
    assert "intent.query_user" in result.affected_selection_roots
    assert _files(old_root) == before_old
    assert _files(new_root) == before_new


def test_diff_is_directional_for_removed_ids(tmp_path: Path) -> None:
    configured = tmp_path / "configured"
    default = tmp_path / "default"
    _export(configured, configured=True)
    _export(default, configured=False)

    result = diff_capability_bundles_v3(configured, default)

    assert result.added_ids == []
    assert result.removed_ids == ["tool.query_user_info"]
