---
snapshot_id: scope.result
description: Observe a direct conversational response.
inputs: [user_input]
outputs: [final_response]
entrypoint_binding: entrypoint.run
stop_binding: node.finished
module_roles: [dialogue, observability]
evidence_ids: [evidence.final_response]
boundary_id: boundary.conversation
requirements:
  - requirement_id: response
    capability_key: result.final_response
    provider: {role: module_role, module_role: observability}
    mandatory: true
    evidence_ids: [evidence.final_response]
completion_condition: A terminal response and its declared status are observable.
unresolved_behavior: Missing capabilities or evidence remain unknown.
---
# Result scope

Inspect final response and status through the declared output interface.
