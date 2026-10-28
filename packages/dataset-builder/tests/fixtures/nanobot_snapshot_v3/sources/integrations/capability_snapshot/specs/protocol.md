---
spec_id: protocol.capability_v3
version: nanobot-sdk-v2
snapshot_format_version: '3.0'
agent_capability_groups:
  agent.conversation:
  - dialogue.respond
  - result.final_response
  agent.execution_contract:
  - contract.sdk_boundary
  - contract.run_result
  - contract.exception_exit
  - contract.tool_dispatch
---

# Nanobot SDK conversation contract

Refines the existing conversation scope for one awaited Nanobot.run call. Contract
completeness and execution support are separate. No new scoring policy is introduced.
