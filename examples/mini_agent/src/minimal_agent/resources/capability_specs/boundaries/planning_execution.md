---
snapshot_id: boundary.planning_execution
description: Structural planning_execution execution boundary.
entry_binding: node.tool_requested
stop_binding: node.tool_terminal
module_roles: [tool_loop, tool_registry]
evidence_ids: [evidence.tool_trace]
terminal_condition_template: The {stop_node} node is reached.
no_overrun_rule_template: No node after {stop_node} may execute in this range.
---
# Planning and execution boundary

This boundary begins with a selected Tool request and stops at its terminal
result.
