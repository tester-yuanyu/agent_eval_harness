"""Oracle-free Provider process; only public execution and fixtures enter stdin."""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import asdict, replace
from pathlib import Path

from agent_trace_sdk import EvidenceReader, InspectEvidenceSink, TraceContext

from ..capabilities import CapabilityRegistry
from ..provider import AdapterOutput
from ..providers.mini_agent.capability_adapter import load_mini_agent_capability_bundle
from ..providers.mini_agent.provider import MiniAgentProvider
from ..providers.mini_agent.runtime_binding import MiniAgentRuntimeBindingFactory
from ..schemas import ExecutionProfile, ExecutionSpec


def execute_public(
    task: dict, bundle: Path, evidence: Path, model_client_factory
) -> dict:
    if set(task) != {"execution", "scope", "environment"}:
        raise ValueError("worker accepts only the public execution projection")
    execution = ExecutionSpec.model_validate(task["execution"])
    capabilities = CapabilityRegistry(load_mini_agent_capability_bundle(bundle))
    profiles = {
        execution.tool_profile: ExecutionProfile(
            allowed_tools=execution.allowed_tools or []
        )
    }
    kind = task["environment"]["kind"]
    options = {}
    if kind == "gift_sqlite_v1":
        options["environment"] = kind
    elif kind == "query_user_fixture_v1":
        from minimal_agent.contracts.tools import ToolResult

        users = task["environment"]["users"]

        def handler(**query):
            matched = [
                user
                for user in users
                if all(user.get(k) == v for k, v in query.items() if v is not None)
            ]
            return ToolResult(
                success=True,
                code="OK" if matched else "EMPTY",
                message="query complete",
                data={"users": matched},
            )

        binding = MiniAgentRuntimeBindingFactory(
            capabilities, query_user_handler_factory=lambda: handler
        )
        # Verify actual exported contracts before supplying the custom binding.
        binding(frozenset(execution.allowed_tools or []))
        options.update(tool_registry_factory=binding, current_capabilities=capabilities)
    elif kind != "no_tools" or execution.allowed_tools:
        raise ValueError("unsupported public environment")
    provider = MiniAgentProvider(
        capabilities, model_client_factory, execution_profiles=profiles, **options
    )
    identifier = uuid.uuid4().hex
    sink = InspectEvidenceSink(
        evidence,
        TraceContext(identifier),
        event_rules_version=provider.evidence_rules_version,
    )
    runtime, output, errors, completed = None, None, [], False
    try:
        runtime = provider.create_observed_runtime(
            execution, identifier, task["scope"], sink
        )
        output = (
            provider.run_module(runtime, execution)
            if task["scope"] == "module"
            else provider.run_full(runtime, execution, task["scope"])
        )
        completed = True
    except Exception as exc:
        info = provider.classify_exception(exc)
        output = info.output
        errors.append(
            {
                "kind": "provider",
                "code": info.execution_status,
                "message": info.exception,
            }
        )
    finally:
        manifest = sink.finish(execution_completed=completed)
        events, manifest = EvidenceReader().read(evidence, memory_manifest=manifest)
        if runtime is not None:
            provider.cleanup(runtime)
    output = output or AdapterOutput(
        None, [], None, [], None, execution_completed=False
    )
    issues = provider.evidence_issues(output, events)
    status = manifest["status"] if not issues else "PARTIAL"
    output = replace(
        output,
        observations={
            "tool_results": [
                event["payload"].get("output")
                for event in events
                if event["event_type"] == "tool_succeeded"
                and event.get("validation_status") == "VALID"
            ]
        },
        trace_events=events,
        evidence_status=status,
        evidence_manifest=manifest,
    )
    return {
        "status": "completed" if completed else "error",
        "adapter_output": asdict(output),
        "evidence_complete": completed and status == "COMPLETE",
        "errors": errors + issues,
    }


def main():
    from minimal_agent.runtime import DeepSeekModelClient
    from openai import OpenAI

    payload = json.load(sys.stdin)

    def client(execution):
        return DeepSeekModelClient(
            OpenAI(base_url=payload["bridge_url"], api_key="inspect", max_retries=0),
            model="inspect",
            timeout_seconds=execution.timeout_seconds,
        )

    result = execute_public(
        payload["task"], Path("/opt/reference"), Path("evidence"), client
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
