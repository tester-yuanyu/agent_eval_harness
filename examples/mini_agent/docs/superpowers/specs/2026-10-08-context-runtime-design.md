# Context Runtime Design

Date: 2026-10-08

## Purpose

Add a small, executable Context capability to `MinimalAgent` so the Agent can
truthfully support and expose these capability claims:

- `context.inheritance`
- `context.override`
- `context.cancellation`
- `context.session_isolation`
- `context.residual_state_handling`
- `context.cleanup`

The implementation must support direct Context evaluation and full Agent runs,
produce stable Evidence for Builder and Evaluator consumers, and keep the
runtime small. It is not a general conversation-history system.

## Agreed Constraints

- State storage is injected through a `ContextStore` protocol.
- An in-memory implementation is available by default.
- Context is explicit structured data. The Agent does not infer state from
  natural language and does not persist complete conversation transcripts.
- Context values are JSON-compatible.
- Production callers may replace the default store with Redis, database, or
  other implementations without changing `MinimalAgent`.
- No automatic summarization, token compression, expiry scheduler, or database
  integration is included.
- Capability snapshots describe only behavior implemented by the runtime.

## Public Runtime Model

### `ContextUpdate`

`ContextUpdate` is the complete Context command supplied for one operation:

- `values: dict[str, JsonValue]` contains new values and overrides.
- `cancel_keys: list[str]` identifies individual keys to remove.
- `clear: bool` requests removal of the complete inherited state before any new
  values are applied.

Keys must be non-empty strings. Values must be JSON-compatible. Duplicate
cancel keys are normalized by keeping their first occurrence; the public result
therefore uses a deterministic, duplicate-free representation.

Operations are applied in this fixed order:

1. load inherited state;
2. clear inherited state when `clear` is true;
3. remove `cancel_keys`;
4. merge `values`, with current values replacing inherited values;
5. persist or delete the resulting session state;
6. return an immutable-by-copy observation of the operation.

If a key appears in both `cancel_keys` and `values`, the final value is the new
value because cancellation precedes the merge.

### `ContextState`

`ContextState` is the stable result and Evidence payload:

- `session_id: str | None`
- `inherited: dict[str, JsonValue]`
- `applied_values: dict[str, JsonValue]`
- `cancelled_keys: list[str]`
- `cleared: bool`
- `resolved: dict[str, JsonValue]`

All dictionaries returned across the public boundary are deep copies. Mutating
a returned object cannot mutate stored state.

### Agent entrypoints

The Context-only entrypoint is:

```python
agent.resolve_context(
    session_id="session-1",
    context=ContextUpdate(...),
) -> ContextState
```

This entrypoint stops after Context resolution. It does not invoke the intent
model or a Tool, so it matches the `scope.context` boundary.

The full Agent entrypoint becomes:

```python
agent.run(
    user_input,
    session_id="session-1",
    context=ContextUpdate(...),
) -> AgentResult
```

Existing calls that omit Context remain valid.

When no `session_id` is supplied, Context is ephemeral: it is resolved from an
empty inherited state and is not persisted. This permits deterministic
single-run Context without creating unaddressable residual state.

When a `session_id` is supplied and Context is omitted, the Agent resolves and
returns the currently inherited state without changing it.

## Components

The two data contracts live beside the existing Agent protocol in
`src/minimal_agent/contracts/agent.py`, avoiding a runtime-to-contract import
cycle. Context behavior stays in one focused module,
`src/minimal_agent/runtime/context.py`, containing:

- `ContextStore`;
- `ContextStoreError`;
- `InMemoryContextStore`.

`MinimalAgent` receives an optional `context_store` constructor dependency. If
none is provided, it creates one `InMemoryContextStore` owned by that Agent
instance. No module-global state is used.

### `ContextStore`

The store exposes one atomic operation conceptually equivalent to:

```python
apply(session_id: str, update: ContextUpdate) -> ContextState
```

The operation either commits the entire update or leaves the previous state
unchanged. This prevents read/modify/write races from being introduced by the
Agent. Replaceable stores are responsible for providing the same atomic
contract using their own transaction mechanism.

The default in-memory store uses a lock, stores deep copies, and removes the
session entry when the resolved state is empty. This provides isolation and
prevents empty residual records.

Ephemeral Context is resolved by the Context runtime without writing to the
store.

## Full-Run Data Flow

`MinimalAgent.run` resolves Context immediately after validating the run input
and before calling the intent model:

```text
user input + session id + ContextUpdate
                 |
                 v
        resolve Context atomically
                 |
        +--------+---------+
        |                  |
        v                  v
ContextState Evidence   resolved Context
                           |
                 intent model and Tool loop
                           |
                           v
                      AgentResult
```

The resolved Context is presented to the intent model as a deterministic JSON
block combined with the model-facing input. Intent contract validation still
uses the original `user_input`; Context serialization does not alter semantic
validation rules.

`ToolLoopRequest` gains a `context` field with an empty default. The OpenAI and
DeepSeek clients include it in their initial model input. Scripted and custom
clients that do not inspect the field continue to work.

Context is committed before downstream model or Tool execution. A later model
or Tool failure does not create ambiguous commit behavior: the `ContextState`
reported for that run remains the state already committed before execution.

## Evidence and Result Protocol

For full runs, Context is observable at both:

- `AgentResult.context_state`;
- the `context_state_resolved` Trace event.

The event payload uses the same `ContextState` schema. It is emitted after a
successful Context operation and before the intent request. Runs that use
neither a session nor an explicit Context update may report no Context state,
preserving the lightweight behavior of existing stateless runs.

For Context-only evaluation, the returned `ContextState` is the Evidence and no
full Agent result is required.

The generated capability facts must declare `evidence.context_state` as
supported and identify both stable observation interfaces. The six Context
claims on the orchestration module become supported only after runtime and
Evidence tests pass.

## Failure Semantics

- Invalid Context data fails validation before model or Tool execution.
- An empty or whitespace-only `session_id` remains invalid.
- A store failure is surfaced as `ContextStoreError` and prevents downstream
  model and Tool execution.
- `ContextStore.apply` must not partially mutate state on failure.
- Removing a missing key is an idempotent no-op and remains visible in the
  requested `cancelled_keys` Evidence.
- `clear=True` on a missing session is successful and idempotent.
- When the final resolved state is empty, the store deletes the session entry.

The first implementation does not add retries. Retry policy depends on the
production store and would otherwise introduce behavior the in-memory runtime
cannot meaningfully evaluate.

## Capability Bundle Changes

After implementation, the capability source facts are updated and the
canonical `capabilities/` Bundle is regenerated.

Expected changes include:

- the six `context.*` claims change from `unsupported` to `supported`;
- `evidence.context_state` changes to `supported`;
- Context Evidence lists `ContextState` as its payload schema;
- the observation interface points to `MinimalAgent.resolve_context`,
  `AgentResult.context_state`, and the `context_state_resolved` event as
  appropriate;
- the orchestration module lists `context_state_resolved` among observable
  events;
- Agent input and result schemas include the new optional Context fields;
- all snapshot hashes, reference hashes, and the Bundle hash are regenerated.

No unsupported capability is changed merely to make a Scope resolve. The
Bundle must be derived from verified runtime facts.

## Verification

Tests cover:

1. initial Context creation;
2. inheritance across runs with the same session;
3. override precedence;
4. individual cancellation;
5. whole-session cleanup;
6. cleanup followed by new values in one update;
7. isolation between session identifiers;
8. deletion of empty residual state;
9. deep-copy protection for input, stored, and returned values;
10. atomic behavior when a store operation fails;
11. Context-only execution without model or Tool calls;
12. resolved Context reaching intent and Tool-loop model inputs;
13. Context Evidence in `AgentResult` and Trace;
14. downstream failure retaining unambiguous Context Evidence;
15. all six Context requirements resolving as supported;
16. Bundle Schema, reference, DAG, and hash verification;
17. the complete existing test and lint suites.

## Out of Scope

- automatic extraction of Context from natural-language messages;
- persistence of raw conversation history;
- distributed store implementations;
- Context TTL or expiry scheduling;
- summarization or token-budget management;
- cross-Agent shared memory;
- business-specific Context fields;
- evaluator fixtures or scoring policy.

These concerns may build on `ContextStore` later without expanding the core
Agent now.
