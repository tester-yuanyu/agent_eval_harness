---
snapshot_id: evidence.intent_result
description: Validated IntentResult returned by the intent router.
consumer_roles: [builder, evaluator]
required: true
applicable_result_paths: [success, need_clarification, need_confirmation, rejected, failure]
---
# Intent result Evidence

The Agent must expose the validated formal intent decision after intent
processing. The concrete payload schema, producer, event, and observation
interface come from the Agent adapter.
