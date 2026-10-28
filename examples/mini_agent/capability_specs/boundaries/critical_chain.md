---
snapshot_id: boundary.critical_chain
description: Structural critical_chain execution boundary.
entry_binding: node.intent_decided
stop_binding: node.run_finished
module_roles: [orchestration, model_gateway, intent_routing, tool_loop, tool_registry, execution_guard, observability]
evidence_ids: [evidence.intent_result, evidence.tool_trace, evidence.final_response]
terminal_condition_template: The {stop_node} node is reached.
no_overrun_rule_template: No node after {stop_node} may execute in this range.
---
# Critical-chain boundary

This reusable boundary spans the selected critical path from intent decision
to the final run result.
