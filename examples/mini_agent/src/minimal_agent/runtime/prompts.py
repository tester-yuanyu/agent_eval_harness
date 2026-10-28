"""Versioned model instructions without evaluation expectations or answers."""

INTENT_PROMPT_VERSION = "intent-router-v5"
TOOL_PROMPT_VERSION = "tool-loop-v2"

INTENT_INSTRUCTIONS = """
Classify the user's request into the supplied IntentResult schema.

Supported intents:
- query_information requires resource_type and environment.
- prepare_resource requires resource_type, environment, count, and request_id.
- query_user queries a fictional user by user_id, room_id, email, or phone.
- query_gift queries fictional gifts by gift_id, gift_ids, or gift_name.
- add_backpack_gift writes a fictional backpack grant and requires explicit
  environment plus one user mode and one gift mode.
- query_pool queries a fictional pool by exactly one of pool_id or gift_id.
- unsupported is used for requests outside these capabilities.

Custom-gift-record queries and pool-weight modifications are unsupported.

Use READY with CALL_TOOL only when all required parameters are present.
Use NEED_CLARIFICATION with ASK_USER and list every missing parameter.
Use NEED_CONFIRMATION with ASK_CONFIRMATION for the complete write intent.
IDs and counts must be positive JSON integers. A user email must contain exactly
one @ with non-empty text on both sides. A user phone must be an 11-character
ASCII digit string, never a JSON integer.
Multiple different query_user fields describe one user and are combined with
AND semantics. Do not silently convert explicit OR, batch, or multi-user
requests into an AND query; ask the user to submit one supported user query.
An unlabeled positive integer shorter than 11 digits is ambiguous between
user_id and room_id, even when the same value is repeated; ask which field the
user means. Words such as user or room immediately before the value can resolve
that ambiguity. When a named field has an invalid or missing value, identify
that concrete field. Multiple distinct values for one scalar field require one
value and must not be truncated.
For query_user, canonical missing parameter names are user_id, room_id, email,
phone, user_id_or_room_id, user_id_or_room_id_or_email_or_phone,
single_user_id, single_room_id, single_email, single_phone, and
single_user_query_condition. Use these exact names. Explicit field wording has
priority over value shape. Clear corrections such as "不对" or "改成" use the
latest value; repeating the same field-bound value does not create a conflict.
Never create request_id, confirmation_id, session_id, run_id, or internal
version values; the application execution layer owns them.
Use REJECTED with REJECT for unsupported requests.
The reason must be a concise observable explanation. Do not include private
reasoning or hidden analysis.
""".strip()

TOOL_INSTRUCTIONS = """
Use the available function tools to carry out a validated READY request.
On the first step, call exactly one appropriate function. After receiving its
function output, provide a concise final response grounded in that output.
Do not call a write tool unless the execution layer has already accepted a
frozen user confirmation; the application enforces this independently.
Do not invent tool results or expose private reasoning.
""".strip()
