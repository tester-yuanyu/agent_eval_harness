---
spec_id: protocol.capability_v3
version: "1.0"
snapshot_format_version: "3.0"
agent_capability_groups:
  agent.understanding:
    - intent.formal_validation
  agent.context:
    - context.inheritance
    - context.override
    - context.cancellation
    - context.session_isolation
    - context.residual_state_handling
    - context.cleanup
  agent.planning_execution:
    - execution.bounded_tool_loop
    - execution.registered_tool_invocation
    - safety.run_allow_list
  agent.safety_recovery:
    - safety.tool_failure_terminal
    - safety.tool_timeout_terminal
  agent.result:
    - observability.trace_export
    - result.final_response
---
# Capability Snapshot Protocol v3

This protocol combines portable evaluation requirements with facts supplied by
one concrete Agent adapter. Requirements do not prove support. Explicitly
unsupported facts take precedence, missing facts remain unknown, and supported
facts require observable Evidence.
