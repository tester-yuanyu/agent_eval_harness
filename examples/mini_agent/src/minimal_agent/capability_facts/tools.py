"""MiniAgent Tool facts derived only from registered Tool contracts."""

from capability_snapshot_kit.facts import ToolFactV3
from capability_snapshot_kit.models import CapabilityClaimV3
from minimal_agent.runtime.tool_registry import ToolRegistry


def _claim(
    capability_key: str,
    status: str,
    *,
    evidence_ids: tuple[str, ...] = (),
    reason: str | None = None,
) -> CapabilityClaimV3:
    return CapabilityClaimV3(
        capability_key=capability_key,
        support_status=status,
        evidence_ids=list(evidence_ids),
        reason=reason,
    )


def build_tool_facts_v3(registry: ToolRegistry) -> tuple[ToolFactV3, ...]:
    facts: list[ToolFactV3] = []
    for definition in registry.definitions:
        contract = definition.contract
        declared_results = {
            code: dict(protocol)
            for code, protocol in sorted(contract.result_contracts.items())
        }
        has_rate_limit_protocol = "RATE_LIMITED" in declared_results
        result_protocols = {
            "declared_results": declared_results,
            "empty_result": {
                "behavior": contract.empty_result_behavior,
                "source": "tool_contract",
            },
            "timeout": {
                "terminal_status": "failure",
                "runtime_event": "tool_timeout",
            },
            "rate_limit": (
                {
                    "support_status": "supported",
                    "result_code": "RATE_LIMITED",
                    "source": "tool_contract",
                }
                if has_rate_limit_protocol
                else {
                    "support_status": "unknown",
                    "reason": "No runtime-specific rate-limit protocol is declared.",
                }
            ),
            "execution_failure": {
                "terminal_status": "failure",
                "runtime_event": "tool_failed",
            },
            "partial_success": {
                "behavior": contract.partial_success_behavior,
                "source": "tool_contract",
            },
            "async": {
                "support_status": "unsupported",
                "reason": "The runtime invokes handlers synchronously.",
            },
        }
        facts.append(
            ToolFactV3(
                tool_name=contract.name,
                contract_version=contract.version,
                tool_version=contract.version,
                description=contract.description,
                implementation_profile=contract.implementation_profile,
                registered=True,
                function_schema=definition.schema(),
                parameter_semantics={
                    "rules": dict(contract.parameter_rules),
                    "validation": "STRICT_ARGUMENT_MODEL",
                },
                combination_rules={
                    "source": "parameter_schema",
                    "undeclared_combinations": "unknown",
                },
                batch_behavior={
                    "support_status": "unknown",
                    "reason": (
                        "No generic batch behavior is declared by ToolContract."
                    ),
                },
                preconditions=list(contract.permission_requirements),
                result_protocols=result_protocols,
                permission_requirements=list(contract.permission_requirements),
                requires_confirmation=contract.requires_confirmation,
                risk_level=contract.risk_level,
                idempotency_rules=dict(contract.idempotency_rules),
                side_effects=list(contract.side_effects),
                retry_policy={
                    "eligible": False,
                    "maximum_attempts": 1,
                    "stop_conditions": ["success", "failure", "timeout"],
                    "reason": (
                        "The runtime performs one handler invocation per call."
                    ),
                },
                simulation_protocol=(
                    {
                        "name": "deterministic_injected_handler",
                        "version": contract.version,
                    }
                    if contract.implementation_profile != "production"
                    else None
                ),
                simulation_capabilities=list(contract.simulation_capabilities),
                observation_interfaces=list(contract.observation_interfaces),
                capabilities=(
                    _claim(
                        "tool.registered_execution",
                        "supported",
                        evidence_ids=("evidence.tool_trace",),
                    ),
                    _claim(
                        "tool.runtime_retry",
                        "unsupported",
                        reason="The runtime does not retry failed Tool handlers.",
                    ),
                    (
                        _claim(
                            "tool.rate_limit_protocol",
                            "supported",
                            evidence_ids=("evidence.tool_trace",),
                        )
                        if has_rate_limit_protocol
                        else _claim(
                            "tool.rate_limit_protocol",
                            "unknown",
                            reason=(
                                "Rate-limit semantics are owned by the injected "
                                "handler."
                            ),
                        )
                    ),
                ),
            )
        )
    return tuple(facts)
