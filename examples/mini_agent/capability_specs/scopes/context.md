---
snapshot_id: scope.context
description: Reusable context evaluation range.
inputs: [prior_context, current_user_input]
outputs: [resolved_context, cleared_state]
entrypoint_binding: input.context
stop_binding: node.context_state_observed
module_roles: [orchestration]
evidence_ids: [evidence.context_state]
boundary_id: boundary.context
requirements:
  - requirement_id: inheritance
    capability_key: context.inheritance
    provider: {role: module_role, module_role: orchestration}
    mandatory: true
    evidence_ids: [evidence.context_state]
  - requirement_id: override
    capability_key: context.override
    provider: {role: module_role, module_role: orchestration}
    mandatory: true
    evidence_ids: [evidence.context_state]
  - requirement_id: cancellation
    capability_key: context.cancellation
    provider: {role: module_role, module_role: orchestration}
    mandatory: true
    evidence_ids: [evidence.context_state]
  - requirement_id: session_isolation
    capability_key: context.session_isolation
    provider: {role: module_role, module_role: orchestration}
    mandatory: true
    evidence_ids: [evidence.context_state]
  - requirement_id: residual_state_handling
    capability_key: context.residual_state_handling
    provider: {role: module_role, module_role: orchestration}
    mandatory: true
    evidence_ids: [evidence.context_state]
  - requirement_id: cleanup
    capability_key: context.cleanup
    provider: {role: module_role, module_role: orchestration}
    mandatory: true
    evidence_ids: [evidence.context_state]
completion_condition: The entrypoint is reached, every mandatory requirement is resolved, the stop boundary is reached, and required Evidence is observable.
unresolved_behavior: A missing or undeclared capability remains unknown; the Scope does not infer support.
---
# Context Scope

This Scope evaluates inherited context, current-input overrides, cancellation,
session isolation, residual-state handling, and cleanup.
