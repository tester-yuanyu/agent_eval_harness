---
snapshot_id: scope.understanding
description: Reusable understanding evaluation range.
inputs: [user_input]
outputs: [intent_result]
entrypoint_binding: entrypoint.intent_only
stop_binding: node.intent_decided
module_roles: [model_gateway, intent_routing]
evidence_ids: [evidence.intent_result]
boundary_id: boundary.understanding
requirements:
  - requirement_id: formal_intent_validation
    capability_key: intent.formal_validation
    provider: {role: module_role, module_role: intent_routing}
    mandatory: true
    evidence_ids: [evidence.intent_result]
  - requirement_id: selected_intent_contract
    capability_key: intent.contract_validation
    provider: {role: selected_intent}
    mandatory: true
    evidence_ids: [evidence.intent_result]
completion_condition: The entrypoint is reached, every mandatory requirement is resolved, the stop boundary is reached, and required Evidence is observable.
unresolved_behavior: A missing or undeclared capability remains unknown; the Scope does not infer support.
---
# Understanding Scope

This Scope evaluates formal intent interpretation only. A selected Intent
contract is injected by the Suite and must not be inferred by the Scope.
