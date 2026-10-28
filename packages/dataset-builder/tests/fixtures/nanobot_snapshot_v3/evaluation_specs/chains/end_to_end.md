---
snapshot_id: chain.end_to_end
category: end_to_end
description: Conditional foreground SDK pipeline; the node sequence is the ordinary
  model path, not a guarantee every node runs.
nodes:
- node_id: admit
  capability_key: contract.sdk_boundary
  provider:
    role: module_role
    module_role: dialogue
  depends_on: []
  inputs:
  - sdk_arguments
  outputs:
  - runtime_selection
  stop_conditions:
  - raised_exception
  - cancelled
  state_reads: []
  state_writes: []
- node_id: restore_and_route
  capability_key: contract.sdk_boundary
  provider:
    role: module_role
    module_role: dialogue
  depends_on:
  - admit
  inputs:
  - runtime_selection
  - message
  - session_key
  outputs:
  - session_or_command_response
  stop_conditions:
  - command_return
  - raised_exception
  - cancelled
  state_reads:
  - session_history
  state_writes:
  - command_specific_state
- node_id: build_context
  capability_key: contract.sdk_boundary
  provider:
    role: module_role
    module_role: dialogue
  depends_on:
  - restore_and_route
  inputs:
  - session_or_command_response
  outputs:
  - model_messages
  - tool_schemas
  stop_conditions:
  - raised_exception
  - cancelled
  state_reads:
  - session_history
  - memory
  - skills
  state_writes: []
- node_id: model_tool_loop
  capability_key: dialogue.respond
  provider:
    role: module_role
    module_role: dialogue
  depends_on:
  - build_context
  inputs:
  - model_messages
  - tool_schemas
  outputs:
  - runner_outcome
  stop_conditions:
  - returned
  - returned_error
  - tool_error
  - iteration_limit
  - empty_response
  - raised_exception
  - cancelled
  state_reads:
  - model_context
  state_writes:
  - tool_specific_side_effects
- node_id: persist
  capability_key: contract.sdk_boundary
  provider:
    role: module_role
    module_role: dialogue
  depends_on:
  - model_tool_loop
  inputs:
  - runner_outcome
  outputs:
  - outbound_response_or_none
  stop_conditions:
  - raised_exception
  - cancelled
  state_reads:
  - session_policy
  state_writes:
  - session_history_when_enabled
- node_id: return_result
  capability_key: contract.run_result
  provider:
    role: module_role
    module_role: observability
  depends_on:
  - persist
  inputs:
  - outbound_response_or_none
  outputs:
  - run_result
  stop_conditions:
  - sdk_return
  state_reads: []
  state_writes: []
module_roles:
- dialogue
- observability
- tools
- memory
- skills
- providers
evidence_ids:
- evidence.execution_contract
- evidence.final_response
- evidence.run_exception
boundary_id: boundary.conversation
requirements:
- requirement_id: business_task
  capability_key: dialogue.business_task
  provider:
    role: selected_intent
  mandatory: true
  evidence_ids:
  - evidence.final_response
- requirement_id: response_evidence
  capability_key: result.final_response
  provider:
    role: module_role
    module_role: observability
  mandatory: true
  evidence_ids:
  - evidence.final_response
- requirement_id: declared_boundary
  capability_key: contract.sdk_boundary
  provider:
    role: module_role
    module_role: dialogue
  mandatory: true
  evidence_ids:
  - evidence.execution_contract
branches:
- branch_type: normal
  terminal_condition: RunResult returned; completed is a runner status, not a business
    success verdict (refusal/content-filter text can be completed).
- branch_type: returned_error
  terminal_condition: Terminal provider error response yields a RunResult with stop_reason=error;
    it need not raise.
- branch_type: tool_error
  terminal_condition: Unrecovered fatal tool error yields stop_reason=tool_error;
    recoverable errors may instead continue the model loop.
- branch_type: iteration_limit
  terminal_condition: stop_reason=max_iterations; a final no-tools response or fallback
    may be returned with error=null.
- branch_type: empty_response
  terminal_condition: Terminal empty model response after recovery yields stop_reason=empty_final_response
    and diagnostic content.
- branch_type: command_return
  terminal_condition: Handled command skips the remaining normal stages; SDK returns
    directly from the command response, possibly with stop_reason=null.
- branch_type: suppressed_response
  terminal_condition: process_direct may return None; SDK content is then empty, with
    captured fields retained.
- branch_type: raised_exception
  terminal_condition: Uncaught Python exception exits the call; no RunResult required
    and later normal nodes are not reached.
- branch_type: cancelled
  terminal_condition: asyncio.CancelledError propagates; no RunResult or rollback
    is promised.
completion_condition: The foreground call returns or raises/cancels. Final-response
  evidence applies only to returned paths; raised paths need caller-owned exception
  capture. This is completion of observation, not a PASS verdict.
---

# Conditional SDK pipeline

Command return jumps from routing to SDK result conversion, bypassing build, runner
and normal persistence. Exceptions/cancellation can leave from any stage; later
nodes do not run. Tool iterations are optional and repeat within model_tool_loop.
The existing conversation requirements assess returned dialogue; exception
branches are declared separately and are not proven by final_response evidence.
After injected follow-up continuation, stop_reason/error can retain an earlier
failure alongside recovered content. Branch descriptions are execution paths,
not mutually exclusive classifications inferred solely from the final status fields.
