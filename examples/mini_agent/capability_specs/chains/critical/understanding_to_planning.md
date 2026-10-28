---
snapshot_id: chain.understanding_to_planning
category: critical
description: Reusable understanding_to_planning capability chain.
nodes:
  - node_id: intent_validation
    capability_key: intent.contract_validation
    provider: {role: selected_intent}
    depends_on: []
    inputs: [intent_validation_input]
    outputs: [intent_validation_output]
    stop_conditions: [intent_validation_terminal]
    state_reads: []
    state_writes: []
  - node_id: tool_execution
    capability_key: tool.registered_execution
    provider: {role: selected_tool}
    depends_on: [intent_validation]
    inputs: [tool_execution_input]
    outputs: [tool_execution_output]
    stop_conditions: [tool_execution_terminal]
    state_reads: []
    state_writes: []
  - node_id: bounded_execution
    capability_key: execution.bounded_tool_loop
    provider: {role: module_role, module_role: tool_loop}
    depends_on: [tool_execution]
    inputs: [bounded_execution_input]
    outputs: [bounded_execution_output]
    stop_conditions: [bounded_execution_terminal]
    state_reads: []
    state_writes: []
module_roles: [intent_routing, tool_loop]
evidence_ids: [evidence.intent_result, evidence.tool_trace]
boundary_id: boundary.critical_chain
requirements:
  - requirement_id: selected_intent_contract
    capability_key: intent.contract_validation
    provider: {role: selected_intent}
    mandatory: true
    evidence_ids: [evidence.intent_result]
  - requirement_id: selected_tool_execution
    capability_key: tool.registered_execution
    provider: {role: selected_tool}
    mandatory: true
    evidence_ids: [evidence.tool_trace]
branches:
  - {branch_type: normal, terminal_condition: result_emission completes}
  - {branch_type: error, terminal_condition: a model or Tool failure is emitted}
  - {branch_type: early_stop, terminal_condition: "clarification, confirmation, rejection, or policy stop is emitted"}
completion_condition: The entry node is reached, ordered mandatory nodes are traversed, a declared terminal branch stops at the boundary, and required Evidence is observable.
---
# Understanding-to-planning critical chain

This chain combines the selected Intent contract, selected Tool contract, and
bounded execution loop without asserting a Tool exists in every Agent.
