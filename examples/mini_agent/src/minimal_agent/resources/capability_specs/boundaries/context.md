---
snapshot_id: boundary.context
description: Structural context execution boundary.
entry_binding: input.context
stop_binding: node.context_state_observed
module_roles: [orchestration]
evidence_ids: [evidence.context_state]
terminal_condition_template: The {stop_node} node is reached.
no_overrun_rule_template: No node after {stop_node} may execute in this range.
---
# Context boundary

This boundary covers context inheritance, overrides, cancellation, isolation,
residual state handling, and cleanup only.
