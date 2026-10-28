"""Capability compilation is supported by installed wheels as well as checkouts."""

from pathlib import Path

import minimal_agent
from minimal_agent.capabilities.v3.bundle import DEFAULT_CAPABILITY_SPEC_ROOT


def test_capability_specs_are_package_resources_and_match_source():
    package = Path(minimal_agent.__file__).resolve().parent
    assert DEFAULT_CAPABILITY_SPEC_ROOT.is_relative_to(package)
    source = Path(__file__).resolve().parents[1] / "capability_specs"
    for path in source.rglob("*.md"):
        packaged = DEFAULT_CAPABILITY_SPEC_ROOT / path.relative_to(source)
        assert packaged.read_bytes() == path.read_bytes()


def test_installed_resource_compiler_builds_current_bundle():
    bundle = minimal_agent.build_capability_bundle(
        minimal_agent.build_default_intent_registry(), minimal_agent.ToolRegistry()
    )
    assert bundle.agent.agent_id == "mini_agent"
