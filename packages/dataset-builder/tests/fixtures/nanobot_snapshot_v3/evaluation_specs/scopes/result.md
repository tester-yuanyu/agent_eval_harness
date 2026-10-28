---
snapshot_id: scope.result
description: Inspect the native returned RunResult contract; raised exits are separate
  declared branches.
inputs:
- sdk_arguments
outputs:
- run_result_or_raised_exit
entrypoint_binding: entrypoint.run
stop_binding: node.finished
module_roles:
- dialogue
- observability
evidence_ids:
- evidence.execution_contract
- evidence.final_response
- evidence.run_exception
boundary_id: boundary.conversation
requirements:
- requirement_id: response
  capability_key: result.final_response
  provider:
    role: module_role
    module_role: observability
  mandatory: true
  evidence_ids:
  - evidence.final_response
completion_condition: A returned RunResult is observed, or a caller records the raised
  exception/cancellation using a separately implemented observer. Only returned paths
  satisfy the response evidence requirement.
unresolved_behavior: Missing runtime observations, business oracles and exception
  capture remain unknown. Schema/interface support does not imply successful execution.
---

# Result observation scope

RunResult.content may be empty. Nullable stop_reason/error must not be treated as
mandatory success flags. See contracts.json for Python-only arguments and errors.
