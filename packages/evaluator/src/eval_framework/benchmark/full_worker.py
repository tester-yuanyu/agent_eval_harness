"""Docker内v4执行入口：仅公开输入、fixture与能力契约；无Oracle。"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

from eval_contracts.agent_readiness import AgentPlan, AgentReferenceContext
from eval_contracts.operation_readiness import OperationPlan


def capability_registry(context):
    from eval_contracts.capabilities import (
        CapabilityBundle,
        CapabilityDocument,
        CapabilityRegistry,
    )

    docs = [
        CapabilityDocument(
            snapshot_id=d["snapshot_id"],
            snapshot_type=d["snapshot_type"],
            snapshot_format_version=d["snapshot_format_version"],
            contract_version=d["contract_version"],
            snapshot_sha256=d["snapshot_sha256"],
            payload=d,
            module_id=d.get("module_id"),
            capability_id=d.get("capability_id"),
        )
        for d in context.capability_documents
    ]
    return CapabilityRegistry(
        CapabilityBundle(
            root="bound-request",
            provider_id="mini_agent",
            bundle_format_version="3.0",
            capability_bundle_sha256=context.bundle_sha256,
            documents=tuple(docs),
        )
    )


class RecordedModel:
    def __init__(self, client):
        self.client = client
        self.interactions = []

    def classify_intent(self, user_input):
        result = self.client.classify_intent(user_input)
        value = (
            result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        )
        self.interactions.append(
            dict(method="classify_intent", input=user_input, output=deepcopy(value))
        )
        return result

    def next_tool_step(self, request):
        result = self.client.next_tool_step(request)
        value = (
            result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        )
        self.interactions.append(
            dict(
                method="next_tool_step",
                input=request.model_dump(mode="json"),
                output=deepcopy(value),
            )
        )
        return result

    def metadata(self):
        return self.client.metadata()


def execute_public(task, mini_root, evidence_root, client=None):
    from .agent_readiness import AgentReferenceExecutor
    from .full_readiness import fixture_class
    from .operation_readiness import execute_plan

    if set(task) != {"case_id", "execution", "plan", "live", "context"}:
        raise ValueError("worker accepts only public input")
    context = AgentReferenceContext.model_validate(task["context"])
    if "category" in task["plan"]:
        plan = AgentPlan.model_validate(task["plan"])
        if task["live"] != (plan.category != "module_event"):
            raise ValueError("model mode differs from public execution category")
        if task["live"] and client is None:
            raise ValueError("real model client missing")
        row = AgentReferenceExecutor(context, mini_root, evidence_root).execute(
            task["case_id"],
            plan,
            model=RecordedModel(client) if task["live"] else None,
            user_responses=task["execution"].get("user_responses", []),
        )
    else:
        if task["live"]:
            raise ValueError("operation must not call a model")
        plan = OperationPlan.model_validate(task["plan"])
        row = execute_plan(task["case_id"], plan, fixture_class(mini_root))
    return row.model_dump(mode="json")


def main():
    from minimal_agent.runtime import DeepSeekModelClient
    from openai import OpenAI

    payload = json.load(sys.stdin)
    client = None
    if payload["task"]["live"]:
        client = DeepSeekModelClient(
            OpenAI(base_url=payload["bridge_url"], api_key="inspect", max_retries=0),
            model="inspect",
            timeout_seconds=90,
        )
    row = execute_public(
        payload["task"],
        Path("/opt/runtime/packages/agent/src/_eval_fixture_root"),
        Path("evidence"),
        client,
    )
    Path("observation.json").write_text(json.dumps(row, ensure_ascii=False))
    print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
