---
snapshot_id: scope.planning_execution
description: Reusable planning_execution evaluation range.
inputs: [intent_result, selected_tool]
outputs: [tool_terminal_result]
entrypoint_binding: node.tool_requested
stop_binding: node.tool_terminal
module_roles: [tool_loop, tool_registry, execution_guard]
evidence_ids: [evidence.tool_trace, evidence.safety_recovery_event]
boundary_id: boundary.planning_execution
requirements:
  - requirement_id: bounded_tool_loop
    capability_key: execution.bounded_tool_loop
    provider: {role: module_role, module_role: tool_loop}
    mandatory: true
    evidence_ids: [evidence.tool_trace]
  - requirement_id: selected_tool_execution
    capability_key: tool.registered_execution
    provider: {role: selected_tool}
    mandatory: true
    evidence_ids: [evidence.tool_trace]
completion_condition: The entrypoint is reached, every mandatory requirement is resolved, the stop boundary is reached, and required Evidence is observable.
unresolved_behavior: A missing or undeclared capability remains unknown; the Scope does not infer support.
---
# Planning and execution Scope

This Scope evaluates the bounded Tool loop and the explicitly selected Tool.
The Tool must be present in the current Agent configuration.
