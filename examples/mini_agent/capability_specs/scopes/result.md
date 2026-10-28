---
snapshot_id: scope.result
description: Reusable result evaluation range.
inputs: [terminal_status, execution_evidence]
outputs: [agent_result, final_response]
entrypoint_binding: node.terminal_status_selected
stop_binding: node.run_finished
module_roles: [orchestration, observability]
evidence_ids: [evidence.final_response]
boundary_id: boundary.result
requirements:
  - requirement_id: final_response
    capability_key: result.final_response
    provider: {role: module_role, module_role: observability}
    mandatory: true
    evidence_ids: [evidence.final_response]
completion_condition: The entrypoint is reached, every mandatory requirement is resolved, the stop boundary is reached, and required Evidence is observable.
unresolved_behavior: A missing or undeclared capability remains unknown; the Scope does not infer support.
---
# Result Scope

This Scope evaluates terminal status and the final user-facing response.
