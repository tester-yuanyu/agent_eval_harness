"""Collect real builtin registrations without starting an Agent or executing tools.

The explicit offline profile is a construction profile, not a running deployment.
Execution claims remain unknown, even when a tool is registered successfully.
"""

# Kit 0.1.0 has inline annotations but no py.typed marker; keep other checks enabled.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import inspect
import platform
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Literal, TypedDict

from capability_snapshot_kit import (
    AgentFacts,
    CapabilityClaim,
    EvidenceFact,
    IntentFact,
    ModuleFact,
    SupportStatus,
    ToolFact,
)
from capability_snapshot_kit.hashing import sha256_json
from capability_snapshot_kit.ingestion import FactDocument
from capability_snapshot_kit.ingestion.sources import source_reference
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, StrictBool, TypeAdapter

import nanobot
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.exec_session import ExecSessionManager
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ToolsConfig
from nanobot.cron.service import CronService
from nanobot.sdk.types import RunResult
from nanobot.session.manager import SessionManager

DEFAULT_PROFILE = "integrations/capability_snapshot/offline.json"
CONTRACT = "nanobot-collector-v1"
EXECUTION_UNKNOWN = (
    "Offline construction only: no model call, tool execution or external service verification."
)


class OfflineProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    file_tools: StrictBool = True
    exec_tool: StrictBool = True
    web_tools: StrictBool = True


class _BuiltinLoader(ToolLoader):
    def _discover_plugins(self) -> dict[str, type[Tool]]:
        # Explicitly limit this profile to repository-owned builtin classes.
        return {}


# `class` is a JSON key, and cannot be a Python class-body identifier.
ToolClassRecord = TypedDict(
    "ToolClassRecord", {"class": str, "source": str, "status": str, "tool_names": list[str]},
)


def _claim(key: str, *, supported: bool = False, reason: str | None = None) -> CapabilityClaim:
    return CapabilityClaim(
        capability_key=key,
        support_status=SupportStatus.SUPPORTED if supported else SupportStatus.UNKNOWN,
        evidence_ids=["evidence.final_response"] if supported else [],
        reason=None if supported else reason or EXECUTION_UNKNOWN,
    )


def _class_path(cls: type, root: Path) -> str:
    filename = inspect.getsourcefile(cls)
    if filename is None:
        raise ValueError(f"No source file for {cls.__name__}")
    try:
        return Path(filename).resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"Class {cls.__name__} comes from another checkout") from exc


class NanobotCollector:
    def __init__(self, *, profile_path: str = DEFAULT_PROFILE):
        self.profile_path = profile_path
        self.coverage: dict[str, Any] = {}

    def collect(self, source_root: Path) -> FactDocument:
        self.coverage = {}
        root = Path(source_root).resolve()
        if Path(nanobot.__file__).resolve().parent.parent != root:
            raise ValueError("source_root must match the imported nanobot checkout")
        # The kit checks containment, symlink escapes, size and UTF-8 before reading.
        profile_source = source_reference(root, self.profile_path, kind="config")
        profile = OfflineProfile.model_validate_json(
            (root / profile_source.path).read_text(encoding="utf-8")
        )
        config = ToolsConfig()
        config.file.enable = profile.file_tools
        config.exec.enable = profile.exec_tool
        config.web.enable = profile.web_tools
        config.restrict_to_workspace = True
        config.my.enable = False
        config.cli_apps.enable = False
        config.image_generation.enabled = False
        version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]

        # SessionManager writes namespace metadata on construction. Keep all of it
        # outside both the source tree and the user's personal nanobot workspace.
        with tempfile.TemporaryDirectory(prefix="nanobot-snapshot-") as directory:
            scratch = Path(directory)
            workspace = scratch / "workspace"
            workspace.mkdir()
            bus = MessageBus()
            ctx = ToolContext(
                config=config,
                workspace=str(workspace),
                bus=bus,
                sessions=SessionManager(workspace, sessions_root=scratch / "sessions"),
                cron_service=CronService(scratch / "cron" / "jobs.json"),
                exec_session_manager=ExecSessionManager(),
                subagent_manager=SubagentManager(
                    workspace=workspace, bus=bus, max_tool_result_chars=16000,
                    tools_config=config, restrict_to_workspace=True,
                ),
            )
            registry = ToolRegistry()
            loader = _BuiltinLoader()
            errors: list[str] = []
            sink = logger.add(
                lambda message: errors.append(str(message)), level="ERROR",
                filter=lambda record: record["name"] == "nanobot.agent.tools.loader",
            )
            try:
                classes = loader.discover()
                registered = loader.load(ctx, registry)
            finally:
                logger.remove(sink)
            if errors:
                raise RuntimeError("Tool discovery/registration failed: " + "\n".join(errors))
            if len(registered) != len(set(registered)):
                raise RuntimeError("Tool registration contains duplicate names")
            definitions = registry.get_definitions()
            tools = tuple(self._tool_fact(schema, registry, version) for schema in definitions)
            class_rows: list[ToolClassRecord] = []
            for cls in classes:
                in_scope = "core" in getattr(cls, "_scopes", {"core"})
                enabled = in_scope and cls.enabled(ctx)
                names = sorted(name for name in registry.tool_names
                               if type(registry.get(name)) is cls)
                if enabled and not names:
                    raise RuntimeError(f"Tool registration missing enabled class: {cls.__name__}")
                class_rows.append({
                    "class": cls.__name__, "source": _class_path(cls, root),
                    "status": "registered" if names else "disabled" if in_scope else "out_of_scope",
                    "tool_names": names,
                })
            tool_paths = {
                tool.tool_name: _class_path(type(registry.get(tool.tool_name)), root)
                for tool in tools
            }
            document = self._document(
                root, profile, config, version, tools, tool_paths,
                {row["source"] for row in class_rows},
            )
            self.coverage = self._coverage(profile, document, class_rows)
            return document

    @staticmethod
    def _tool_fact(schema: dict[str, Any], registry: ToolRegistry, version: str) -> ToolFact:
        name = schema["function"]["name"]
        tool = registry.get(name)
        if tool is None:
            raise RuntimeError(f"Tool registration disappeared: {name}")
        return ToolFact(
            tool_name=name, contract_version=CONTRACT, tool_version=version,
            description=tool.description, implementation_profile="production", registered=True,
            function_schema=schema,
            parameter_semantics={
                key: value.get("description", "See the exact function schema.")
                for key, value in tool.parameters.get("properties", {}).items()
            },
            combination_rules={"exclusive": tool.exclusive,
                               "concurrency_safe": tool.concurrency_safe},
            batch_behavior={"declared": False},
            preconditions=[
                "Registration is limited to the named offline profile.",
                "Execution requires tool-specific services, request context and permissions.",
            ],
            result_protocols={
                "registry_return_type": "Any; tool-specific return contract",
                "error_marker": "ToolResult.is_error; see ToolRegistry.execute",
            },
            permission_requirements=["See implementation-specific guards; not audited here."],
            requires_confirmation=False,
            risk_level="medium" if tool.read_only else "high",
            idempotency_rules={"status": "unknown"},
            side_effects=["Not audited; read_only declaration=" + str(tool.read_only)],
            retry_policy={"status": "unknown"}, simulation_protocol=None,
            simulation_capabilities=[],
            observation_interfaces=["ToolRegistry.get_definitions", "ToolRegistry.execute"],
            # Registration and exact schema are structural ToolFact fields. Do not
            # use the conversation response as evidence of tool behavior.
            capabilities=(_claim("tool.execution"),),
        )

    def _document(
        self, root: Path, profile: OfflineProfile, config: ToolsConfig, version: str,
        tools: tuple[ToolFact, ...], tool_paths: dict[str, str], discovered_sources: set[str],
    ) -> FactDocument:
        input_schema = {
            "type": "object", "required": ["message"],
            "properties": {"message": {"type": "string"},
                           "session_key": {"type": "string", "default": "sdk:default"},
                           "ephemeral": {"type": "boolean", "default": False}},
            "description": "Common Nanobot.run arguments; additional SDK keyword arguments allowed.",
        }
        output_schema = TypeAdapter(RunResult).json_schema()
        module_paths = {
            "dialogue": ["nanobot/nanobot.py", "nanobot/agent/loop.py", "nanobot/agent/runner.py"],
            "observability": ["nanobot/sdk/types.py", "nanobot/sdk/streaming.py"],
            "tools": ["nanobot/agent/tools/loader.py", "nanobot/agent/tools/registry.py"],
            "memory": ["nanobot/agent/memory.py", "nanobot/session/manager.py"],
            "skills": ["nanobot/agent/skills.py", "nanobot/agent/context.py"],
            "providers": ["nanobot/providers/factory.py", "nanobot/providers/registry.py"],
            "channels": ["nanobot/channels/manager.py", "nanobot/channels/registry.py"],
            "mcp": ["nanobot/agent/tools/mcp.py"],
        }
        descriptions = {
            "dialogue": "Nanobot.run delegates to AgentLoop.process_direct and AgentRunner.",
            "observability": "SDK RunResult and stream event interfaces; no trace was executed.",
            "tools": "Builtin ToolLoader registration in the explicit offline profile.",
            "memory": "Session persistence and memory consolidation code; behavior unverified.",
            "skills": "Prompt skill loading code; inventory does not establish skill execution.",
            "providers": "Provider factory and catalog; no model provider is connected.",
            "channels": "Channel discovery and manager; no external channel is started.",
            "mcp": "Dynamic MCP integration exists in source; no server connection or tool discovery.",
        }
        module_claims = {
            "dialogue": (_claim("dialogue.respond"),),
            "observability": (_claim("result.final_response", supported=True),),
            "tools": (_claim("tool.execution"),),
            "memory": (_claim("context.inheritance"), _claim("memory.consolidation")),
            "skills": (_claim("skills.execution"),),
            "providers": (_claim("provider.inference"),),
            "channels": (_claim("channel.delivery"),),
            "mcp": (_claim("mcp.discovery"),),
        }
        modules = tuple(ModuleFact(
            module_id=name, contract_version=CONTRACT, roles=(name,),
            responsibility=descriptions[name], component_versions={"nanobot": version},
            input_schema=input_schema if name == "dialogue" else {},
            output_schema=output_schema if name in {"dialogue", "observability"} else {},
            capabilities=module_claims[name], module_ids=(),
            intent_ids=("intent.assistant",) if name == "dialogue" else (),
            tool_ids=tuple(f"tool.{tool.tool_name}" for tool in tools) if name == "tools" else (),
            execution_boundary_ids=("boundary.conversation",) if name == "dialogue" else (),
            trace_event_types=(),
        ) for name in module_paths)
        document = FactDocument(
            agent=AgentFacts(
                agent_id="nanobot", agent_version=version, contract_version=CONTRACT,
                entrypoints=["nanobot.nanobot.Nanobot.run"],
                runtime_bindings={"entrypoint.run": "nanobot.nanobot.Nanobot.run",
                                  "node.finished": "Nanobot.run returns RunResult"},
                input_schema=input_schema, output_schema=output_schema,
                runtime_versions={"nanobot": version, "python": platform.python_version(),
                                  "profile": profile.profile_id,
                                  "tools_config_sha256": sha256_json(config.model_dump(mode="json"))},
            ),
            modules=modules,
            intents=(IntentFact(
                intent_id="assistant", contract_version=CONTRACT, module_role="dialogue",
                parameters_schema=input_schema,
                parameter_semantics={"message": "User input passed to Nanobot.run."},
                decision_rules={"routing": "Model-driven; no fixed business-intent router inferred."},
                semantic_rules={"purpose": "General assistant; no business-specific competency inferred."},
                required_tool_name=None, capabilities=(_claim("dialogue.business_task"),),
            ),),
            tools=tools,
            evidence=(EvidenceFact(
                evidence_id="final_response", producer_module_roles=("observability",),
                production_timing="On successful return of Nanobot.run; exceptions may propagate.",
                payload_schema=output_schema, observation_interface="dataclasses.asdict(RunResult)",
                event_types=(), applicable_result_paths=("success",),
                availability=_claim("evidence.final_response_available", supported=True),
            ),),
        )
        common = ["integrations/capability_snapshot/collector.py", self.profile_path,
                  "nanobot/config/schema.py", "pyproject.toml"]
        origins = {
            "agent.nanobot": common + module_paths["dialogue"] + module_paths["observability"],
            "intent.assistant": common + module_paths["dialogue"],
            "evidence.final_response": common + module_paths["observability"] + ["nanobot/nanobot.py"],
        }
        for name, paths in module_paths.items():
            origins[f"module.{name}"] = common + paths
        for name, path in tool_paths.items():
            origins[f"tool.{name}"] = common + [path, "nanobot/agent/tools/base.py"] + module_paths["tools"]
        # Include excluded classes too, so the coverage census is independently inspectable.
        paths = {path for values in origins.values() for path in values}
        paths.update(discovered_sources)
        paths.update(("nanobot/agent/tools/self.py", "nanobot/agent/tools/cli_apps.py",
                      "nanobot/agent/tools/image_generation.py"))
        paths.update(path.relative_to(root).as_posix()
                     for path in (root / "nanobot/skills").glob("*/SKILL.md"))
        sources = {}
        for path in sorted(paths):
            kind: Literal["code", "config", "prompt"] = (
                "config" if path == self.profile_path or path.endswith(".toml") else
                "prompt" if path.endswith(".md") else "code"
            )
            sources[path] = source_reference(root, path, kind=kind)
        return FactDocument.model_validate({
            **document.model_dump(), "sources": sources,
            "origins": {key: sorted(set(values)) for key, values in origins.items()},
        })

    @staticmethod
    def _coverage(profile: OfflineProfile, document: FactDocument,
                  class_rows: list[ToolClassRecord]) -> dict[str, Any]:
        names = {tool.tool_name for tool in document.tools}
        registered = {name for row in class_rows for name in row["tool_names"]}
        return {
            "profile_id": profile.profile_id,
            "basis": "isolated builtin registry construction, not a running gateway",
            "execution_verified": False,
            "registered_tool_count": len(registered), "exported_tool_count": len(names),
            "missing_registered_tools": sorted(registered - names),
            "unexpected_exported_tools": sorted(names - registered),
            "tool_classes": class_rows,
            "manual_tools": [{"tool_name": "my", "source": "nanobot/agent/tools/self.py",
                              "status": "disabled", "reason": "Requires AgentLoop runtime control."}],
            "skills": [{"path": path, "sha256": source.sha256, "status": "source_only"}
                       for path, source in document.sources.items()
                       if path.startswith("nanobot/skills/")],
            "module_ids": [module.module_id for module in document.modules],
            "fact_count": len(document.fact_index()),
            "sourced_fact_count": sum(bool(document.origins.get(key)) for key in document.fact_index()),
            "limits": [
                "Registry completeness only applies to the explicit offline profile.",
                "Tool execution, model output quality, memory and business competencies are unverified.",
                "MCP servers, external tool plugins and user-installed skills are not discovered.",
                "Channels/providers are represented at subsystem level, not per-integration verification.",
                "Skill files are inventoried; their semantic abilities and requirements are not evaluated.",
                "Conversation evaluation profile does not evaluate individual tool execution.",
                "Risk levels are conservative adapter labels; confirmation/idempotency need per-tool review.",
            ],
        }


def create() -> NanobotCollector:
    return NanobotCollector()
