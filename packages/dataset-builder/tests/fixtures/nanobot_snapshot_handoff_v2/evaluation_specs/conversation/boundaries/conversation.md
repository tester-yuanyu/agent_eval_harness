---
snapshot_id: boundary.conversation
description: One direct conversation turn.
entry_binding: entrypoint.run
stop_binding: node.finished
module_roles: [dialogue, observability]
evidence_ids: [evidence.final_response]
terminal_condition_template: The {stop_node} boundary is reached.
no_overrun_rule_template: No further work is performed after {stop_node} within this turn.
---
# Conversation boundary

Use the actual run entry and terminal event or return boundary. This profile
does not claim cross-turn persistence, external transfers or tool execution.
