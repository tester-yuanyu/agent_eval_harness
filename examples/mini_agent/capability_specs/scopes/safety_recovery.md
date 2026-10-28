---
snapshot_id: scope.safety_recovery
description: Reusable safety_recovery evaluation range.
inputs: [policy_decision, execution_failure]
outputs: [terminal_stop]
entrypoint_binding: node.policy_or_failure_detected
stop_binding: node.terminal_stop
module_roles: [execution_guard, tool_loop]
evidence_ids: [evidence.safety_recovery_event]
boundary_id: boundary.safety_recovery
requirements:
  - requirement_id: run_allow_list
    capability_key: safety.run_allow_list
    provider: {role: module_role, module_role: execution_guard}
    mandatory: true
    evidence_ids: [evidence.safety_recovery_event]
  - requirement_id: tool_failure_terminal
    capability_key: safety.tool_failure_terminal
    provider: {role: module_role, module_role: tool_loop}
    mandatory: true
    evidence_ids: [evidence.safety_recovery_event]
completion_condition: The entrypoint is reached, every mandatory requirement is resolved, the stop boundary is reached, and required Evidence is observable.
unresolved_behavior: A missing or undeclared capability remains unknown; the Scope does not infer support.
---
# Safety and recovery Scope

This Scope evaluates allow-list enforcement and terminal handling for Tool
failures through observable safety and recovery events.
