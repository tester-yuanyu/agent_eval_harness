from types import ModuleType

import pytest


def test_source_binding_requires_loaded_module_to_match_root(tmp_path):
    from capability_snapshot_kit.ingestion.sources import bound_module_sources

    actual = tmp_path / "loaded"
    actual.mkdir()
    (actual / "agent.py").write_text("VERSION=1\n")
    other = tmp_path / "other"
    other.mkdir()
    (other / "agent.py").write_text("VERSION=2\n")
    module = ModuleType("other_agent")
    module.__file__ = str(actual / "agent.py")
    assert (
        bound_module_sources(actual, {"agent.py": module})["agent.py"].path
        == "agent.py"
    )
    with pytest.raises(ValueError, match="loaded module"):
        bound_module_sources(other, {"agent.py": module})
