---
snapshot_id: evidence.context_state
description: Cross-turn conversation state observation interface.
consumer_roles: [builder, evaluator]
required: false
applicable_result_paths: []
---
# Context state Evidence

Context evaluation requires an observable representation of inherited,
overridden, cancelled, isolated, and cleared state. An Agent without such an
interface must report the Evidence as unsupported or unknown.
