---
snapshot_id: chain.end_to_end
category: end_to_end
description: Direct conversation from business request to terminal response.
nodes:
  - node_id: response
    capability_key: dialogue.respond
    provider: {role: module_role, module_role: dialogue}
    depends_on: []
    inputs: [user_input]
    outputs: [final_response]
    stop_conditions: [terminal_response]
    state_reads: []
    state_writes: []
module_roles: [dialogue, observability]
evidence_ids: [evidence.final_response]
boundary_id: boundary.conversation
requirements:
  - requirement_id: business_task
    capability_key: dialogue.business_task
    provider: {role: selected_intent}
    mandatory: true
    evidence_ids: [evidence.final_response]
  - requirement_id: response_evidence
    capability_key: result.final_response
    provider: {role: module_role, module_role: observability}
    mandatory: true
    evidence_ids: [evidence.final_response]
branches:
  - {branch_type: normal, terminal_condition: A final response is returned}
  - {branch_type: early_stop, terminal_condition: A clarification or handoff suggestion is returned when declared by the Agent}
  - {branch_type: error, terminal_condition: A declared failure is returned or raised}
completion_condition: The run reaches its terminal boundary and exposes the declared response evidence.
---
# Conversation chain

No selected_tool provider is required. This does not imply a specific Agent
supports every branch; applicable paths must come from its Evidence facts.
