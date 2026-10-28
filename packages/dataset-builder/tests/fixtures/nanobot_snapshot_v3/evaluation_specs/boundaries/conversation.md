---
snapshot_id: boundary.conversation
description: One foreground await Nanobot.run call on an existing instance, including
  returned and raised exits.
entry_binding: entrypoint.run
stop_binding: node.finished
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
terminal_condition_template: The call {stop_node}. A return or raised exit ends this
  foreground boundary, not business acceptance.
no_overrun_rule_template: Observation of this call stops at {stop_node}. Separate
  background consolidation, detached spawned tasks (spawn(wait=false)), future cron jobs and detached processes
  are not awaited by this boundary and may continue; external channel acknowledgement
  and global quiescence are excluded. Awaited spawn(wait=true) work remains inside the foreground call.
---

# SDK foreground boundary

Construction is outside. Per-call selection and optional MCP connect are inside,
before the session lock. Only awaited work belongs to this call. Exceptions and
cancellation do not imply rollback or absence of earlier side effects.
