# Context Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compact, injectable Context runtime that supports inheritance, override, cancellation, session isolation, residual-state handling, cleanup, and observable Context Evidence.

**Architecture:** Define Context command/result contracts beside the existing Agent contracts, implement one atomic `ContextStore` protocol with a default locked in-memory store, and let `MinimalAgent` reuse it from both a Context-only entrypoint and the full run path. Pass only resolved structured Context into model inputs, expose it through `AgentResult` and Trace, then regenerate the capability Bundle from verified runtime facts.

**Tech Stack:** Python 3.11, Pydantic 2, standard-library `RLock`/`deepcopy`/`json`, pytest, Ruff, Capability Snapshot Kit.

**Spec:** `docs/superpowers/specs/2026-10-08-context-runtime-design.md`

## Global Constraints

- State storage is injected through `ContextStore`; one `InMemoryContextStore` is owned by each `MinimalAgent` by default.
- Context is explicit JSON-compatible structured data, not inferred natural language or persisted conversation history.
- The Context update order is clear, cancel, then value merge.
- Store application is atomic: complete commit or unchanged prior state.
- Context without `session_id` is ephemeral and never persisted.
- Empty resolved session state removes the session entry.
- Existing callers that omit Context remain valid.
- Do not add summarization, token compression, TTL scheduling, database integration, business-specific fields, or evaluator scoring logic.
- Capability claims become supported only after runtime and Evidence tests pass.

## Review Focus

- A key present in both `cancel_keys` and `values` must end with the new value; Task 1 pins the operation order.
- Mutable nested input and output values must not alias stored state; Task 1 tests mutations on both sides.
- Whitespace-only keys, non-JSON values, and whitespace-only session IDs must fail before state or model execution; Tasks 1 and 2 pin this boundary.
- A downstream model or Tool failure after Context commit must retain the committed `ContextState` Evidence; Task 2 covers the failure path.
- Empty, missing, and already-cleared sessions must be idempotent and leave no residual entry; Task 1 covers all three cases.

---

## File Structure

- Modify `src/minimal_agent/contracts/agent.py`: define `ContextUpdate`, `ContextState`, add optional Context to `ToolLoopRequest` and `AgentResult`.
- Create `src/minimal_agent/runtime/context.py`: `ContextStore`, `ContextStoreError`, `InMemoryContextStore`, and ephemeral resolution.
- Modify `src/minimal_agent/runtime/agent.py`: inject the store, add `resolve_context`, wire Context into `run`, Trace, result, and tool-loop requests.
- Modify `src/minimal_agent/runtime/intent_router.py`: accept resolved Context and format only the model-facing input.
- Modify `src/minimal_agent/runtime/prompts.py`: canonical Context JSON formatting shared by intent and Tool clients.
- Modify `src/minimal_agent/runtime/openai_client.py` and `deepseek_client.py`: add resolved Context to first-step Tool input.
- Modify `src/minimal_agent/contracts/__init__.py` and `runtime/__init__.py`: expose stable Context contracts and store interfaces without expanding the root package facade.
- Modify `src/minimal_agent/capability_facts/modules.py`, `evidence.py`, and `capability_adapter.py`: report verified Context support and schemas.
- Modify `docs/CAPABILITY_SNAPSHOT.md`: document Agent/Evaluator Context entrypoints and Evidence.
- Regenerate `capabilities/`: update generated artifacts and hashes from the same runtime configuration.
- Create `tests/test_context_runtime.py` and `tests/test_runtime_context.py`; extend provider, capability, and public API tests.

### Task 1: Context Contracts and Atomic Store

**Files:**
- Modify: `src/minimal_agent/contracts/agent.py`
- Modify: `src/minimal_agent/contracts/__init__.py`
- Create: `src/minimal_agent/runtime/context.py`
- Modify: `src/minimal_agent/runtime/__init__.py`
- Create: `tests/test_context_runtime.py`
- Modify: `tests/test_public_api.py`

**Interfaces:**
- Consumes: `ProtocolModel` and Pydantic JSON-compatible validation.
- Produces: `ContextUpdate(values={}, cancel_keys=[], clear=False)`, `ContextState(session_id, inherited, applied_values, cancelled_keys, cleared, resolved)`, `ContextStore.apply(session_id: str, update: ContextUpdate) -> ContextState`, `InMemoryContextStore`, `ContextStoreError`, and `resolve_ephemeral_context(update: ContextUpdate) -> ContextState`.

- [ ] **Step 1: Write failing contract and store tests**

Add tests named:

- `test_context_update_rejects_blank_keys_and_non_json_values`
- `test_in_memory_store_inherits_overrides_and_cancels_atomically`
- `test_clear_precedes_cancel_and_new_values`
- `test_sessions_are_isolated_and_empty_state_is_removed`
- `test_missing_and_already_cleared_sessions_are_idempotent`
- `test_nested_input_and_returned_state_do_not_alias_storage`
- `test_ephemeral_resolution_never_touches_a_store`
- `test_context_interfaces_are_exported_from_contracts_and_runtime`

Assert the exact operation order, `session_id=None` for ephemeral results, and deep-copy behavior after mutating nested lists/dictionaries.

- [ ] **Step 2: Run the tests and verify the missing interfaces fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_context_runtime.py tests/test_public_api.py -q`

Expected: FAIL because the Context models and runtime store do not exist.

- [ ] **Step 3: Add the Context contracts**

In `contracts/agent.py`, add the two Pydantic models with these public fields:

```python
class ContextUpdate(ProtocolModel):
    values: dict[str, JsonValue] = Field(default_factory=dict)
    cancel_keys: list[str] = Field(default_factory=list)
    clear: bool = False

class ContextState(ProtocolModel):
    session_id: str | None
    inherited: dict[str, JsonValue]
    applied_values: dict[str, JsonValue]
    cancelled_keys: list[str]
    cleared: bool
    resolved: dict[str, JsonValue]
```

Reject keys that are empty after stripping without rewriting valid key text. Normalize duplicate cancellation keys by preserving their first occurrence. Export both models from `minimal_agent.contracts`.

- [ ] **Step 4: Implement the atomic Context runtime**

Create `runtime/context.py` with the interfaces from this task. `InMemoryContextStore.apply` must hold one `RLock` across copy, mutation, and replacement; it must remove an entry rather than storing `{}`. Build the working result before replacing stored state and wrap internal store failures as `ContextStoreError` without changing prior state. Export the store types from `minimal_agent.runtime`.

- [ ] **Step 5: Run focused tests and lint**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_context_runtime.py tests/test_public_api.py -q`

Expected: PASS.

Run: `.venv/bin/python -m ruff check src/minimal_agent/contracts src/minimal_agent/runtime/context.py tests/test_context_runtime.py`

Expected: PASS.

- [ ] **Step 6: Commit the Context core**

```bash
git add src/minimal_agent/contracts/agent.py src/minimal_agent/contracts/__init__.py src/minimal_agent/runtime/context.py src/minimal_agent/runtime/__init__.py tests/test_context_runtime.py tests/test_public_api.py
git commit -m "feat: add atomic context store"
```

### Task 2: MinimalAgent Context Entry Point and Evidence

**Files:**
- Modify: `src/minimal_agent/contracts/agent.py`
- Modify: `src/minimal_agent/runtime/agent.py`
- Create: `tests/test_runtime_context.py`
- Modify: `tests/test_runtime_agent.py`

**Interfaces:**
- Consumes: all Task 1 interfaces.
- Produces: `MinimalAgent(..., context_store: ContextStore | None = None)`, `MinimalAgent.resolve_context(*, session_id: str | None = None, context: ContextUpdate | dict[str, object] | None = None) -> ContextState`, `MinimalAgent.run(..., context=...)`, `AgentResult.context_state: ContextState | None`, and `context_state_resolved` Trace Evidence.

- [ ] **Step 1: Write failing Agent Context tests**

Add tests named:

- `test_resolve_context_stops_before_model_and_tool_execution`
- `test_run_inherits_context_across_same_session`
- `test_run_keeps_sessions_isolated`
- `test_run_with_context_but_no_session_is_ephemeral`
- `test_run_rejects_blank_session_before_store_and_model_calls`
- `test_store_failure_prevents_model_and_tool_execution`
- `test_agent_result_and_trace_expose_identical_context_state`
- `test_model_failure_after_commit_keeps_context_state_for_next_run`
- `test_stateless_run_remains_compatible_with_no_context_state`

Use recording/failing stores and `DeterministicModelClient.requests` to assert exact call boundaries.

- [ ] **Step 2: Run the Agent Context tests and verify failure**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_runtime_context.py tests/test_runtime_agent.py -q`

Expected: FAIL because `MinimalAgent` has no Context entrypoint or constructor dependency.

- [ ] **Step 3: Extend the result and Tool-loop contracts**

Add `context_state: ContextState | None = None` to `AgentResult` and `context: dict[str, JsonValue] = Field(default_factory=dict)` to `ToolLoopRequest`. Preserve all existing required fields and validation rules.

- [ ] **Step 4: Wire Context into `MinimalAgent`**

Add the constructor dependency and `resolve_context` signature above. In `run`, resolve Context before intent execution, emit `context_state_resolved` with `ContextState.model_dump(mode="json")`, pass `resolved` to the intent router and every first/continuing `ToolLoopRequest`, and preserve the same `ContextState` in every terminal `_finish` path. Skip Context work only when both `session_id` and `context` are absent.

- [ ] **Step 5: Run focused Agent tests and lint**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_runtime_context.py tests/test_runtime_agent.py -q`

Expected: PASS.

Run: `.venv/bin/python -m ruff check src/minimal_agent/contracts/agent.py src/minimal_agent/runtime/agent.py tests/test_runtime_context.py`

Expected: PASS.

- [ ] **Step 6: Commit Agent integration**

```bash
git add src/minimal_agent/contracts/agent.py src/minimal_agent/runtime/agent.py tests/test_runtime_context.py tests/test_runtime_agent.py
git commit -m "feat: integrate context into agent runs"
```

### Task 3: Deterministic Model Input Integration

**Files:**
- Modify: `src/minimal_agent/runtime/prompts.py`
- Modify: `src/minimal_agent/runtime/intent_router.py`
- Modify: `src/minimal_agent/runtime/openai_client.py`
- Modify: `src/minimal_agent/runtime/deepseek_client.py`
- Modify: `tests/test_intent_router.py`
- Modify: `tests/test_openai_client.py`
- Modify: `tests/test_deepseek_client.py`
- Modify: `tests/test_runtime_context.py`

**Interfaces:**
- Consumes: `ContextState.resolved` and `ToolLoopRequest.context` from Tasks 1–2.
- Produces: `canonical_context_json(context: dict[str, JsonValue]) -> str` and `IntentRouter.run_intent_only(..., context: dict[str, JsonValue] | None = None)` while leaving `ModelClient.classify_intent(user_input: str)` unchanged.

- [ ] **Step 1: Write failing prompt-boundary tests**

Assert:

- intent classification receives original text unchanged when Context is empty;
- non-empty Context appears as sorted, compact JSON in a labeled `Resolved context` block;
- Intent contract validation still receives the original user text;
- OpenAI and DeepSeek first-step Tool requests include the same canonical Context JSON;
- continuation steps do not create a second Context/user message.

- [ ] **Step 2: Run provider and router tests and verify failure**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_intent_router.py tests/test_openai_client.py tests/test_deepseek_client.py tests/test_runtime_context.py -q`

Expected: FAIL because resolved Context is not included in model-facing input.

- [ ] **Step 3: Add one canonical serializer and route Context to intent**

Add `canonical_context_json` to `runtime/prompts.py` using `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`. Extend `IntentRouter.run_intent_only` with the optional Context parameter, construct the labeled model input only when Context is non-empty, and continue passing the original `user_input` to `IntentRegistry.validate`.

- [ ] **Step 4: Include Context in Tool client initial inputs**

Update both provider `_initial_input` methods to append the labeled canonical Context block only when `request.context` is non-empty. Do not change `ModelClient` or provider method signatures.

- [ ] **Step 5: Run focused tests and lint**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_intent_router.py tests/test_openai_client.py tests/test_deepseek_client.py tests/test_runtime_context.py -q`

Expected: PASS.

Run: `.venv/bin/python -m ruff check src/minimal_agent/runtime tests/test_intent_router.py tests/test_openai_client.py tests/test_deepseek_client.py tests/test_runtime_context.py`

Expected: PASS.

- [ ] **Step 6: Commit model-input integration**

```bash
git add src/minimal_agent/runtime/prompts.py src/minimal_agent/runtime/intent_router.py src/minimal_agent/runtime/openai_client.py src/minimal_agent/runtime/deepseek_client.py tests/test_intent_router.py tests/test_openai_client.py tests/test_deepseek_client.py tests/test_runtime_context.py
git commit -m "feat: provide resolved context to model steps"
```

### Task 4: Truthful Capability Facts and Generated Bundle

**Files:**
- Modify: `src/minimal_agent/capability_facts/modules.py`
- Modify: `src/minimal_agent/capability_facts/evidence.py`
- Modify: `src/minimal_agent/capability_adapter.py`
- Modify: `tests/test_capability_v3_runtime_facts.py`
- Modify: `tests/test_minimal_agent_capability_adapter.py`
- Modify: `tests/test_capability_v3_compiled_topology.py`
- Modify: `tests/test_capability_v3_query_user_bundle.py`
- Modify: `tests/test_capability_v3_resolution.py`
- Modify: generated files under `capabilities/`

**Interfaces:**
- Consumes: tested runtime contracts and Evidence from Tasks 1–3.
- Produces: six supported `context.*` claims, supported `evidence.context_state`, `MinimalAgent.resolve_context` runtime binding, Context-aware Agent schemas, and a validated regenerated Bundle.

- [ ] **Step 1: Replace negative assertions with failing truthful-capability assertions**

Assert all six Context claims are `supported` and reference `evidence.context_state`; Evidence uses `ContextState.model_json_schema()`, lists `context_state_resolved`, and exposes the Context-only/result/Trace observation interfaces. Assert `scope.context` and the relevant chains resolve according to their remaining Tool/Intent dependencies rather than remaining unsupported because of Context.

- [ ] **Step 2: Run capability tests and verify failure**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_runtime_facts.py tests/test_minimal_agent_capability_adapter.py tests/test_capability_v3_compiled_topology.py tests/test_capability_v3_query_user_bundle.py tests/test_capability_v3_resolution.py -q`

Expected: FAIL because current facts explicitly mark Context unsupported.

- [ ] **Step 3: Update runtime-derived facts and adapter schemas**

Remove the `no_conversation_state` unsupported claims. Emit supported claims with `evidence.context_state`; add `context_state_resolved` to orchestration events. Build Evidence payload schema from `ContextState.model_json_schema()`, set production timing to Context resolution, and declare `MinimalAgent.resolve_context`, `agent_result.context_state`, and `events.context_state_resolved` as observation interfaces. Add the Context-only entrypoint/runtime binding and optional Context input schema to `MiniAgentCapabilityAdapter.agent_facts()`.

- [ ] **Step 4: Run capability tests before generation**

Run the Task 4 pytest command again.

Expected: PASS against in-memory compilation.

- [ ] **Step 5: Regenerate and validate the canonical Bundle**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m minimal_agent.capabilities.cli export --spec-root capability_specs --output capabilities
PYTHONPATH=src .venv/bin/python -m minimal_agent.capabilities.cli validate --input capabilities
```

Expected: both commands exit 0; snapshot counts remain 1 Agent, 7 Module, 7 Intent, 0 Tool, 5 Scope, 3 Chain, 5 Evidence, and 7 Boundary; hashes change only where transitive Context references require it.

- [ ] **Step 6: Run generated-bundle parity tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_generator_parity.py tests/test_capability_v3_export.py tests/test_capability_v3_validation.py -q`

Expected: PASS.

- [ ] **Step 7: Commit facts and Bundle**

```bash
git add src/minimal_agent/capability_facts/modules.py src/minimal_agent/capability_facts/evidence.py src/minimal_agent/capability_adapter.py tests/test_capability_v3_runtime_facts.py tests/test_minimal_agent_capability_adapter.py tests/test_capability_v3_compiled_topology.py tests/test_capability_v3_query_user_bundle.py tests/test_capability_v3_resolution.py capabilities
git commit -m "feat: publish supported context capability"
```

### Task 5: Bridge Documentation and Full Verification

**Files:**
- Modify: `docs/CAPABILITY_SNAPSHOT.md`
- Modify: `README.md` only if its public API example would otherwise be incomplete.
- Test: full `tests/` suite.

**Interfaces:**
- Consumes: the final runtime and Bundle from Tasks 1–4.
- Produces: documented Builder/Evaluator bridge for Context execution and Evidence collection.

- [ ] **Step 1: Document the stable Context bridge**

Document `MinimalAgent.resolve_context`, `MinimalAgent.run(..., context=...)`, `ContextUpdate`, `ContextState`, `AgentResult.context_state`, and `context_state_resolved`. State that Builder only reads the generated Bundle, while Evaluator invokes Agent entrypoints and reads result/Trace Evidence. Do not introduce protocol-version wording or evaluator-owned fixtures into Agent capabilities.

- [ ] **Step 2: Run the complete test suite**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q`

Expected: all tests pass, with only explicitly marked environment-dependent skips.

- [ ] **Step 3: Run complete lint and Bundle validation**

Run:

```bash
.venv/bin/python -m ruff check .
PYTHONPATH=src .venv/bin/python -m minimal_agent.capabilities.cli validate --input capabilities
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 4: Confirm scope and generated output**

Run: `git status --short` and `git diff --stat 058d834..HEAD`.

Expected: no unrelated user-owned untracked files are staged or modified; implementation changes match this plan; generated Bundle is present and validates.

- [ ] **Step 5: Commit documentation**

```bash
git add docs/CAPABILITY_SNAPSHOT.md README.md
git commit -m "docs: describe context evaluation bridge"
```

If `README.md` required no change, omit it from `git add`.
