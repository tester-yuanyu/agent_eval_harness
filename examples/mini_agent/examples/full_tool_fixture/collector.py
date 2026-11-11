"""Bridge the existing MiniAgent adapter into the independent ingestion API."""

import importlib
import inspect
from pathlib import Path

from capability_snapshot_kit.ingestion import AdapterCollector, FactDocument
from capability_snapshot_kit.ingestion.sources import (
    bound_module_sources,
    check_sources,
)
from minimal_agent.capability_adapter import MiniAgentCapabilityAdapter
from minimal_agent.contracts import build_default_intent_registry

from . import create_registry


class MiniAgentCollector:
    def __init__(self, adapter: MiniAgentCapabilityAdapter | None = None):
        self.adapter = adapter

    def collect(self, source_root: Path) -> FactDocument:
        # 明确绑定事实声明及其实现来源；新增模块必须补充映射。
        common = [
            "src/minimal_agent/capability_adapter.py",
            "examples/full_tool_fixture/collector.py",
        ]
        intent = [
            "src/minimal_agent/capability_facts/intents.py",
            "src/minimal_agent/capability_facts/semantics.py",
            "src/minimal_agent/contracts/intents.py",
            "src/minimal_agent/contracts/intent_parameters.py",
            "src/minimal_agent/contracts/agent.py",
            "src/minimal_agent/runtime/intent_router.py",
        ]
        tool = [
            "src/minimal_agent/capability_facts/tools.py",
            "src/minimal_agent/contracts/tools.py",
            "src/minimal_agent/contracts/intent_parameters.py",
            "src/minimal_agent/runtime/tool_registry.py",
            "src/minimal_agent/runtime/tool_binding.py",
            "examples/full_tool_fixture/__init__.py",
            "examples/full_tool_fixture/contracts.py",
            "examples/full_tool_fixture/results.py",
            "examples/full_tool_fixture/environment.py",
        ]
        modules = {
            "agent_orchestrator": ["agent.py", "intent_router.py"],
            "model_gateway": ["model_client.py", "prompts.py"],
            "intent_router": ["intent_router.py", "prompts.py"],
            "tool_loop": ["agent.py", "tool_registry.py"],
            "tool_registry": ["tool_registry.py", "tool_binding.py"],
            "execution_guard": ["agent.py", "tool_registry.py"],
            "observability": ["trace.py", "agent.py"],
        }
        agent = [
            "src/minimal_agent/versions.py",
            "src/minimal_agent/runtime/prompts.py",
            "src/minimal_agent/contracts/agent.py",
            "src/minimal_agent/runtime/agent.py",
        ]
        evidence = [
            "src/minimal_agent/capability_facts/evidence.py",
            "src/minimal_agent/runtime/trace.py",
            "src/minimal_agent/runtime/agent.py",
            "src/minimal_agent/contracts/agent.py",
        ]
        module_common = [
            "src/minimal_agent/capability_facts/modules.py",
            "src/minimal_agent/contracts/intents.py",
            "src/minimal_agent/contracts/agent.py",
            "examples/full_tool_fixture/contracts.py",
        ]
        module_sources = {
            key: module_common + ["src/minimal_agent/runtime/" + name for name in names]
            for key, names in modules.items()
        }
        all_paths = sorted(
            set(
                common
                + intent
                + tool
                + agent
                + evidence
                + [path for paths in module_sources.values() for path in paths]
            )
        )
        loaded = {}
        for path in all_paths:
            name = path.removeprefix("src/").removesuffix(".py").replace("/", ".")
            name = name.removesuffix(".__init__")
            loaded[path] = importlib.import_module(name)
        sources = bound_module_sources(source_root, loaded)
        adapter = (
            self.adapter
            if self.adapter is not None
            else MiniAgentCapabilityAdapter(
                build_default_intent_registry(), create_registry()
            )
        )
        if type(adapter) is not MiniAgentCapabilityAdapter:
            raise ValueError(
                "full fixture collector requires MiniAgentCapabilityAdapter; "
                "custom adapters need their own collector"
            )
        configured_origins = {}
        configured_modules = {}
        for fact_id, implementations in adapter.fact_implementations().items():
            configured_origins[fact_id] = []
            for implementation in implementations:
                module = inspect.getmodule(implementation)
                origin = getattr(module, "__file__", None)
                if not origin:
                    raise ValueError(
                        f"configured implementation has no source module: {fact_id}"
                    )
                try:
                    relative = (
                        Path(origin)
                        .resolve(strict=True)
                        .relative_to(source_root.resolve(strict=True))
                        .as_posix()
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"configured implementation outside source root: {fact_id}"
                    ) from exc
                configured_modules[relative] = module
                configured_origins[fact_id].append(relative)
        configured_sources = bound_module_sources(source_root, configured_modules)
        for path, source in configured_sources.items():
            if path in sources and source != sources[path]:
                raise ValueError(f"source changed during collection: {path}")
        sources.update(configured_sources)
        document = AdapterCollector(adapter).collect(source_root)
        origins = {}
        groups = {"agent": agent, "intent": intent, "tool": tool, "evidence": evidence}
        for key in document.fact_index():
            kind, identifier = key.split(".", 1)
            paths = module_sources[identifier] if kind == "module" else groups[kind]
            origins[key] = sorted(set(common + paths + configured_origins.get(key, [])))
        payload = document.model_dump(mode="json")
        payload["sources"] = {
            path: sources[path].model_dump(mode="json")
            for path in sorted({p for paths in origins.values() for p in paths})
        }
        payload["origins"] = origins
        result = FactDocument.model_validate(payload)
        check_sources(result, source_root)
        return result


def create() -> MiniAgentCollector:
    return MiniAgentCollector()
