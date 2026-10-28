---
spec_id: protocol.capability_v3
version: "1.0"
snapshot_format_version: "3.0"
agent_capability_groups:
  agent.conversation: [dialogue.respond, result.final_response]
---
# Conversation profile

A profile for direct-response agents. No tool, model provider, fixed module count
or internal intent router is required. A selected Intent describes the business
task; it need not be a separate runtime routing node. Adapt bindings and Facts
to actual implementation. Support resolution is not an execution test.
