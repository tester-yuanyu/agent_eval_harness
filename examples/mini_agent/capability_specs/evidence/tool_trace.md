---
snapshot_id: evidence.tool_trace
description: Tool request and terminal ToolCallRecord observations.
consumer_roles: [builder, evaluator]
required: true
applicable_result_paths: [success, failure, timeout]
---
# Tool trace Evidence

Tool evaluation requires observable request, start, success, failure, and
timeout information that can be correlated to one call.
