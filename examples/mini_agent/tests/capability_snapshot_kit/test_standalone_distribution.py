import tomllib
from pathlib import Path


def test_standalone_project_has_no_agent_dependency_and_includes_resources(tmp_path):
    from scripts.build_snapshot_kit import stage_project

    root = Path(__file__).resolve().parents[2]
    stage_project(root, tmp_path)
    metadata = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    assert metadata["project"]["name"] == "capability-snapshot-kit"
    assert metadata["project"]["dependencies"] == ["pydantic>=2.6,<3", "PyYAML>=6.0,<7"]
    assert not (tmp_path / "src/minimal_agent").exists()
    assert (tmp_path / "src/capability_snapshot_kit/resources/extraction.md").exists()
    assert (
        tmp_path / "src/capability_snapshot_kit/resources/conversation/protocol.md"
    ).exists()
