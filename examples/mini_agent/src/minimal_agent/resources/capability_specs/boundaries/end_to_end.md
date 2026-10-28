---
snapshot_id: boundary.end_to_end
description: Structural end_to_end execution boundary.
entry_binding: node.run_started
stop_binding: node.run_finished
module_roles: [orchestration, model_gateway, intent_routing, tool_loop, tool_registry, execution_guard, observability]
evidence_ids: [evidence.intent_result, evidence.tool_trace, evidence.safety_recovery_event, evidence.final_response]
terminal_condition_template: The {stop_node} node is reached.
no_overrun_rule_template: No node after {stop_node} may execute in this range.
---
# End-to-end boundary

This boundary starts when a run begins and stops at the declared terminal run
event. No node may execute after the terminal event.
