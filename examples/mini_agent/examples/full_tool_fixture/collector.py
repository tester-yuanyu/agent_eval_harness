"""Bridge the existing MiniAgent adapter into the independent ingestion API."""

from pathlib import Path

from capability_snapshot_kit.ingestion import AdapterCollector, FactDocument
from capability_snapshot_kit.ingestion.sources import source_reference
from minimal_agent.capability_adapter import MiniAgentCapabilityAdapter
from minimal_agent.contracts import build_default_intent_registry

from . import create_registry


class MiniAgentCollector:
    def collect(self, source_root: Path) -> FactDocument:
        adapter = MiniAgentCapabilityAdapter(
            build_default_intent_registry(), create_registry()
        )
        document = AdapterCollector(adapter).collect(source_root)
        # Explicit integration-owned files; no generic source-code scanner in the Kit.
        paths = [
            "src/minimal_agent/capability_adapter.py",
            "src/minimal_agent/runtime/agent.py",
            "src/minimal_agent/runtime/tool_registry.py",
            "examples/full_tool_fixture/contracts.py",
            "examples/full_tool_fixture/results.py",
            "examples/full_tool_fixture/environment.py",
            "examples/full_tool_fixture/collector.py",
        ]
        for directory in (
            "src/minimal_agent/capability_facts",
            "src/minimal_agent/contracts",
        ):
            paths.extend(
                path.relative_to(source_root).as_posix()
                for path in sorted((source_root / directory).glob("*.py"))
            )
        payload = document.model_dump(mode="json")
        payload["sources"] = {
            path: source_reference(source_root, path).model_dump(mode="json")
            for path in paths
        }
        payload["origins"] = {key: paths for key in document.fact_index()}
        return FactDocument.model_validate(payload)


def create() -> MiniAgentCollector:
    return MiniAgentCollector()
