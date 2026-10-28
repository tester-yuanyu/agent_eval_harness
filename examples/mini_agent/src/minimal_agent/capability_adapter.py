"""MiniAgent adapter for the portable Capability Snapshot Kit."""

from capability_snapshot_kit.facts import (
    AgentFactsV3,
    EvidenceFactV3,
    IntentFactV3,
    ModuleFactV3,
    ToolFactV3,
)
from minimal_agent.capability_facts import (
    build_evidence_facts_v3,
    build_intent_facts_v3,
    build_module_facts_v3,
    build_tool_facts_v3,
)
from minimal_agent.contracts.agent import AgentResult
from minimal_agent.contracts.intents import IntentRegistry
from minimal_agent.runtime.prompts import INTENT_PROMPT_VERSION, TOOL_PROMPT_VERSION
from minimal_agent.runtime.tool_registry import ToolRegistry
from minimal_agent.versions import (
    MODEL_CLIENT_PROTOCOL_VERSION,
    TOOL_REGISTRY_CONTRACT_VERSION,
    agent_package_version,
)

MINI_AGENT_CONTRACT_VERSION_V3 = "mini-agent-capability-contract-v3"


class MiniAgentCapabilityAdapter:
    """Expose runtime truth as facts without constructing snapshots."""

    def __init__(
        self,
        intent_registry: IntentRegistry,
        tool_registry: ToolRegistry,
    ) -> None:
        self._intent_registry = intent_registry
        self._tool_registry = tool_registry

    def agent_facts(self) -> AgentFactsV3:
        return AgentFactsV3(
            agent_id="mini_agent",
            agent_version=agent_package_version(),
            contract_version=MINI_AGENT_CONTRACT_VERSION_V3,
            entrypoints=["MinimalAgent.run_intent_only", "MinimalAgent.run"],
            runtime_bindings={
                "entrypoint.intent_only": "MinimalAgent.run_intent_only",
                "input.context": "context_input",
                "node.context_state_observed": "context_state_observed",
                "node.intent_decided": "intent_decided",
                "node.policy_or_failure_detected": "policy_or_failure_detected",
                "node.run_finished": "run_finished",
                "node.run_started": "run_started",
                "node.terminal_status_selected": "terminal_status_selected",
                "node.terminal_stop": "terminal_stop",
                "node.tool_requested": "tool_requested",
                "node.tool_terminal": "tool_terminal",
            },
            input_schema={
                "additionalProperties": False,
                "properties": {
                    "user_input": {"type": "string"},
                    "session_id": {"type": ["string", "null"]},
                },
                "required": ["user_input", "session_id"],
                "type": "object",
            },
            output_schema=AgentResult.model_json_schema(),
            runtime_versions={
                "intent_prompt": INTENT_PROMPT_VERSION,
                "tool_prompt": TOOL_PROMPT_VERSION,
                "model_client": MODEL_CLIENT_PROTOCOL_VERSION,
                "tool_registry": TOOL_REGISTRY_CONTRACT_VERSION,
            },
        )

    def module_facts(self) -> tuple[ModuleFactV3, ...]:
        intent_ids = tuple(
            sorted(
                f"intent.{item.intent}"
                for item in self._intent_registry.definitions
            )
        )
        tool_ids = tuple(
            sorted(
                f"tool.{item.contract.name}"
                for item in self._tool_registry.definitions
            )
        )
        return build_module_facts_v3(intent_ids, tool_ids)

    def intent_facts(self) -> tuple[IntentFactV3, ...]:
        return build_intent_facts_v3(self._intent_registry)

    def tool_facts(self) -> tuple[ToolFactV3, ...]:
        return build_tool_facts_v3(self._tool_registry)

    def evidence_facts(self) -> tuple[EvidenceFactV3, ...]:
        return build_evidence_facts_v3()
