---
snapshot_id: boundary.safety_recovery
description: Structural safety_recovery execution boundary.
entry_binding: node.policy_or_failure_detected
stop_binding: node.terminal_stop
module_roles: [execution_guard, tool_loop]
evidence_ids: [evidence.safety_recovery_event]
terminal_condition_template: The {stop_node} node is reached.
no_overrun_rule_template: No node after {stop_node} may execute in this range.
---
# Safety and recovery boundary

This boundary covers policy decisions, execution failures, and the terminal
stop they cause.
