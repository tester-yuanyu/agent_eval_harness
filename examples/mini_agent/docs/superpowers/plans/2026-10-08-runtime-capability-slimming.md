# Runtime and Capability Slimming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Mock/Shadow evaluation support from `minimal_agent` while preserving intent recognition, generic tool execution, configuration-bound capability export, and stable Builder/Evaluator integration surfaces.

**Architecture:** Split production code into `contracts`, `runtime`, and `capabilities` packages. Runtime executes only explicitly registered `ToolDefinition` objects; capability export consumes the same `IntentRegistry` and `ToolRegistry`, so the default zero-tool bundle cannot claim executable Tool support and configured registries produce their own bound bundles.

**Tech Stack:** Python 3.11+, Pydantic v2, OpenAI-compatible model adapters, pytest, Ruff, canonical JSON/SHA-256.

**Spec:** `docs/superpowers/specs/2026-10-08-runtime-capability-slimming-design.md`

## Global Constraints

- Keep all seven current Intent definitions and the public intent-only behavior.
- Preserve `MinimalAgent.run(...)`, `run_intent_only(...)`, `ToolRegistry.register(...)`, `ToolRegistry.invoke(...)`, `export_capability_bundle(...)`, and `validate_capability_bundle(...)` as concepts; document signature migrations.
- Remove all production Shadow/Mock business implementations, seeded data, fault injection, and evaluation-only scripted clients.
- A Tool is executable and snapshot-supported only when it is explicitly registered in the `ToolRegistry` used for that run and export.
- The default composition has no built-in business tools and emits no Tool snapshots.
- Keep strict Pydantic tool arguments, `additionalProperties: false`, and all properties required in function schemas.
- Do not add plugin discovery, network scanning, hidden fallback tools, evaluation cases, expected values, or scoring.
- Never infer or record chain-of-thought; retain only observable input, output, error, and Trace events.
- Use test-first red/green/refactor for every behavior change; run the whole offline suite before completion.

## Target File Map

```text
src/minimal_agent/
├── contracts/
│   ├── __init__.py
│   ├── agent.py                 # ProtocolModel, IntentResult, AgentResult, loop records
│   ├── intent_parameters.py     # seven formal Intent parameter models
│   ├── intents.py               # IntentDefinition, IntentRegistry, default registry
│   └── tools.py                 # ToolResult and immutable ToolContract
├── runtime/
│   ├── __init__.py
│   ├── agent.py                 # generic orchestration and tool loop
│   ├── config.py
│   ├── intent_router.py
│   ├── model_client.py
│   ├── openai_client.py
│   ├── deepseek_client.py
│   ├── prompts.py
│   ├── tool_registry.py         # generic registration, validation, allow-list, invocation
│   └── trace.py
├── capabilities/
│   ├── __init__.py
│   ├── bundle.py
│   ├── catalog.py
│   ├── cli.py
│   ├── hashing.py
│   ├── models.py
│   └── versions.py
├── __init__.py                  # narrow stable facade
└── cli.py                       # empty-default composition; injectable registry factory
tests/
├── support/
│   ├── __init__.py
│   ├── model_client.py          # deterministic test-owned ModelClient
│   └── tools.py                 # deterministic test-owned ToolContract/handler
├── test_runtime_agent.py
├── test_runtime_tool_registry.py
├── test_configured_capabilities.py
└── test_public_api.py
```

Legacy root modules are removed after call sites move. No compatibility module may retain implementation logic.

## Review Focus

- A model requests a name absent from the registry: Task 3 tests a terminal `TOOL_NOT_AVAILABLE` failure with no handler call.
- An Intent names a logical Tool absent from the exported registry: Task 4 tests an empty `tool_refs` list and no dangling child.
- A registry contains a Tool unrelated to any current Intent: Task 4 tests that the Tool is still in Agent scope through `module.tool_registry` and the bundle validates.
- A Tool handler raises an arbitrary exception or `TimeoutError`: Task 3 tests normalized failure/timeout records and observable Trace without fabricated output.
- A checked-in bundle is validated after a stale Tool file is left behind: Task 6 tests rejection of out-of-scope artifacts and regenerates into a clean destination.

---

### Task 1: Separate formal Intent contracts from Shadow naming

**Files:**
- Create: `src/minimal_agent/contracts/__init__.py`
- Create: `src/minimal_agent/contracts/agent.py`
- Create: `src/minimal_agent/contracts/intent_parameters.py`
- Create: `src/minimal_agent/contracts/intents.py`
- Modify: `src/minimal_agent/intent_router.py`
- Modify: `tests/test_intent_contracts.py`
- Modify: `tests/test_query_user_intent_contract.py`
- Modify: `tests/test_schemas.py`

**Interfaces:**
- Consumes: current `ProtocolModel`, Agent result models, seven parameter models, `IntentDefinition`, `IntentRegistry`, and `build_default_intent_registry()`.
- Produces: the same types from `minimal_agent.contracts.agent`, `minimal_agent.contracts.intent_parameters`, and `minimal_agent.contracts.intents`, with no import from any `shadow_*` module.

- [ ] **Step 1: Write failing contract-boundary tests**

Add tests that import the new contract modules, assert
`build_default_intent_registry().intents` is exactly the set
`{"query_information", "prepare_resource", "query_user", "query_gift", "query_pool", "add_backpack_gift", "unsupported"}`, and exercise `query_user`
validation through the new parameter-model location. The mutation caught is
reintroducing a Shadow dependency or losing an Intent during the move.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_intent_contracts.py tests/test_query_user_intent_contract.py tests/test_schemas.py -q`

Expected: FAIL because `minimal_agent.contracts` does not exist.

- [ ] **Step 3: Move contracts without changing behavior**

Move the public Pydantic result models from `schemas.py` to `contracts/agent.py`; move the Intent parameter models currently in `shadow_schemas.py` to `contracts/intent_parameters.py`; move `intent_contracts.py` to `contracts/intents.py`; and update `intent_router.py` imports. Do not rename the seven Intent IDs or change their decision rules.

- [ ] **Step 4: Run focused and router tests**

Run: `.venv/bin/python -m pytest tests/test_intent_contracts.py tests/test_query_user_intent_contract.py tests/test_schemas.py tests/test_intent_router.py tests/test_intent_trace.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the contract extraction**

```bash
git add src/minimal_agent/contracts src/minimal_agent/intent_router.py tests/test_intent_contracts.py tests/test_query_user_intent_contract.py tests/test_schemas.py
git commit -m "refactor: separate formal agent contracts"
```

### Task 2: Build a generic Tool contract and registry

**Files:**
- Create: `src/minimal_agent/contracts/tools.py`
- Create: `src/minimal_agent/runtime/__init__.py`
- Create: `src/minimal_agent/runtime/tool_registry.py`
- Create: `src/minimal_agent/runtime/trace.py`
- Create: `tests/support/__init__.py`
- Create: `tests/support/tools.py`
- Create: `tests/test_runtime_tool_registry.py`

**Interfaces:**
- Consumes: `ProtocolModel` from Task 1 and the existing strict function-schema behavior.
- Produces:
  - `ToolResult(success: bool, code: str, message: str, data: dict[str, Any])`.
  - immutable `ToolContract` with `name`, `version`, `description`, `arguments_model`, `tool_type`, `parameter_rules`, `permission_requirements`, `requires_confirmation`, `risk_level`, `idempotency_rules`, `side_effects`, `result_contracts`, `empty_result_behavior`, `partial_success_behavior`, and `trace_event_types`.
  - `ToolDefinition(contract: ToolContract, handler: ToolHandler)`.
  - `ToolRegistry.definitions: tuple[ToolDefinition, ...]` in registration order.
  - `ToolRegistry.register(definition)`, `get(name)`, `schemas(allowed_tools=None)`, `metadata(allowed_tools=None)`, and `invoke(name, arguments, allowed_tools=None)`.
  - `ToolNotAvailableError.code == "TOOL_NOT_AVAILABLE"`, `ToolNotAllowedError.code == "TOOL_NOT_ALLOWED"`, plus duplicate and invalid-argument errors.

- [ ] **Step 1: Write failing registry tests using one test-owned Tool**

In `tests/support/tools.py`, define a strict `EchoArguments` model, a literal `ToolContract(name="echo", version="test-echo-v1", ...)`, and a handler that returns its input. Test registration order, immutable definitions, strict schema, valid invocation, duplicate rejection, unavailable Tool error code, allow-list denial, and that invalid arguments do not call the handler.

- [ ] **Step 2: Run the registry tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_runtime_tool_registry.py -q`

Expected: FAIL because the new contracts and runtime registry are missing.

- [ ] **Step 3: Implement the minimal generic registry**

Implement the Task 2 interfaces with no imports from `store.py`, `tools.py`, `fault_injection.py`, or any `shadow_*` module. `ToolDefinition.invoke(arguments)` validates with `arguments_model.model_validate`, converts with `model_dump`, calls the handler once, and requires a `ToolResult` return value.

- [ ] **Step 4: Run registry tests and Ruff on the new units**

Run: `.venv/bin/python -m pytest tests/test_runtime_tool_registry.py -q && .venv/bin/ruff check src/minimal_agent/contracts/tools.py src/minimal_agent/runtime/tool_registry.py tests/test_runtime_tool_registry.py`

Expected: PASS.

- [ ] **Step 5: Commit the generic Tool boundary**

```bash
git add src/minimal_agent/contracts/tools.py src/minimal_agent/runtime tests/support tests/test_runtime_tool_registry.py
git commit -m "refactor: add generic tool runtime"
```

### Task 3: Slim the Agent to a generic planning and execution loop

**Files:**
- Create: `src/minimal_agent/runtime/agent.py`
- Create: `src/minimal_agent/runtime/intent_router.py`
- Create: `src/minimal_agent/runtime/model_client.py`
- Create: `src/minimal_agent/runtime/prompts.py`
- Create: `tests/support/model_client.py`
- Create: `tests/test_runtime_agent.py`
- Modify: `src/minimal_agent/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 1 contracts and Intent registry; Task 2 `ToolRegistry`, `ToolResult`, and Trace.
- Produces:
  - `MinimalAgent(model_client, tool_registry, *, max_steps=4, run_id_factory=...)`.
  - `MinimalAgent.run(user_input, *, session_id=None, allowed_tools=None) -> AgentResult`; `fault_config` is removed.
  - `MinimalAgent.run_intent_only(user_input) -> IntentResult` and `intent_trace_snapshot()`.
  - `cli.main(..., openai_client_factory=None, tool_registry_factory=None)`; the default registry factory returns an empty registry.

- [ ] **Step 1: Write failing Agent tests around retained behavior**

Use a test-owned deterministic `ModelClient` and Task 2's `echo` Tool. Cover: intent-only with an empty registry; one complete plan-call-result-answer loop; unavailable function call returns `FAILED` with `TOOL_NOT_AVAILABLE`; invalid arguments do not call the handler; allow-list denial; arbitrary handler failure; `TimeoutError` produces a `TIMEOUT` record; final answer without a Tool; and maximum-step termination. Assert observable `AgentResult` and Trace rather than calls on the model double.

- [ ] **Step 2: Run Agent tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_runtime_agent.py -q`

Expected: FAIL because the slim runtime Agent is missing.

- [ ] **Step 3: Implement the generic Agent loop**

Move only the generic routing, tool-loop, result, maximum-step, and Trace behavior into `runtime/agent.py`. Remove confirmation reply branches, pending state, write mappings, fault-mode selection, Shadow execution contexts, and SQLite references. On unavailable tools, surface the stable error code in the ToolCallRecord/final response and never synthesize output.

- [ ] **Step 4: Simplify the CLI composition**

Remove `--script`, `--database`, and `--profile`; keep `intent`, `run`, `--max-steps`, and optional `--session-id`. Default to `OpenAIModelClient.from_env()` and an empty `ToolRegistry`; tests inject deterministic model and registry factories. Add a CLI test proving no database file is created and another proving an injected registry can complete a Tool run.

- [ ] **Step 5: Run the retained runtime and CLI tests**

Run: `.venv/bin/python -m pytest tests/test_runtime_agent.py tests/test_runtime_tool_registry.py tests/test_cli.py tests/test_intent_router.py tests/test_intent_trace.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the slim runtime**

```bash
git add src/minimal_agent/runtime src/minimal_agent/cli.py tests/support/model_client.py tests/test_runtime_agent.py tests/test_cli.py
git commit -m "refactor: slim agent execution runtime"
```

### Task 4: Make capability construction depend on the configured registries

**Files:**
- Create: `src/minimal_agent/capabilities/__init__.py`
- Create: `src/minimal_agent/capabilities/models.py`
- Create: `src/minimal_agent/capabilities/hashing.py`
- Create: `src/minimal_agent/capabilities/versions.py`
- Create: `src/minimal_agent/capabilities/catalog.py`
- Create: `src/minimal_agent/capabilities/bundle.py`
- Create: `tests/test_configured_capabilities.py`
- Modify: `tests/test_capability_protocol_v2.py`
- Modify: `tests/test_capability_bundle_v2.py`
- Modify: `tests/test_capability_snapshot.py`
- Modify: `tests/test_intent_capability_snapshots_v2.py`
- Modify: `tests/test_module_capability_snapshots_v2.py`
- Modify: `tests/test_tool_capability_snapshots_v2.py`

**Interfaces:**
- Consumes: `IntentRegistry`, `ToolRegistry.definitions`, and `ToolContract` from Tasks 1–2.
- Produces:
  - `build_capability_bundle(intent_registry: IntentRegistry, tool_registry: ToolRegistry) -> CapabilityBundle`.
  - `build_capability_snapshot(snapshot_id, intent_registry, tool_registry) -> SnapshotV2`.
  - `export_capability_bundle(output_root, intent_registry, tool_registry) -> list[Path]`.
  - unchanged canonical hash and `validate_capability_bundle(input_root)` behavior.
  - fixed current Module IDs: `agent_orchestrator`, `model_gateway`, `intent_router`, `tool_loop`, `tool_registry`, `execution_guard`, and `observability`.
  - fixed evidence IDs: `intent_router_output`, `tool_trace`, `permission_event`, and `final_response`.
  - fixed boundaries: `intent_router_only`, `tool_chain`, and `end_to_end`.

- [ ] **Step 1: Write failing zero-tool and one-tool bundle tests**

For the default Intent registry plus an empty Tool registry, assert 1 Agent, 7 Modules, 7 Intents, 0 Tools, empty Intent `tool_refs`, `planning_execution` unsupported for execution modules, and a valid round trip. For a registry containing only test-owned `echo`, assert exactly one Tool snapshot, strict schema metadata copied from `ToolContract`, a supported registry/tool-loop path, Agent scope containing the Tool through `module.tool_registry`, and successful validation even though no current Intent names `echo`.

- [ ] **Step 2: Add failing binding and mismatch tests**

Register a test-owned Tool whose name matches one current Intent's logical Tool and assert only that Intent references it. Export, then delete or alter that Tool and assert validation rejects the missing/hash-mismatched child. Also assert a zero-tool export leaves no stale files when written over a previous one-tool destination.

- [ ] **Step 3: Run configured capability tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_configured_capabilities.py -q`

Expected: FAIL because capability construction still uses the hard-coded six-Tool catalog and old signatures.

- [ ] **Step 4: Implement dynamic snapshot construction**

Move the v2 models and hashing unchanged, then replace hard-coded Tool construction with iteration over `tool_registry.definitions`. Bind Intent references by exact logical Tool name. Remove `state_store`, guarded-write/state-snapshot claims, fault modes, SQLite versions, Shadow entrypoints, and static `TOOL_SNAPSHOT_IDS`; derive Tool IDs from the registry. Export through a staging directory and replace the destination only after in-memory and on-disk validation, so stale artifacts cannot survive.

- [ ] **Step 5: Update validation to derive graph scope from the Agent root**

Keep fixed Module and Intent registries, but validate Tool membership and counts from actual references. Preserve strict schema, safe relative paths, duplicate detection, parent metadata/hash checks, evidence/boundary scope, Agent layer recomputation, and bundle hash recomputation.

- [ ] **Step 6: Run all capability tests**

Run: `.venv/bin/python -m pytest tests/test_configured_capabilities.py tests/test_capability_protocol_v2.py tests/test_capability_bundle_v2.py tests/test_capability_snapshot.py tests/test_intent_capability_snapshots_v2.py tests/test_module_capability_snapshots_v2.py tests/test_tool_capability_snapshots_v2.py -q`

Expected: PASS with dynamic Tool counts and no Shadow assumptions.

- [ ] **Step 7: Commit configuration-bound capabilities**

```bash
git add src/minimal_agent/capabilities tests/test_configured_capabilities.py tests/test_capability_protocol_v2.py tests/test_capability_bundle_v2.py tests/test_capability_snapshot.py tests/test_intent_capability_snapshots_v2.py tests/test_module_capability_snapshots_v2.py tests/test_tool_capability_snapshots_v2.py
git commit -m "refactor: bind capability snapshots to runtime configuration"
```

### Task 5: Move provider adapters and narrow the public API

**Files:**
- Create: `src/minimal_agent/runtime/config.py`
- Create: `src/minimal_agent/runtime/openai_client.py`
- Create: `src/minimal_agent/runtime/deepseek_client.py`
- Modify: `src/minimal_agent/runtime/__init__.py`
- Modify: `src/minimal_agent/contracts/__init__.py`
- Modify: `src/minimal_agent/capabilities/__init__.py`
- Modify: `src/minimal_agent/__init__.py`
- Create: `tests/test_public_api.py`
- Modify: `tests/test_openai_client.py`
- Modify: `tests/test_deepseek_client.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: Tasks 1–4 package paths.
- Produces: top-level exports limited to `MinimalAgent`, `IntentResult`, `AgentResult`, `IntentRegistry`, `build_default_intent_registry`, `ToolContract`, `ToolDefinition`, `ToolRegistry`, `ToolResult`, `run_intent_only`, `build_capability_bundle`, `export_capability_bundle`, and `validate_capability_bundle`. Provider adapters are imported from `minimal_agent.runtime` rather than the root facade.

- [ ] **Step 1: Write a failing public consumer test**

Import only the listed facade names, construct an empty Agent, construct an Agent with the test-owned `echo` Tool, and export both configurations through public APIs. The mutation caught is a facade that imports deleted Shadow modules or omits a required integration surface.

- [ ] **Step 2: Run public and provider tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_public_api.py tests/test_openai_client.py tests/test_deepseek_client.py tests/test_config.py -q`

Expected: FAIL until provider modules and the facade move.

- [ ] **Step 3: Move provider/config code and shrink the facade**

Update internal imports to `contracts` and `runtime`, retain provider behavior, and replace the 200+ name root export list with the exact stable list above. Do not add compatibility exports for Mock/Shadow or fault injection.

- [ ] **Step 4: Run public, provider, and runtime tests**

Run: `.venv/bin/python -m pytest tests/test_public_api.py tests/test_openai_client.py tests/test_deepseek_client.py tests/test_config.py tests/test_runtime_agent.py tests/test_runtime_tool_registry.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the package boundary**

```bash
git add src/minimal_agent/runtime src/minimal_agent/contracts src/minimal_agent/capabilities src/minimal_agent/__init__.py tests/test_public_api.py tests/test_openai_client.py tests/test_deepseek_client.py tests/test_config.py
git commit -m "refactor: expose a narrow agent public api"
```

### Task 6: Remove evaluation-support production code and regenerate the default bundle

**Files:**
- Delete: `src/minimal_agent/agent.py`
- Delete: `src/minimal_agent/capability_bundle.py`
- Delete: `src/minimal_agent/capability_catalog.py`
- Delete: `src/minimal_agent/capability_hashing.py`
- Delete: `src/minimal_agent/capability_models.py`
- Delete: `src/minimal_agent/capability_snapshot.py`
- Delete: `src/minimal_agent/capability_versions.py`
- Delete: `src/minimal_agent/config.py`
- Delete: `src/minimal_agent/deepseek_client.py`
- Delete: `src/minimal_agent/fault_injection.py`
- Delete: `src/minimal_agent/intent_contracts.py`
- Delete: `src/minimal_agent/intent_router.py`
- Delete: `src/minimal_agent/model_client.py`
- Delete: `src/minimal_agent/openai_client.py`
- Delete: `src/minimal_agent/prompts.py`
- Delete: `src/minimal_agent/schemas.py`
- Delete: `src/minimal_agent/scripted_client.py`
- Delete: `src/minimal_agent/shadow_execution.py`
- Delete: `src/minimal_agent/shadow_schemas.py`
- Delete: `src/minimal_agent/shadow_tools.py`
- Delete: `src/minimal_agent/shadow_write_tools.py`
- Delete: `src/minimal_agent/store.py`
- Delete: `src/minimal_agent/tool_contracts.py`
- Delete: `src/minimal_agent/tool_registry.py`
- Delete: `src/minimal_agent/tools.py`
- Delete: `src/minimal_agent/trace.py`
- Delete: `tests/test_agent.py`
- Delete: `tests/test_fault_injection.py`
- Delete: `tests/test_removed_capabilities.py`
- Delete: `tests/test_shadow_agent_integration.py`
- Delete: `tests/test_shadow_execution.py`
- Delete: `tests/test_shadow_fault_trace.py`
- Delete: `tests/test_shadow_schemas.py`
- Delete: `tests/test_shadow_store.py`
- Delete: `tests/test_shadow_tools.py`
- Delete: `tests/test_shadow_write_tools.py`
- Delete: `tests/test_smoke_cases.py`
- Delete: `tests/test_tools.py`
- Delete: `tests/conftest.py`
- Modify: `src/minimal_agent/capabilities/cli.py`
- Modify: `pyproject.toml`
- Regenerate: `capabilities/`

**Interfaces:**
- Consumes: the new packages and passing retained tests from Tasks 1–5.
- Produces: no production import path or generated artifact for Shadow, Mock business data, SQLite state, fault injection, or `ScriptedModelClient`; `python -m minimal_agent.capabilities.cli` exports the default zero-tool bundle.

- [ ] **Step 1: Update the capability CLI tests for the zero-tool default**

Move `tests/test_capability_snapshot_cli.py` to call `minimal_agent.capabilities.cli`; assert 20 artifacts (1 Agent + 7 Module + 7 Intent + 0 Tool + 5 Schema), an empty `tools/` directory, and validation counts with `tool: 0`. Corruption coverage targets an Intent or Module child rather than a removed Tool.

- [ ] **Step 2: Run the CLI test and verify RED**

Run: `.venv/bin/python -m pytest tests/test_capability_snapshot_cli.py -q`

Expected: FAIL while the old CLI still exports six Tool artifacts.

- [ ] **Step 3: Switch the capability CLI and delete obsolete code/tests**

Make the CLI construct `build_default_intent_registry()` and `ToolRegistry()` explicitly. Delete the listed legacy production files only after all retained imports use the new packages. Delete tests whose sole subject is removed Shadow/Mock/store/fault behavior; move any still-relevant generic assertion into Tasks 1–5 tests before deletion. Remove SQLite-specific package metadata if none remains.

- [ ] **Step 4: Regenerate into a temporary directory and replace the checked-in bundle**

Run:

```bash
tmp_bundle="$(mktemp -d)/capabilities"
.venv/bin/python -m minimal_agent.capabilities.cli export --output "$tmp_bundle"
.venv/bin/python -m minimal_agent.capabilities.cli validate --input "$tmp_bundle"
.venv/bin/python -m minimal_agent.capabilities.cli export --output capabilities
.venv/bin/python -m minimal_agent.capabilities.cli validate --input capabilities
```

Expected: both commands exit 0; the temporary bundle has exactly 20 artifacts and zero Tool snapshots. Replace `capabilities/` with this validated output using the implementation's atomic export path, then validate the checked-in directory.

- [ ] **Step 5: Prove removed concepts are absent and stale artifacts fail**

Run: `rg -n "shadow_|Shadow|with_mock_tools|with_shadow|FaultInjection|ToolMode|ScriptedModelClient|mock_users|mock_gifts|mock_pools|mock_backpack" src capabilities`

Expected: no matches. Then run the stale-artifact test from Task 4 and confirm validation rejects an unreferenced Tool file.

- [ ] **Step 6: Run the complete retained test suite**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS; the paid OpenAI smoke may remain explicitly skipped.

- [ ] **Step 7: Commit removal and regenerated artifacts**

```bash
git add -A src tests capabilities pyproject.toml
git commit -m "refactor: remove agent evaluation support"
```

### Task 7: Update integration documentation and perform final verification

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_SPEC.md`
- Modify: `docs/CAPABILITY_SNAPSHOT.md`
- Create: `docs/RUNTIME_CAPABILITY_MIGRATION.md`

**Interfaces:**
- Consumes: final public APIs, CLI paths, bundle counts, and removed API list.
- Produces: Builder/Evaluator instructions for default and configured bundles, real Tool registration example, and explicit migration notes for every breaking removal.

- [ ] **Step 1: Update documentation from the verified implementation**

Document the three-domain architecture, empty default registry, `ToolContract` registration, full-chain condition, intent-only behavior, configuration-bound export signatures, default 20-artifact bundle, and Builder/Evaluator mismatch rejection. Remove all examples using SQLite, Shadow profiles, fault modes, or scripted production clients.

- [ ] **Step 2: Write migration notes**

List removed imports and CLI flags. Give replacement imports for retained concepts and state “no replacement” for Mock/Shadow/store/fault APIs. Explain that deterministic clients and Tools now belong to consumer test support.

- [ ] **Step 3: Run final verification**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/python -m minimal_agent.capabilities.cli validate --input capabilities
```

Expected: all commands succeed, aside from the documented paid smoke skip.

- [ ] **Step 4: Record before/after size evidence**

Run `wc -l` over production `.py` files and count top-level `__all__` names. Record the final figures beside the baseline of 9,453 production Python lines and 116 top-level exports; confirm both materially decreased.

- [ ] **Step 5: Commit documentation and final verified state**

```bash
git add README.md PROJECT_SPEC.md docs/CAPABILITY_SNAPSHOT.md docs/RUNTIME_CAPABILITY_MIGRATION.md
git commit -m "docs: document slim agent integration"
```
