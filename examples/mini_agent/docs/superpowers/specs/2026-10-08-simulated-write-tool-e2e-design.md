# Simulated Write Tool End-to-End Design

## 1. Purpose

Add an opt-in, contract-realistic `add_gift_to_backpack` simulator so this
repository can verify the critical write path and end-to-end behavior without
claiming access to a real gift service.

The simulator must exercise intent validation, confirmation, permission,
strict Tool invocation, transactional persistence, idempotency, failure
handling, Trace evidence, independent state observation, and
configuration-bound capability export. It is a versioned surrogate contract,
not proof of compatibility with an unknown production API.

## 2. Architectural boundary

The existing three-domain production architecture remains intact:

- `minimal_agent.contracts` owns formal Agent, Intent, and Tool protocols;
- `minimal_agent.runtime` owns generic confirmation and execution behavior;
- `minimal_agent.capabilities` describes the registries actually configured.

Simulation-specific code lives under `minimal_agent.testing`. It is installed
with the package so a consumer can run an end-to-end evaluation, but it is not
imported by the default runtime, exported from `minimal_agent.__all__`, or
registered by default.

The default composition remains seven Intents, zero Tools, and twenty
capability artifacts. A consumer must explicitly create the simulator,
register its Tool, and export a separate configured capability bundle.

## 3. Alternatives considered

### Selected: opt-in simulator in `minimal_agent.testing`

This keeps the evaluation path reproducible beside the Agent while preserving
an empty default registry. It also allows the repository to prove the full
chain without presenting fictional data as a production capability.

### Rejected: simulator only in the Evaluator project

This gives stronger repository isolation but prevents the Agent repository
from owning and verifying the end-to-end reference path.

### Rejected: default built-in business Tool

This is easiest to invoke but recreates the business coupling and capability
inflation removed by the runtime slimming work.

## 4. Generic confirmation runtime

### 4.1 Interfaces

The runtime defines a `ConfirmationStore` protocol and immutable records for a
pending action and its terminal outcome. `MinimalAgent` accepts an optional
store and optional confirmation policy. When no store is supplied, current
behavior is unchanged: a write Intent returns `NEED_CONFIRMATION` without
persisting or executing anything.

A pending action contains:

- an opaque `operation_id`, used as the execution idempotency key;
- `session_id`;
- the original write `IntentResult`;
- the required Tool name;
- frozen Tool arguments derived from the registered Tool parameter model;
- creation and expiration timestamps;
- state: `PENDING`, `CANCELLED`, `EXECUTING`, `SUCCEEDED`, or `FAILED`;
- an optional terminal Tool result or error.

The generic runtime does not know about users, gifts, backpacks, or SQLite.
The testing package supplies the SQLite implementation of the store.

### 4.2 First turn

When the IntentRegistry returns `NEED_CONFIRMATION` and the Agent has a
confirmation store:

1. `session_id` is required; without it the Agent returns an explicit failure
   and does not save an action.
2. The Agent resolves the Intent's declared `tool_name` in ToolRegistry.
3. It projects the frozen Intent parameters onto the registered Tool argument
   model. Execution-only values such as `environment` remain confirmation
   metadata and are not injected into the strict Tool schema.
4. It validates the projected arguments before saving.
5. It replaces any still-pending action for the same session and records a new
   opaque operation ID and expiration.
6. It returns `NEED_CONFIRMATION` without invoking the Tool.

### 4.3 Confirmation and cancellation turns

The confirmation policy recognizes exact normalized phrases. The initial
Chinese policy accepts `确认`, `确认执行`, `执行`, and `是`; cancellation accepts
`取消`, `取消执行`, `不执行`, and `否`. Applications may inject a different
policy.

For a session with a pending action:

- a confirmation phrase claims the action atomically and invokes the frozen
  Tool directly; it does not call the model again;
- a cancellation phrase atomically marks the action cancelled and performs no
  Tool invocation;
- other input follows normal intent classification and may replace the
  pending action only if it produces a new complete write request;
- an expired action is terminal and cannot execute.

The confirmed execution creates an execution-phase IntentResult with
`READY/CALL_TOOL`, the frozen parameters, and a public confirmation reason.
This distinguishes the authorized execution from the first-turn
`NEED_CONFIRMATION` result while preserving the existing AgentResult schema.

### 4.4 Concurrency and replay

Claiming a pending action is an atomic compare-and-set from `PENDING` to
`EXECUTING`. Concurrent confirmations therefore invoke the Tool at most once.

After any terminal ToolResult, repeated confirmation for the same session
returns the stored result without reinvoking the Tool. A raised service error
or timeout is marked retryable; repeating confirmation atomically claims it
again with the same operation ID. That makes pre-commit failures retryable and
makes commit-then-timeout converge on the Tool's stored idempotent success.
Cancellation and expiration never invoke the Tool and are not retryable.

## 5. Tool execution context

`ToolDefinition.invoke` gains an optional execution context. Existing handlers
continue to receive only their validated business keyword arguments.

A ToolDefinition may opt in to context delivery at construction. Context-aware
handlers additionally receive a keyword-only `execution_context` containing:

- `operation_id`;
- `run_id`;
- `session_id`;
- `confirmed`.

The simulator requires a non-null context with `confirmed=True`. A missing
context is rejected by ToolDefinition before handler invocation; a supplied
but unconfirmed context returns `PERMISSION_DENIED` and never writes. The
opaque operation ID becomes its idempotency request ID without exposing that
field to the model-visible Tool schema.

## 6. Versioned surrogate Tool contract

The Tool is named `add_gift_to_backpack` and uses the existing strict
`AddGiftToBackpackArguments` business schema:

- exactly one user mode: `user_id` or `user_ids`;
- exactly one gift mode: `gift_id`, `gift_ids`, or `gift_nums`;
- `num` defaults to 1 when the selected gift mode does not carry quantities;
- `duration_days` defaults to 7; 1000 means permanent validity;
- quantities and duration are integers from 1 through 1000.

The surrogate service additionally limits the expanded total quantity for one
user in one operation to 1000. Exceeding that aggregate limit returns
`INVALID_QUANTITY`; this business rule remains observable after strict field
validation and makes the result code reachable without weakening the schema.

The testing contract has its own explicit version and identifies itself as a
simulated implementation in its description and metadata. It declares a
write Tool, high risk, confirmation required, operation-ID idempotency,
backpack side effects, and all supported result codes.

## 7. SQLite simulator

### 7.1 Isolation

Each evaluation case creates a unique database path. The factory refuses an
implicit shared default path. The Evaluator owns database creation and cleanup.

The database contains:

- `users` with active/inactive status;
- `gifts` with active/inactive status;
- `backpack_grants` with operation, user, gift, quantity, duration, and time;
- `idempotency_requests` with operation ID, canonical request hash, and stored
  terminal result;
- `confirmation_actions` used by the SQLite ConfirmationStore.

The test fixture API accepts explicit seed users and gifts. It does not invent
rows on lookup.

### 7.2 Transaction

One confirmed request is normalized into concrete `(user, gift, quantity)`
grant rows. The simulator validates every referenced entity before opening the
write transaction. All grants and the idempotency record commit atomically.
Partial success is unsupported.

An existing operation ID with the same canonical request returns the stored
result without adding rows. The same operation ID with different normalized
arguments returns `IDEMPOTENCY_CONFLICT` without mutation.

### 7.3 Independent observation

The testing API exposes read-only snapshots and grant queries keyed by case,
user, and operation ID. Evaluator assertions use these interfaces rather than
trusting AgentResult or ToolResult.

## 8. Results and failures

Business outcomes are ToolResult values:

- `OK`;
- `USER_NOT_FOUND`;
- `GIFT_NOT_FOUND`;
- `INVALID_QUANTITY`;
- `IDEMPOTENCY_CONFLICT`;
- `PERMISSION_DENIED`.

Transport/service simulations are explicit configured behaviors owned by one
simulator instance:

- `NORMAL`;
- `SERVICE_ERROR`, which fails before mutation;
- `TIMEOUT`, which times out before mutation;
- `COMMIT_THEN_TIMEOUT`, which commits and then raises a timeout.

Behavior configuration is never model-visible and is isolated per evaluation
case. The Agent does not automatically retry failures.

For confirmed direct execution, a successful ToolResult yields Agent
`SUCCESS`; a business-failure ToolResult yields Agent `FAILED` while retaining
the observable Tool output; raised errors/timeouts yield Agent `FAILED` with a
`FAILED` or `TIMEOUT` ToolCallRecord. `COMMIT_THEN_TIMEOUT` is detected only by
the Evaluator's independent state observation and safe operation-ID replay.

## 9. Trace evidence

The generic runtime adds observable events for:

- confirmation saved, replaced, accepted, cancelled, expired, or replayed;
- confirmed Tool requested, started, succeeded, failed, or timed out;
- operation ID, session ID, Tool name, public status, and error class.

Trace must not contain chain-of-thought, hidden evaluator expectations,
database credentials, or unmasked seed data beyond the explicit Tool request
and result protocols.

## 10. Capability snapshots

The default checked-in bundle remains unchanged and contains no Tool files.

The evaluation setup exports a separate bundle using the default
IntentRegistry and simulator-configured ToolRegistry. That bundle contains
`tool.add_gift_to_backpack`; `intent.add_backpack_gift` references it; Tool and
execution Modules become supported according to the existing aggregation
rules; all parent hashes and `capability_bundle_sha256` are recomputed.

The Tool description and contract version explicitly include its simulated
status. Builder and Evaluator bind to this configured bundle and reject any
hash or configuration mismatch.

## 11. Verification

Tests cover:

- no-store behavior remains unchanged;
- first-turn persistence and required session ID;
- exact confirmation/cancellation phrases and unrelated input;
- frozen parameters and pending-action replacement;
- expiration, cancellation, repeat confirmation, and concurrent claim;
- strict Tool arguments and confirmed execution context;
- success, each business result code, service error, timeout, and
  commit-then-timeout;
- atomic multi-user/multi-gift writes and rollback;
- same-request idempotency and conflict detection;
- case/session isolation and independent state snapshots;
- default bundle remains 20 artifacts with zero Tools;
- configured bundle contains one Tool and a valid Intent reference;
- complete two-turn Agent-to-Tool-to-state end-to-end flow.

The full offline test suite, Ruff, default bundle validation, and configured
bundle validation must all pass. The paid OpenAI smoke test remains opt-in.

## 12. Non-goals

- claiming compatibility with a real service whose protocol is unavailable;
- shipping the simulator in the default Agent composition;
- adding evaluation cases, scoring, Judge logic, or reports to the Agent;
- automatic retries, distributed locks, production authentication, or
  production-grade database migration tooling;
- adding the simulator or confirmation store to the 13-name top-level API.
