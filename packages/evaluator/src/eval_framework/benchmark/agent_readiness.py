"""现有 MiniAgentProvider 上的离线确定性输入驱动器。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from eval_contracts.agent_readiness import (
    AgentPlan,
    AgentReferenceContext,
    node_evidence,
)
from eval_contracts.full_readiness import ToolEvidence

from .full_readiness import fixture_class
from .operation_readiness import _snapshot


class ReferenceModel:
    def __init__(self, plan: AgentPlan):
        self.plan = plan
        self.interactions: list[dict[str, Any]] = []

    def classify_intent(self, user_input: str) -> dict[str, Any]:
        if user_input != self.plan.user_input:
            raise ValueError("reference model input drift")
        result = deepcopy(self.plan.candidate)
        self.interactions.append(
            {"method": "classify_intent", "input": user_input, "output": result}
        )
        return deepcopy(result)

    def next_tool_step(self, request):
        interaction = {
            "method": "next_tool_step",
            "input": request.model_dump(mode="json"),
        }
        self.interactions.append(interaction)
        if self.plan.fault == "model_error":
            interaction["error"] = "REFERENCE_MODEL_FAILURE"
            raise RuntimeError("REFERENCE_MODEL_FAILURE")
        if not self.plan.tool_name:
            raise AssertionError("unexpected model tool step")
        if request.tool_outputs and self.plan.fault != "repeat":
            # Final response is built from actual observed tool output.
            result = {
                "type": "message",
                "content": json.dumps(
                    request.tool_outputs[-1].output, ensure_ascii=False, sort_keys=True
                ),
            }
        else:
            result = {
                "type": "function_call",
                "call_id": f"reference-call-{request.step}",
                "name": self.plan.tool_name,
                "arguments": deepcopy(self.plan.tool_arguments),
            }
        interaction["output"] = deepcopy(result)
        return result

    def metadata(self):
        return {"model": "deterministic-reference-input-v1", "paid_model": "false"}


class AgentReferenceExecutor:
    def __init__(
        self,
        request: AgentReferenceContext,
        mini_root: Path,
        evidence_root: Path | None = None,
    ):
        from eval_contracts.capabilities import (
            CapabilityBundle,
            CapabilityDocument,
            CapabilityRegistry,
        )
        from minimal_agent import (
            build_default_intent_registry,
            export_capability_bundle,
        )

        from ..providers.mini_agent.capability_adapter import (
            load_mini_agent_capability_bundle,
        )

        if not isinstance(request, AgentReferenceContext):
            raise TypeError("executor requires Oracle-free reference context")
        self.request = request
        self.evidence_root = evidence_root
        self.factory = fixture_class(mini_root)
        docs = []
        for p in request.capability_documents:
            docs.append(
                CapabilityDocument(
                    snapshot_id=p["snapshot_id"],
                    snapshot_type=p["snapshot_type"],
                    snapshot_format_version=p["snapshot_format_version"],
                    contract_version=p["contract_version"],
                    snapshot_sha256=p["snapshot_sha256"],
                    payload=p,
                    capability_id=p.get("capability_id"),
                    module_id=p.get("module_id"),
                )
            )
        self.reference = CapabilityRegistry(
            CapabilityBundle(
                root="bound-reference-request",
                provider_id="mini_agent",
                bundle_format_version="3.0",
                capability_bundle_sha256=request.bundle_sha256,
                documents=tuple(docs),
            )
        )
        with TemporaryDirectory(prefix="mini-reference-current-") as temporary:
            path = Path(temporary) / "bundle"
            export_capability_bundle(
                path, build_default_intent_registry(), self.factory().registry()
            )
            self.current = CapabilityRegistry(load_mini_agent_capability_bundle(path))
        from .full_readiness import function_schema

        for name, schema in request.target_schemas.items():
            actual = self.current.bundle.get_document(name).payload
            if name.startswith("tool."):
                if function_schema(schema) != function_schema(
                    actual["function_schema"]
                ):
                    raise ValueError("runtime tool schema differs from reference")
            elif actual.get("parameters_schema") != schema:
                raise ValueError("runtime intent schema differs from reference")
        for doc in request.capability_documents:
            if doc["snapshot_type"] == "intent":
                actual = self.current.bundle.get_document(doc["snapshot_id"]).payload
                if doc["decision_rules"] != actual["decision_rules"]:
                    raise ValueError("runtime decision policy differs from reference")
                semantics = doc.get("parameter_semantics", {}).get(
                    "execution_semantics"
                )
                if semantics is not None and semantics != actual.get(
                    "parameter_semantics", {}
                ).get("execution_semantics"):
                    raise ValueError("runtime intent semantics differ from reference")

    def execute(
        self,
        case_id: str,
        plan: AgentPlan,
        *,
        model=None,
        user_responses=None,
    ) -> ToolEvidence:
        from eval_contracts.schemas import ExecutionProfile, ExecutionSpec

        from ..providers.mini_agent.provider import MiniAgentProvider

        row = ToolEvidence(
            case_id=case_id,
            status="error",
            evidence_complete=False,
            before_state={},
            after_state={},
            tool_calls=[],
            tool_result={},
            errors=[],
            execution=plan.model_dump(mode="json"),
        )
        from agent_trace_sdk import EvidenceReader, InspectEvidenceSink, TraceContext

        temporary = None
        if self.evidence_root is None:
            temporary = TemporaryDirectory(prefix="agent-reference-evidence-")
            evidence_path = Path(temporary.name) / "trace"
        else:
            import hashlib

            # Persist at the discoverable destination before any Agent work.
            # The sink rejects an existing directory, so attempts never overwrite.
            evidence_path = (
                self.evidence_root / hashlib.sha256(case_id.encode()).hexdigest()[:24]
            )
        sink = InspectEvidenceSink(
            evidence_path, TraceContext(), event_rules_version="mini-agent-events-v1"
        )
        runtime = None
        fixture = self.factory()
        # Start from a known empty fixture; input-only recipes may fill it later.
        fixture.users, fixture.gifts, fixture.pools = {}, {}, {}
        fixture.resources, fixture.grants, fixture.requests = [], [], {}
        for field, key in [
            ("users", "user_id"),
            ("gifts", "gift_id"),
            ("pools", "pool_id"),
        ]:
            setattr(
                fixture,
                field,
                {r[key]: deepcopy(r) for r in plan.records.get(field, [])},
            )
        fixture.resources = deepcopy(plan.records.get("resources", []))
        registry = fixture.registry()
        handler_calls = []
        for definition in registry.definitions:
            original, tool_name = definition.handler, definition.name

            def observed_handler(_handler=original, _name=tool_name, **arguments):
                handler_calls.append({"name": _name, "arguments": deepcopy(arguments)})
                if _name == plan.tool_name and plan.fault == "tool_error":
                    raise RuntimeError("REFERENCE_TOOL_FAILURE")
                if _name == plan.tool_name and plan.fault == "tool_timeout":
                    raise TimeoutError("REFERENCE_TOOL_TIMEOUT")
                return _handler(**arguments)

            definition.handler = observed_handler
        live = model is not None
        model = model if live else ReferenceModel(plan)
        try:
            provider = MiniAgentProvider(
                self.reference,
                lambda execution: model,
                current_capabilities=self.current,
                execution_profiles={
                    "full_fixture": ExecutionProfile(
                        allowed_tools=sorted(d.name for d in registry.definitions)
                    )
                },
                tool_registry_factory=lambda allowed: registry,
            )
            execution = ExecutionSpec(
                user_input=plan.user_input,
                user_responses=[] if user_responses is None else user_responses,
                tool_profile="full_fixture",
                allowed_tools=plan.allowed_tools,
                max_steps=plan.max_steps,
                timeout_seconds=30,
            )
            runtime = provider.create_observed_runtime(
                execution, "reference-isolated-session", plan.scope, sink
            )

            # Reuse the existing adapter's per-turn independent state reads.
            # This evaluation wrapper observes the fixture, never changes Agent policy.
            class FixtureState:
                def snapshot(self):
                    return _snapshot(fixture)

                def cleanup(self):
                    pass

            runtime.environment = FixtureState()
            row.before_state = _snapshot(fixture)
            output = (
                provider.run_module(runtime, execution)
                if plan.scope == "module"
                else provider.run_full(runtime, execution, plan.scope)
            )
            result = output.turns[-1] if output.turns else None
            manifest = sink.finish(execution_completed=True)
            events, manifest = EvidenceReader().read(
                evidence_path, memory_manifest=manifest
            )
            if manifest["status"] != "COMPLETE" or provider.evidence_issues(
                output, events
            ):
                raise ValueError("provider evidence incomplete")
            reference_hash = self.reference.bundle.capability_bundle_sha256
            row.observations = {
                "module_output": output.module_output,
                "agent_result": result,
                "turns": output.turns,
                "turn_snapshots": output.turn_snapshots,
                "events": events,
                "evidence_manifest": manifest,
                "model_interactions": model.interactions,
                "provider": "mini_agent",
                "reference_bundle_sha256": reference_hash,
                "runtime_bundle_sha256": self.current.bundle.capability_bundle_sha256,
                "execution_kind": "real_model_agent"
                if live
                else "scripted_model_real_agent",
                "handler_calls": handler_calls,
                "chain_nodes": node_evidence(plan, events, self.request),
            }
            if not output.turns:
                row.observations.pop("turn_snapshots")
            row.tool_calls = [] if result is None else result["tool_calls"]
            row.after_state = _snapshot(fixture)
            row.status, row.evidence_complete = "completed", True
        except Exception as exc:
            row.errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            if runtime is not None:
                provider.cleanup(runtime)
            if temporary is not None:
                temporary.cleanup()
        return row
