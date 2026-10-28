---
snapshot_id: boundary.understanding
description: Structural understanding execution boundary.
entry_binding: entrypoint.intent_only
stop_binding: node.intent_decided
module_roles: [model_gateway, intent_routing]
evidence_ids: [evidence.intent_result]
terminal_condition_template: The {stop_node} node is reached.
no_overrun_rule_template: No node after {stop_node} may execute in this range.
---
# Understanding boundary

This boundary stops after the formal intent decision and excludes planning,
tool execution, and result production.
