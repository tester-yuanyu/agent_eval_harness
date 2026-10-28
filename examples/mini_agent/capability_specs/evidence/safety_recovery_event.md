---
snapshot_id: evidence.safety_recovery_event
description: Observable stop, rejection, and failure events.
consumer_roles: [builder, evaluator]
required: true
applicable_result_paths: [need_clarification, need_confirmation, rejected, failure, timeout]
---
# Safety and recovery Evidence

The Agent must expose the event that caused an abnormal or early terminal
state. The adapter supplies the concrete runtime event names.
