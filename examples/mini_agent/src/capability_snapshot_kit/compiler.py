"""Compile portable Capability Specs and Agent Facts into v3 snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, TypeVar

from capability_snapshot_kit.adapter import CapabilityAdapterV3
from capability_snapshot_kit.bundle import (
    CapabilityBundleV3,
    calculate_capability_bundle_sha256_v3,
    reference_for_snapshot_v3,
)
from capability_snapshot_kit.facts import (
    AgentFactsV3,
    EvidenceFactV3,
    IntentFactV3,
    ModuleFactV3,
    ToolFactV3,
)
from capability_snapshot_kit.hashing import calculate_snapshot_sha256, sha256_json
from capability_snapshot_kit.models import (
    AgentSnapshotV3,
    BoundarySnapshotV3,
    CapabilityClaimV3,
    CapabilityProviderV3,
    CapabilityRequirementV3,
    ChainNodeV3,
    ChainSnapshotV3,
    EvidenceSnapshotV3,
    IntentSnapshotV3,
    ModuleSnapshotV3,
    ScopeSnapshotV3,
    SnapshotReferenceV3,
    SnapshotV3,
    SupportStatusV3,
    ToolSnapshotV3,
)
from capability_snapshot_kit.spec_models import (
    CapabilitySpecPackV3,
    RequirementSpecV3,
    SpecProviderV3,
)
from capability_snapshot_kit.versions import SNAPSHOT_FORMAT_VERSION_V3

Fact = TypeVar("Fact", ModuleFactV3, IntentFactV3, ToolFactV3, EvidenceFactV3)
SnapshotModel = TypeVar(
    "SnapshotModel",
    AgentSnapshotV3,
    ModuleSnapshotV3,
    IntentSnapshotV3,
    ToolSnapshotV3,
    ScopeSnapshotV3,
    ChainSnapshotV3,
    EvidenceSnapshotV3,
    BoundarySnapshotV3,
)


class CapabilityCompilationErrorV3(ValueError):
    """One or more deterministic compilation diagnostics."""

    def __init__(self, diagnostics: Iterable[str]) -> None:
        self.diagnostics = tuple(sorted(set(diagnostics)))
        super().__init__("; ".join(self.diagnostics))


class _CompilationContext:
    def __init__(
        self,
        specs: CapabilitySpecPackV3,
        adapter: CapabilityAdapterV3,
    ) -> None:
        self.specs = specs
        self.agent = adapter.agent_facts()
        self.modules = _index(adapter.module_facts(), "module_id", "module")
        self.intents = _index(adapter.intent_facts(), "intent_id", "intent")
        self.tools = _index(adapter.tool_facts(), "tool_name", "tool")
        self.evidence = _index(adapter.evidence_facts(), "evidence_id", "evidence")
        self.roles: dict[str, list[ModuleFactV3]] = {}
        for module in self.modules.values():
            for role in module.roles:
                self.roles.setdefault(role, []).append(module)
        for values in self.roles.values():
            values.sort(key=lambda item: item.module_id)

    def binding(self, key: str) -> str:
        try:
            return self.agent.runtime_bindings[key]
        except KeyError as exc:
            raise CapabilityCompilationErrorV3(
                [f"missing runtime binding: {key}"]
            ) from exc

    def role_modules(self, role: str, *, singular: bool) -> tuple[ModuleFactV3, ...]:
        values = tuple(self.roles.get(role, ()))
        if not values:
            raise CapabilityCompilationErrorV3([f"missing module role: {role}"])
        if singular and len(values) != 1:
            ids = [f"module.{item.module_id}" for item in values]
            raise CapabilityCompilationErrorV3(
                [f"ambiguous module role {role}: {ids}"]
            )
        return values

    def role_ids(self, roles: Iterable[str]) -> list[str]:
        result: list[str] = []
        for role in roles:
            for module in self.role_modules(role, singular=False):
                snapshot_id = f"module.{module.module_id}"
                if snapshot_id not in result:
                    result.append(snapshot_id)
        return result


def _index(
    values: tuple[Fact, ...],
    attribute: str,
    label: str,
) -> dict[str, Fact]:
    result: dict[str, Fact] = {}
    for value in values:
        key = str(getattr(value, attribute))
        if key in result:
            raise CapabilityCompilationErrorV3([f"duplicate {label} fact: {key}"])
        result[key] = value
    return result


def _finish(model: type[SnapshotModel], payload: dict[str, Any]) -> SnapshotModel:
    payload["snapshot_sha256"] = calculate_snapshot_sha256(payload)
    return model.model_validate(payload)


def _refs(
    snapshots: Mapping[str, SnapshotV3],
    ids: Iterable[str],
) -> list[SnapshotReferenceV3]:
    try:
        return [
            reference_for_snapshot_v3(snapshots[snapshot_id]) for snapshot_id in ids
        ]
    except KeyError as exc:
        raise CapabilityCompilationErrorV3(
            [f"missing referenced snapshot: {exc.args[0]}"]
        ) from exc


def _validate_claims(
    claims: Iterable[CapabilityClaimV3],
    evidence: Mapping[str, EvidenceSnapshotV3],
    owner: str,
) -> None:
    diagnostics: list[str] = []
    for claim in claims:
        if claim.support_status != SupportStatusV3.SUPPORTED:
            continue
        for evidence_id in claim.evidence_ids:
            snapshot = evidence.get(evidence_id)
            if snapshot is None:
                diagnostics.append(
                    f"{owner}: supported {claim.capability_key} references missing "
                    f"{evidence_id}"
                )
            elif snapshot.availability.support_status != SupportStatusV3.SUPPORTED:
                diagnostics.append(
                    f"{owner}: supported {claim.capability_key} uses unavailable "
                    f"{evidence_id}"
                )
    if diagnostics:
        raise CapabilityCompilationErrorV3(diagnostics)


def _build_evidence(
    context: _CompilationContext,
) -> dict[str, EvidenceSnapshotV3]:
    snapshots: dict[str, EvidenceSnapshotV3] = {}
    for snapshot_id, spec in sorted(context.specs.evidence.items()):
        local_id = snapshot_id.split(".", 1)[1]
        fact = context.evidence.get(local_id)
        if fact is None:
            producer_ids: list[str] = []
            timing = "not declared by the Agent adapter"
            payload_schema: dict[str, Any] = {"type": "object"}
            interface = "unavailable"
            events: list[str] = []
            paths = spec.applicable_result_paths
            availability = CapabilityClaimV3(
                capability_key=f"evidence.{local_id}_available",
                support_status="unknown",
                evidence_ids=[],
                reason="The Agent adapter did not declare this Evidence interface.",
            )
        else:
            producer_ids = context.role_ids(fact.producer_module_roles)
            timing = fact.production_timing
            payload_schema = fact.payload_schema
            interface = fact.observation_interface
            events = list(fact.event_types)
            paths = list(fact.applicable_result_paths)
            availability = fact.availability
        definition = {
            "description": spec.description,
            "producers": producer_ids,
            "timing": timing,
            "payload_schema": payload_schema,
            "interface": interface,
            "events": events,
            "required": spec.required,
            "paths": paths,
            "availability": availability.model_dump(mode="json"),
        }
        payload = {
            "snapshot_id": snapshot_id,
            "snapshot_type": "evidence",
            "snapshot_format_version": SNAPSHOT_FORMAT_VERSION_V3,
            "contract_version": context.agent.contract_version,
            "evidence_id": local_id,
            "description": spec.description,
            "producer_module_ids": producer_ids,
            "consumer_roles": spec.consumer_roles,
            "production_timing": timing,
            "payload_schema": payload_schema,
            "observation_interface": interface,
            "event_types": events,
            "required": spec.required,
            "applicable_result_paths": paths,
            "availability": availability.model_dump(mode="json"),
            "source_hashes": {"catalog_definition_sha256": sha256_json(definition)},
            "snapshot_sha256": "0" * 64,
        }
        snapshots[snapshot_id] = _finish(EvidenceSnapshotV3, payload)
    return snapshots


def _build_tools(
    context: _CompilationContext,
    evidence: Mapping[str, EvidenceSnapshotV3],
) -> dict[str, ToolSnapshotV3]:
    snapshots: dict[str, ToolSnapshotV3] = {}
    for tool_name, fact in sorted(context.tools.items()):
        claims = list(fact.capabilities)
        _validate_claims(claims, evidence, f"tool.{tool_name}")
        safety = {
            "permission_requirements": fact.permission_requirements,
            "requires_confirmation": fact.requires_confirmation,
            "risk_level": fact.risk_level,
            "side_effects": fact.side_effects,
            "idempotency_rules": fact.idempotency_rules,
        }
        payload = {
            "snapshot_id": f"tool.{tool_name}",
            "snapshot_type": "tool",
            "snapshot_format_version": SNAPSHOT_FORMAT_VERSION_V3,
            "contract_version": fact.contract_version,
            "tool_name": tool_name,
            "tool_version": fact.tool_version,
            "description": fact.description,
            "implementation_profile": fact.implementation_profile,
            "registered": True,
            "function_schema": fact.function_schema,
            "parameter_semantics": fact.parameter_semantics,
            "combination_rules": fact.combination_rules,
            "batch_behavior": fact.batch_behavior,
            "preconditions": fact.preconditions,
            "result_protocols": fact.result_protocols,
            **safety,
            "retry_policy": fact.retry_policy,
            "simulation_protocol": fact.simulation_protocol,
            "simulation_capabilities": fact.simulation_capabilities,
            "observation_interfaces": fact.observation_interfaces,
            "capabilities": [item.model_dump(mode="json") for item in claims],
            "source_hashes": {
                "function_schema_sha256": sha256_json(fact.function_schema),
                "execution_contract_sha256": sha256_json(
                    {
                        "parameter_semantics": fact.parameter_semantics,
                        "result_protocols": fact.result_protocols,
                        "safety": safety,
                    }
                ),
            },
            "snapshot_sha256": "0" * 64,
        }
        snapshots[payload["snapshot_id"]] = _finish(ToolSnapshotV3, payload)
    return snapshots


def _build_intents(
    context: _CompilationContext,
    tools: Mapping[str, ToolSnapshotV3],
    evidence: Mapping[str, EvidenceSnapshotV3],
) -> dict[str, IntentSnapshotV3]:
    snapshots: dict[str, IntentSnapshotV3] = {}
    for intent_id, fact in sorted(context.intents.items()):
        module = context.role_modules(fact.module_role, singular=True)[0]
        tool_id = (
            f"tool.{fact.required_tool_name}"
            if fact.required_tool_name is not None
            else None
        )
        tool_refs = (
            [reference_for_snapshot_v3(tools[tool_id])]
            if tool_id is not None and tool_id in tools
            else []
        )
        claims = list(fact.capabilities)
        _validate_claims(claims, evidence, f"intent.{intent_id}")
        refs_json = [item.model_dump(mode="json") for item in tool_refs]
        payload = {
            "snapshot_id": f"intent.{intent_id}",
            "snapshot_type": "intent",
            "snapshot_format_version": SNAPSHOT_FORMAT_VERSION_V3,
            "contract_version": fact.contract_version,
            "capability_id": intent_id,
            "module_id": f"module.{module.module_id}",
            "parameters_schema": fact.parameters_schema,
            "parameter_semantics": fact.parameter_semantics,
            "decision_rules": fact.decision_rules,
            "semantic_rules": fact.semantic_rules,
            "required_tool_name": fact.required_tool_name,
            "capabilities": [item.model_dump(mode="json") for item in claims],
            "tool_refs": refs_json,
            "source_hashes": {
                "parameters_schema_sha256": sha256_json(fact.parameters_schema),
                "intent_rules_sha256": sha256_json(
                    {
                        "parameter_semantics": fact.parameter_semantics,
                        "decision_rules": fact.decision_rules,
                        "semantic_rules": fact.semantic_rules,
                    }
                ),
                "tool_refs_sha256": sha256_json(refs_json),
            },
            "snapshot_sha256": "0" * 64,
        }
        snapshots[payload["snapshot_id"]] = _finish(IntentSnapshotV3, payload)
    return snapshots


def _build_modules(
    context: _CompilationContext,
    intents: Mapping[str, IntentSnapshotV3],
    tools: Mapping[str, ToolSnapshotV3],
    evidence: Mapping[str, EvidenceSnapshotV3],
) -> dict[str, ModuleSnapshotV3]:
    snapshots: dict[str, ModuleSnapshotV3] = {}
    known: dict[str, SnapshotV3] = {**intents, **tools}
    for module_id, fact in sorted(context.modules.items()):
        claims = list(fact.capabilities)
        _validate_claims(claims, evidence, f"module.{module_id}")
        intent_refs = _refs(known, fact.intent_ids)
        tool_refs = _refs(known, fact.tool_ids)
        child_ids = {
            "intents": [item.snapshot_id for item in intent_refs],
            "tools": [item.snapshot_id for item in tool_refs],
        }
        payload = {
            "snapshot_id": f"module.{module_id}",
            "snapshot_type": "module",
            "snapshot_format_version": SNAPSHOT_FORMAT_VERSION_V3,
            "contract_version": fact.contract_version,
            "module_id": module_id,
            "responsibility": fact.responsibility,
            "component_versions": fact.component_versions,
            "input_schema": fact.input_schema,
            "output_schema": fact.output_schema,
            "capabilities": [item.model_dump(mode="json") for item in claims],
            "module_refs": [],
            "intent_refs": [item.model_dump(mode="json") for item in intent_refs],
            "tool_refs": [item.model_dump(mode="json") for item in tool_refs],
            "execution_boundary_ids": list(fact.execution_boundary_ids),
            "trace_event_types": list(fact.trace_event_types),
            "source_hashes": {
                "capabilities_sha256": sha256_json(
                    [item.model_dump(mode="json") for item in claims]
                ),
                "children_sha256": sha256_json(child_ids),
            },
            "snapshot_sha256": "0" * 64,
        }
        snapshots[payload["snapshot_id"]] = _finish(ModuleSnapshotV3, payload)
    return snapshots


def _provider(
    context: _CompilationContext,
    provider: SpecProviderV3,
) -> CapabilityProviderV3:
    if provider.role == "module_role":
        module = context.role_modules(provider.module_role or "", singular=True)[0]
        return CapabilityProviderV3(
            role="snapshot",
            snapshot_id=f"module.{module.module_id}",
        )
    return CapabilityProviderV3(role=provider.role, snapshot_id=None)


def _requirement(
    context: _CompilationContext,
    spec: RequirementSpecV3,
) -> CapabilityRequirementV3:
    return CapabilityRequirementV3(
        requirement_id=spec.requirement_id,
        capability_key=spec.capability_key,
        provider=_provider(context, spec.provider),
        mandatory=spec.mandatory,
        evidence_ids=spec.evidence_ids,
    )


def _build_boundaries(
    context: _CompilationContext,
    modules: Mapping[str, ModuleSnapshotV3],
) -> dict[str, BoundarySnapshotV3]:
    snapshots: dict[str, BoundarySnapshotV3] = {}
    all_module_ids = set(modules)
    for snapshot_id, spec in sorted(context.specs.boundaries.items()):
        local_id = snapshot_id.split(".", 1)[1]
        entry = context.binding(spec.entry_binding)
        stop = context.binding(spec.stop_binding)
        allowed = context.role_ids(spec.module_roles)
        prohibited = sorted(all_module_ids - set(allowed))
        definition = {
            "entry": entry,
            "stop": stop,
            "allowed": sorted(allowed),
            "prohibited": prohibited,
            "evidence_ids": spec.evidence_ids,
        }
        payload = {
            "snapshot_id": snapshot_id,
            "snapshot_type": "boundary",
            "snapshot_format_version": SNAPSHOT_FORMAT_VERSION_V3,
            "contract_version": context.agent.contract_version,
            "boundary_id": local_id,
            "description": spec.description,
            "entry_node": entry,
            "stop_node": stop,
            "allowed_module_ids": sorted(allowed),
            "prohibited_module_ids": prohibited,
            "terminal_condition": spec.terminal_condition_template.format(
                stop_node=stop
            ),
            "evidence_ids": spec.evidence_ids,
            "no_overrun_rule": spec.no_overrun_rule_template.format(stop_node=stop),
            "source_hashes": {"catalog_definition_sha256": sha256_json(definition)},
            "snapshot_sha256": "0" * 64,
        }
        snapshots[snapshot_id] = _finish(BoundarySnapshotV3, payload)
    return snapshots


def _build_scopes(
    context: _CompilationContext,
    modules: Mapping[str, ModuleSnapshotV3],
    evidence: Mapping[str, EvidenceSnapshotV3],
    boundaries: Mapping[str, BoundarySnapshotV3],
) -> dict[str, ScopeSnapshotV3]:
    snapshots: dict[str, ScopeSnapshotV3] = {}
    all_module_ids = set(modules)
    for snapshot_id, spec in sorted(context.specs.scopes.items()):
        local_id = snapshot_id.split(".", 1)[1]
        allowed = context.role_ids(spec.module_roles)
        prohibited = sorted(all_module_ids - set(allowed))
        requirements = [_requirement(context, item) for item in spec.requirements]
        definition = {
            "inputs": spec.inputs,
            "outputs": spec.outputs,
            "entry": context.binding(spec.entrypoint_binding),
            "stop": context.binding(spec.stop_binding),
            "modules": allowed,
            "evidence": spec.evidence_ids,
            "requirements": [item.model_dump(mode="json") for item in requirements],
        }
        payload = {
            "snapshot_id": snapshot_id,
            "snapshot_type": "scope",
            "snapshot_format_version": SNAPSHOT_FORMAT_VERSION_V3,
            "contract_version": context.agent.contract_version,
            "scope_id": local_id,
            "description": spec.description,
            "inputs": spec.inputs,
            "outputs": spec.outputs,
            "entrypoint": definition["entry"],
            "stop_boundary": definition["stop"],
            "allowed_module_ids": allowed,
            "prohibited_module_ids": prohibited,
            "module_refs": [
                item.model_dump(mode="json") for item in _refs(modules, allowed)
            ],
            "evidence_refs": [
                item.model_dump(mode="json")
                for item in _refs(evidence, spec.evidence_ids)
            ],
            "boundary_refs": [
                reference_for_snapshot_v3(boundaries[spec.boundary_id]).model_dump(
                    mode="json"
                )
            ],
            "requirements": definition["requirements"],
            "completion_condition": spec.completion_condition,
            "unresolved_behavior": spec.unresolved_behavior,
            "source_hashes": {"catalog_definition_sha256": sha256_json(definition)},
            "snapshot_sha256": "0" * 64,
        }
        snapshots[snapshot_id] = _finish(ScopeSnapshotV3, payload)
    return snapshots


def _build_chains(
    context: _CompilationContext,
    modules: Mapping[str, ModuleSnapshotV3],
    evidence: Mapping[str, EvidenceSnapshotV3],
    boundaries: Mapping[str, BoundarySnapshotV3],
) -> dict[str, ChainSnapshotV3]:
    snapshots: dict[str, ChainSnapshotV3] = {}
    for snapshot_id, spec in sorted(context.specs.chains.items()):
        local_id = snapshot_id.split(".", 1)[1]
        module_ids = context.role_ids(spec.module_roles)
        nodes = [
            ChainNodeV3(
                node_id=item.node_id,
                capability_key=item.capability_key,
                provider=_provider(context, item.provider),
                depends_on=item.depends_on,
                inputs=item.inputs,
                outputs=item.outputs,
                stop_conditions=item.stop_conditions,
                state_reads=item.state_reads,
                state_writes=item.state_writes,
            )
            for item in spec.nodes
        ]
        requirements = [_requirement(context, item) for item in spec.requirements]
        definition = {
            "nodes": [item.model_dump(mode="json") for item in nodes],
            "modules": module_ids,
            "evidence": spec.evidence_ids,
            "requirements": [item.model_dump(mode="json") for item in requirements],
            "branches": spec.branches,
        }
        payload = {
            "snapshot_id": snapshot_id,
            "snapshot_type": "chain",
            "snapshot_format_version": SNAPSHOT_FORMAT_VERSION_V3,
            "contract_version": context.agent.contract_version,
            "chain_id": local_id,
            "description": spec.description,
            "nodes": definition["nodes"],
            "module_refs": [
                item.model_dump(mode="json") for item in _refs(modules, module_ids)
            ],
            "evidence_refs": [
                item.model_dump(mode="json")
                for item in _refs(evidence, spec.evidence_ids)
            ],
            "boundary_refs": [
                reference_for_snapshot_v3(boundaries[spec.boundary_id]).model_dump(
                    mode="json"
                )
            ],
            "requirements": definition["requirements"],
            "branches": spec.branches,
            "completion_condition": spec.completion_condition,
            "source_hashes": {"catalog_definition_sha256": sha256_json(definition)},
            "snapshot_sha256": "0" * 64,
        }
        snapshots[snapshot_id] = _finish(ChainSnapshotV3, payload)
    return snapshots


def _aggregate_agent_capabilities(
    specs: CapabilitySpecPackV3,
    modules: Mapping[str, ModuleSnapshotV3],
) -> list[CapabilityClaimV3]:
    claims_by_key: dict[str, list[CapabilityClaimV3]] = {}
    for module in modules.values():
        for claim in module.capabilities:
            claims_by_key.setdefault(claim.capability_key, []).append(claim)
    result: list[CapabilityClaimV3] = []
    for parent_key, required_keys in specs.protocol.agent_capability_groups.items():
        children = [
            claim for key in required_keys for claim in claims_by_key.get(key, [])
        ]
        missing = [key for key in required_keys if key not in claims_by_key]
        unsupported = [
            claim
            for claim in children
            if claim.support_status == SupportStatusV3.UNSUPPORTED
        ]
        unknown = [
            claim
            for claim in children
            if claim.support_status == SupportStatusV3.UNKNOWN
        ]
        if unsupported:
            status = SupportStatusV3.UNSUPPORTED
            reason = "Mandatory capability is unsupported: " + ", ".join(
                sorted(claim.capability_key for claim in unsupported)
            )
            evidence_ids: list[str] = []
        elif missing or unknown:
            status = SupportStatusV3.UNKNOWN
            unresolved = [*missing, *(claim.capability_key for claim in unknown)]
            reason = "Mandatory capability is unresolved: " + ", ".join(
                sorted(unresolved)
            )
            evidence_ids = []
        else:
            status = SupportStatusV3.SUPPORTED
            reason = None
            evidence_ids = sorted(
                {
                    evidence_id
                    for claim in children
                    for evidence_id in claim.evidence_ids
                }
            )
        result.append(
            CapabilityClaimV3(
                capability_key=parent_key,
                support_status=status,
                evidence_ids=evidence_ids,
                reason=reason,
            )
        )
    return result


def _build_agent(
    facts: AgentFactsV3,
    specs: CapabilitySpecPackV3,
    modules: Mapping[str, ModuleSnapshotV3],
    intents: Mapping[str, IntentSnapshotV3],
    tools: Mapping[str, ToolSnapshotV3],
    scopes: Mapping[str, ScopeSnapshotV3],
    chains: Mapping[str, ChainSnapshotV3],
    evidence: Mapping[str, EvidenceSnapshotV3],
    boundaries: Mapping[str, BoundarySnapshotV3],
) -> AgentSnapshotV3:
    groups: dict[str, list[SnapshotReferenceV3]] = {
        "module_refs": _refs(modules, sorted(modules)),
        "intent_refs": _refs(intents, sorted(intents)),
        "tool_refs": _refs(tools, sorted(tools)),
        "scope_refs": _refs(scopes, sorted(scopes)),
        "chain_refs": _refs(chains, sorted(chains)),
        "evidence_refs": _refs(evidence, sorted(evidence)),
        "boundary_refs": _refs(boundaries, sorted(boundaries)),
    }
    references = [item for values in groups.values() for item in values]
    bundle_hash = calculate_capability_bundle_sha256_v3(references)
    capabilities = _aggregate_agent_capabilities(specs, modules)
    payload = {
        "snapshot_id": f"agent.{facts.agent_id}",
        "snapshot_type": "agent",
        "snapshot_format_version": SNAPSHOT_FORMAT_VERSION_V3,
        "contract_version": facts.contract_version,
        "agent_id": facts.agent_id,
        "agent_version": facts.agent_version,
        "entrypoints": facts.entrypoints,
        "input_schema": facts.input_schema,
        "output_schema": facts.output_schema,
        "capabilities": [item.model_dump(mode="json") for item in capabilities],
        **{
            name: [item.model_dump(mode="json") for item in values]
            for name, values in groups.items()
        },
        "runtime_versions": facts.runtime_versions,
        "capability_bundle_sha256": bundle_hash,
        "source_hashes": {
            "children_sha256": bundle_hash,
            "capabilities_sha256": sha256_json(
                [item.model_dump(mode="json") for item in capabilities]
            ),
        },
        "snapshot_sha256": "0" * 64,
    }
    return _finish(AgentSnapshotV3, payload)


def compile_capability_bundle_v3(
    specs: CapabilitySpecPackV3,
    adapter: CapabilityAdapterV3,
) -> CapabilityBundleV3:
    context = _CompilationContext(specs, adapter)
    evidence = _build_evidence(context)
    tools = _build_tools(context, evidence)
    intents = _build_intents(context, tools, evidence)
    modules = _build_modules(context, intents, tools, evidence)
    boundaries = _build_boundaries(context, modules)
    scopes = _build_scopes(context, modules, evidence, boundaries)
    chains = _build_chains(context, modules, evidence, boundaries)
    agent = _build_agent(
        context.agent,
        specs,
        modules,
        intents,
        tools,
        scopes,
        chains,
        evidence,
        boundaries,
    )
    return CapabilityBundleV3(
        agent=agent,
        modules=modules,
        intents=intents,
        tools=tools,
        scopes=scopes,
        chains=chains,
        evidence=evidence,
        boundaries=boundaries,
    )


def compile_capability_snapshot_v3(
    snapshot_id: str,
    specs: CapabilitySpecPackV3,
    adapter: CapabilityAdapterV3,
) -> SnapshotV3:
    bundle = compile_capability_bundle_v3(specs, adapter)
    snapshots = {
        bundle.agent.snapshot_id: bundle.agent,
        **{item.snapshot_id: item for item in bundle.child_snapshots},
    }
    try:
        return snapshots[snapshot_id]
    except KeyError as exc:
        raise ValueError(
            f"snapshot {snapshot_id!r} is not exportable for this configuration"
        ) from exc
