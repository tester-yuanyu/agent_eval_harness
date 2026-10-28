---
snapshot_id: evidence.final_response
description: Native RunResult on returned paths, including error-bearing and short-circuit
  returns.
consumer_roles:
- builder
- evaluator
required: true
applicable_result_paths:
- returned
- returned_error
- tool_error
- iteration_limit
- empty_response
- command_return
- suppressed_response
---

# Returned result

Required only on paths that return. No RunResult is required on a raised or
cancelled exit. The schema comes from the actual SDK dataclass; this is not a
claim that its content achieves a business objective.
