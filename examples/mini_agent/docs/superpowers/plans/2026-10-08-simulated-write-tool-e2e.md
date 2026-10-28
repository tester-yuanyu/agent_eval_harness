# Simulated Write Tool End-to-End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, contract-realistic `add_gift_to_backpack` simulator and generic two-turn confirmation path that verify critical write behavior end to end without changing the default zero-Tool Agent composition.

**Architecture:** Generic confirmation and execution context live in `minimal_agent.runtime`; SQLite state, seed data, simulated service behavior, and the gift Tool live in `minimal_agent.testing`. The Evaluator explicitly constructs this configuration and exports a separate capability bundle, while the default Agent, top-level API, and checked-in 20-artifact bundle remain unchanged.

**Tech Stack:** Python 3.11, Pydantic v2, stdlib `sqlite3`, Pytest, Ruff, Capability Snapshot Protocol v2.

**Spec:** `docs/superpowers/specs/2026-10-08-simulated-write-tool-e2e-design.md`

## Global Constraints

- Use test-driven development: each production behavior starts with a focused failing test and observed expected failure.
- Keep `minimal_agent.__all__` at exactly 13 existing names.
- Keep the default ToolRegistry empty and the checked-in bundle at 1 Agent, 7 Modules, 7 Intents, 0 Tools, and 5 Schemas.
- Do not add evaluator cases, expected values, scoring, Judge logic, or reports to the Agent.
- Simulation-specific code must stay under `minimal_agent.testing` and must never be imported by default runtime composition.
- Do not expose `request_id` or execution context fields in the model-visible Tool schema.
- Every evaluation case must supply an explicit unique SQLite path; no shared default database path is allowed.
- Trace records public inputs, outputs, statuses, and errors only—never chain-of-thought or hidden evaluation answers.

## Review Focus

- Concurrent confirmations for one pending action invoke the Tool at most once; Task 2 adds an atomic-claim test.
- `COMMIT_THEN_TIMEOUT` commits exactly once and safe replay does not duplicate grants; Tasks 3 and 4 add state and replay tests.
- Projection from Intent parameters to strict Tool arguments drops execution metadata such as `environment` but rejects missing/invalid Tool fields; Task 2 adds both tests.
- Multi-user/multi-gift requests are all-or-nothing when any referenced entity is invalid; Task 4 adds transaction rollback tests.
- Default and configured capability bundles cannot be confused; Task 5 tests both counts, references, descriptions, and hashes.

---

### Task 1: Add optional Tool execution context

**Files:**
- Create: `src/minimal_agent/runtime/execution.py`
- Modify: `src/minimal_agent/runtime/tool_registry.py`
- Modify: `src/minimal_agent/runtime/__init__.py`
- Modify: `tests/test_runtime_tool_registry.py`

**Interfaces:**
- Produces: frozen `ToolExecutionContext(operation_id: str, run_id: str, session_id: str, confirmed: bool)`.
- Produces: `ToolDefinition(..., accepts_execution_context: bool = False)`.
- Produces: `ToolRegistry.invoke(name, arguments, *, allowed_tools=None, execution_context=None) -> ToolResult`.
- Preserves: existing context-free handlers and schemas without behavior or schema changes.

- [ ] **Step 1: Write failing context-delivery tests**

Add tests proving a context-aware handler receives the exact immutable context, while an existing handler still receives only validated business keyword arguments. Add a test that constructing a context-aware definition and invoking it without a context fails explicitly before calling the handler.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_runtime_tool_registry.py -q`

Expected: FAIL because `ToolExecutionContext`, `accepts_execution_context`, and the `execution_context` invocation parameter do not exist.

- [ ] **Step 3: Implement the minimal execution context path**

Create the frozen context model in `runtime/execution.py`. Extend ToolDefinition invocation so `accepts_execution_context=False` preserves the current call signature, while `True` supplies keyword-only `execution_context`. Add a stable `MissingToolExecutionContextError`; do not inspect handler signatures dynamically.

- [ ] **Step 4: Verify GREEN and regression safety**

Run:

```bash
.venv/bin/python -m pytest tests/test_runtime_tool_registry.py tests/test_runtime_agent.py -q
.venv/bin/python -m ruff check src/minimal_agent/runtime tests/test_runtime_tool_registry.py
```

Expected: PASS; existing Echo Tool behavior and schema remain unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/minimal_agent/runtime/execution.py src/minimal_agent/runtime/tool_registry.py src/minimal_agent/runtime/__init__.py tests/test_runtime_tool_registry.py
git commit -m "feat: add optional tool execution context"
```

### Task 2: Implement generic confirmation orchestration

**Files:**
- Create: `src/minimal_agent/runtime/confirmation.py`
- Create: `tests/support/confirmation_store.py`
- Create: `tests/test_runtime_confirmation.py`
- Modify: `src/minimal_agent/runtime/agent.py`
- Modify: `src/minimal_agent/runtime/intent_router.py`
- Modify: `src/minimal_agent/runtime/__init__.py`

**Interfaces:**
- Consumes: `ToolExecutionContext` and context-aware ToolRegistry invocation from Task 1.
- Produces: `ConfirmationState`, `PendingAction`, `ConfirmationOutcome`, `ConfirmationStore` protocol, and `ConfirmationPolicy`.
- Produces: `MinimalAgent(..., intent_registry: IntentRegistry | None = None, confirmation_store: ConfirmationStore | None = None, confirmation_policy: ConfirmationPolicy | None = None, ...)`.
- Produces: first-turn save, exact confirm/cancel handling, atomic claim, replay, expiration, and frozen-argument projection.

- [ ] **Step 1: Write failing first-turn confirmation tests**

Using a deterministic model and a test-owned in-memory ConfirmationStore, test that a complete `add_backpack_gift` intent with `session_id="case-1"` saves one pending action and returns `NEED_CONFIRMATION` without Tool invocation. Assert that frozen Tool arguments exclude `environment`, preserve all business values, and pass the registered strict Tool model.

- [ ] **Step 2: Run the first-turn tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_runtime_confirmation.py -q`

Expected: collection or assertion failure because the confirmation types and Agent constructor options do not exist.

- [ ] **Step 3: Implement confirmation records, policy, and first-turn save**

Define strict immutable records and a storage protocol in `runtime/confirmation.py`. Inject one IntentRegistry instance into both MinimalAgent and IntentRouter so the Agent can resolve the declared Tool name without duplicating intent rules. Project arguments from the registered Tool model fields, validate before save, require non-empty session ID, and record `confirmation_saved` or a stable terminal failure.

- [ ] **Step 4: Verify first-turn GREEN**

Run: `.venv/bin/python -m pytest tests/test_runtime_confirmation.py -q`

Expected: first-turn tests PASS.

- [ ] **Step 5: Write failing confirm, cancel, expiration, replacement, and replay tests**

Add tests asserting:

- exact accepted phrases execute the frozen Tool without a second model call;
- exact cancellation phrases never invoke it;
- expired actions fail without invocation;
- a new complete write replaces only a pending action;
- unrelated input follows normal classification;
- two atomic claims yield one execution;
- repeated confirmation returns the stored terminal outcome;
- repeated confirmation after a raised service error or timeout retries with
  the same operation ID, while a terminal ToolResult is only replayed;
- missing or invalid projected Tool fields fail before persistence;
- confirmed AgentResult carries `READY/CALL_TOOL`, the ToolCallRecord, and confirmation Trace events.

- [ ] **Step 6: Run the expanded tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_runtime_confirmation.py -q`

Expected: new tests FAIL because second-turn orchestration is not implemented.

- [ ] **Step 7: Implement second-turn orchestration**

Handle confirmation/cancellation before model classification only when the session has a current action. Atomically claim pending actions, invoke with `ToolExecutionContext`, save terminal outcomes, and build AgentResult directly from the Tool result or raised error. Preserve current no-store behavior and normal read Tool loop.

- [ ] **Step 8: Verify GREEN and runtime regression safety**

Run:

```bash
.venv/bin/python -m pytest tests/test_runtime_confirmation.py tests/test_runtime_agent.py tests/test_intent_router.py -q
.venv/bin/python -m ruff check src/minimal_agent/runtime tests/test_runtime_confirmation.py tests/support/confirmation_store.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/minimal_agent/runtime/confirmation.py src/minimal_agent/runtime/agent.py src/minimal_agent/runtime/intent_router.py src/minimal_agent/runtime/__init__.py tests/support/confirmation_store.py tests/test_runtime_confirmation.py
git commit -m "feat: add generic confirmed tool execution"
```

### Task 3: Build the isolated SQLite evaluation state

**Files:**
- Create: `src/minimal_agent/testing/__init__.py`
- Create: `src/minimal_agent/testing/sqlite_state.py`
- Create: `tests/test_simulated_sqlite_state.py`

**Interfaces:**
- Consumes: `ConfirmationStore`, pending action, and terminal outcome protocols from Task 2.
- Produces: `SimulatedUser`, `SimulatedGift`, `BackpackGrant`, `BackpackSnapshot`.
- Produces: `SQLiteEvaluationState(database_path, *, clock=...)` implementing ConfirmationStore plus explicit seed, transaction, idempotency, and read-only observation methods.
- Produces: no implicit path and no automatic seed rows.

- [ ] **Step 1: Write failing schema and isolation tests**

Test explicit-path enforcement, empty initial state, explicit user/gift seeding, duplicate seed rejection, separate database isolation, and defensive read-only snapshots.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_simulated_sqlite_state.py -q`

Expected: import failure because `minimal_agent.testing.sqlite_state` does not exist.

- [ ] **Step 3: Implement database setup and observation**

Create all five tables with foreign keys enabled and explicit transactions. Store canonical JSON for frozen actions and terminal outcomes. Implement seed and snapshot APIs without importing them into the default runtime.

- [ ] **Step 4: Verify basic state GREEN**

Run: `.venv/bin/python -m pytest tests/test_simulated_sqlite_state.py -q`

Expected: basic state tests PASS.

- [ ] **Step 5: Write failing confirmation concurrency and idempotency tests**

Test atomic pending replacement/claim, expiry, cancel, terminal replay, one winner across two SQLite connections, same operation/request replay, and different-request conflict. Assert rollback leaves zero grant and idempotency rows.

- [ ] **Step 6: Run the expanded tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_simulated_sqlite_state.py -q`

Expected: new transaction and claim tests FAIL.

- [ ] **Step 7: Implement atomic claim and grant transaction primitives**

Use SQLite compare-and-set updates for state transitions and one transaction for all grant rows plus the idempotency record. Persist canonical request hashes and terminal ToolResult JSON.

- [ ] **Step 8: Verify GREEN and static checks**

Run:

```bash
.venv/bin/python -m pytest tests/test_simulated_sqlite_state.py -q
.venv/bin/python -m ruff check src/minimal_agent/testing tests/test_simulated_sqlite_state.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/minimal_agent/testing/__init__.py src/minimal_agent/testing/sqlite_state.py tests/test_simulated_sqlite_state.py
git commit -m "feat: add isolated sqlite evaluation state"
```

### Task 4: Implement the contract-realistic gift Tool simulator

**Files:**
- Create: `src/minimal_agent/testing/gift_tool.py`
- Create: `tests/test_simulated_gift_tool.py`
- Modify: `src/minimal_agent/testing/__init__.py`

**Interfaces:**
- Consumes: `AddGiftToBackpackArguments`, ToolContract/ToolDefinition/ToolResult, ToolExecutionContext, and SQLiteEvaluationState.
- Produces: `SimulatorMode` with `NORMAL`, `SERVICE_ERROR`, `TIMEOUT`, `COMMIT_THEN_TIMEOUT`.
- Produces: versioned `ADD_GIFT_TO_BACKPACK_SIMULATED_CONTRACT`.
- Produces: `SimulatedGiftTool(state, *, mode=SimulatorMode.NORMAL)` and `definition() -> ToolDefinition`.
- Produces: business result codes `OK`, `USER_NOT_FOUND`, `GIFT_NOT_FOUND`, `INVALID_QUANTITY`, `IDEMPOTENCY_CONFLICT`, and `PERMISSION_DENIED`.

- [ ] **Step 1: Write failing contract and permission tests**

Assert exact Tool name/version, strict schema, simulated description, write/high-risk/confirmation metadata, and result codes. Test that an absent execution context raises the runtime's missing-context error and an explicitly unconfirmed context returns `PERMISSION_DENIED`, both with zero writes.

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_simulated_gift_tool.py -q`

Expected: import failure because the simulator does not exist.

- [ ] **Step 3: Implement contract, normalization, and permission gate**

Bind the existing strict argument model. Normalize every user/gift selection mode into concrete rows, applying `num=1` and `duration_days=7` defaults. Reject an expanded total above 1000 per user as `INVALID_QUANTITY`. Require a confirmed ToolExecutionContext before calling state mutation primitives.

- [ ] **Step 4: Verify initial GREEN**

Run: `.venv/bin/python -m pytest tests/test_simulated_gift_tool.py -q`

Expected: contract and permission tests PASS.

- [ ] **Step 5: Write failing business, transaction, idempotency, and failure-mode tests**

Cover every selection mode, inactive/missing users and gifts, invalid quantities, multi-row atomic success, invalid-member rollback, same operation replay, conflict, pre-commit service error, pre-commit timeout, and commit-then-timeout followed by safe replay.

- [ ] **Step 6: Run expanded tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_simulated_gift_tool.py -q`

Expected: new behavior tests FAIL.

- [ ] **Step 7: Implement Tool outcomes and simulated service modes**

Return business ToolResults without raising. Raise `RuntimeError` for `SERVICE_ERROR` and `TimeoutError` for both timeout modes at the specified mutation boundary. Ensure commit-then-timeout saves the idempotent success before raising.

- [ ] **Step 8: Verify GREEN and static checks**

Run:

```bash
.venv/bin/python -m pytest tests/test_simulated_gift_tool.py tests/test_simulated_sqlite_state.py -q
.venv/bin/python -m ruff check src/minimal_agent/testing tests/test_simulated_gift_tool.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/minimal_agent/testing/__init__.py src/minimal_agent/testing/gift_tool.py tests/test_simulated_gift_tool.py
git commit -m "feat: add simulated backpack gift tool"
```

### Task 5: Prove end-to-end execution and configured capabilities

**Files:**
- Create: `tests/test_simulated_write_e2e.py`
- Create: `tests/test_simulated_write_capabilities.py`
- Modify: `README.md`
- Modify: `docs/CAPABILITY_SNAPSHOT.md`
- Modify: `docs/RUNTIME_CAPABILITY_MIGRATION.md`

**Interfaces:**
- Consumes: all runtime and testing interfaces from Tasks 1–4.
- Produces: documented two-turn construction and configured bundle export recipe.
- Preserves: checked-in default bundle and 13-name top-level public API.

- [ ] **Step 1: Write failing two-turn end-to-end tests**

Build one Agent with deterministic first-turn intent output, simulator registry, and SQLite confirmation state. Assert request → `NEED_CONFIRMATION` → same-session confirmation → Tool invocation → Agent `SUCCESS` → independent snapshot with the exact grant. Reconstruct the Agent and state from the same database between turns to prove process persistence. Add cancellation, session isolation, duplicate confirmation, service timeout, and commit-then-timeout state-observation cases.

- [ ] **Step 2: Run end-to-end tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_simulated_write_e2e.py -q`

Expected: at least one integration assertion FAILS until the runtime and simulator boundaries are correctly wired.

- [ ] **Step 3: Make only integration repairs required by the failing tests**

Fix boundary mismatches without adding business logic to runtime or simulator imports to default composition.

- [ ] **Step 4: Verify end-to-end GREEN**

Run: `.venv/bin/python -m pytest tests/test_simulated_write_e2e.py -q`

Expected: PASS.

- [ ] **Step 5: Write failing capability configuration tests**

Assert the checked-in default bundle remains 20 artifacts and zero Tools. Export a temporary configured bundle and assert 21 artifacts, one `tool.add_gift_to_backpack`, a matching `intent.add_backpack_gift.tool_refs` entry, simulated version/description, supported execution modules, and successful validation. Assert hashes differ from the default bundle.

- [ ] **Step 6: Run capability tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_simulated_write_capabilities.py -q`

Expected: FAIL until the simulator definition and capability metadata satisfy the configured export contract.

- [ ] **Step 7: Make capability metadata repairs and update documentation**

Document explicit simulator construction, seed setup, two-turn execution, independent observation, and configured bundle export. State prominently that the simulator is a versioned surrogate rather than a real service contract.

- [ ] **Step 8: Run complete verification**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m minimal_agent.capabilities.cli validate --input capabilities
.venv/bin/python - <<'PY'
import minimal_agent
assert len(minimal_agent.__all__) == 13
PY
```

Expected: all commands succeed; only the documented paid OpenAI smoke may skip. Default bundle reports 1 Agent, 7 Intents, 7 Modules, and 0 Tools.

- [ ] **Step 9: Commit**

```bash
git add tests/test_simulated_write_e2e.py tests/test_simulated_write_capabilities.py README.md docs/CAPABILITY_SNAPSHOT.md docs/RUNTIME_CAPABILITY_MIGRATION.md
git commit -m "test: prove simulated write tool end to end"
```
