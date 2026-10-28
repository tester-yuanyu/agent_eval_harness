---
snapshot_id: evidence.execution_contract
description: Source-backed static execution contract, not a runtime trace or execution
  verdict.
consumer_roles:
- builder
- evaluator
required: false
applicable_result_paths:
- contract_inspection
---

# Static contract

Read integrations/capability_snapshot/contracts.json. Hashes and supporting sources
are in provenance. This evidence supports declaration completeness only; it may
not establish successful inference, tool side effects or business correctness.
