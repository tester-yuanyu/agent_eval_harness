---
snapshot_id: boundary.result
description: Structural result execution boundary.
entry_binding: node.terminal_status_selected
stop_binding: node.run_finished
module_roles: [orchestration, observability]
evidence_ids: [evidence.final_response]
terminal_condition_template: The {stop_node} node is reached.
no_overrun_rule_template: No node after {stop_node} may execute in this range.
---
# Result boundary

This boundary covers terminal status selection and final response emission.
