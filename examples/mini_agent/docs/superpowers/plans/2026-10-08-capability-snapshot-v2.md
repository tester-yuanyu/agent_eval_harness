# Capability Snapshot Protocol v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the v1 capability artifacts with one strictly validated v2 current-capability bundle containing 1 Agent, 8 Module, 7 Intent, and 6 Tool snapshots.

**Architecture:** Split the current monolithic snapshot code into strict Pydantic protocol models, a declarative capability catalog, and a bundle exporter/validator. Every child is built in memory first, parent references contain immutable child metadata and hashes, and `agent.json` is written last with a deterministic transitive Bundle hash.

**Tech Stack:** Python 3.11+, Pydantic v2, standard-library JSON/SHA-256/path handling, SQLite-backed existing Agent contracts, Pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-10-08-capability-snapshot-v2-design.md`

## Global Constraints

- Keep Agent runtime and evaluator decoupled; no expected values, scoring rules, case IDs, Judge output, or target capabilities enter snapshots.
- Use only current Pydantic v2 and standard-library dependencies; add no dependency or external service.
- Use `snapshot_format_version="2.0"`, globally unique typed IDs, strict models with unknown fields forbidden, and relative POSIX reference paths.
- Use the existing canonical JSON algorithm; exclude only `snapshot_sha256` from a snapshot's own hash and exclude no other capability field.
- Use exactly five layer names: `understanding`, `context`, `planning_execution`, `safety_recovery`, `result`; `input` remains a schema, not a layer.
- Preserve `run_intent_only()`, `run()`, and `store.snapshot()` behavior and all existing Agent tests.
- Generate only current capabilities. Do not create a target-capability bundle.
- Unknown tools, invalid arguments, timeouts, max steps, dangling references, invalid paths, and hash mismatches must fail explicitly.
- The repository currently has no `HEAD`; do not create a partial initial commit. Execute commit checkpoint steps only if a project baseline exists when implementation starts; otherwise preserve the changes uncommitted and report that condition.

## Review Focus

- A reference path containing an absolute path, `..`, an empty segment, or a backslash must be rejected before any file is read.
- A child file whose content or hash differs from the parent reference must make validation fail with the exact child ID and mismatch field.
- Duplicate snapshot IDs or duplicate normalized paths must fail even when both individual files are valid.
- Unknown JSON fields and invalid `supported`/`unsupported`/`unknown` layer combinations must fail strict schema validation.
- Changing any Module, Intent, or Tool contract must change the recomputed Bundle hash and invalidate stale `agent.json`.

## Protocol hardening addendum

- Formal hierarchy is exactly Agent → Module → Intent → Tool.
- The five Schema artifacts are `agent.schema.json`, `module.schema.json`,
  `intent.schema.json`, `tool.schema.json`, and
  `snapshot-reference.schema.json`.
- Module IDs are exactly `module.agent_orchestrator`, `module.model_gateway`,
  `module.intent_router`, `module.tool_loop`, `module.tool_registry`,
  `module.execution_guard`, `module.state_store`, and `module.observability`.
- Agent owns the strict Evidence Catalog and Execution Boundary Catalog;
  Module layers and Module boundary lists may reference only registered IDs.
- Agent layers expose `supporting_module_ids` and use the unique three-state
  aggregation algorithm from the design spec.
- `generated_at` is excluded from capability snapshots; export time belongs in
  a separate non-capability manifest if it is ever added.

---

## File Structure

- Create `src/minimal_agent/capability_models.py`: v2 enums, strict envelopes, reference, layer, and four snapshot models.
- Create `src/minimal_agent/capability_catalog.py`: current 8/7/6 declarative capability builders and parent-reference construction.
- Create `src/minimal_agent/capability_bundle.py`: canonical Bundle construction, export, reload, graph validation, schema export, and Bundle hash.
- Modify `src/minimal_agent/capability_snapshot.py`: retain canonical hash helpers and expose the v2 public facade/CLI; remove v1 builders after migration.
- Modify `src/minimal_agent/__init__.py`: export only stable v2 public APIs while preserving unrelated Agent APIs.
- Create `tests/test_capability_protocol_v2.py`: strict model, layer-state, ID, path, and JSON Schema tests.
- Create `tests/test_tool_capability_snapshots_v2.py`: six Tool contracts and runtime-output conformance tests.
- Create `tests/test_intent_capability_snapshots_v2.py`: seven Intent contracts and Tool-reference tests.
- Create `tests/test_module_capability_snapshots_v2.py`: eight Module contracts, five-layer completeness, and hierarchy tests.
- Create `tests/test_capability_bundle_v2.py`: Agent aggregation, graph, Bundle hash, export, reload, and tamper tests.
- Create `tests/test_capability_snapshot_cli.py`: export/validate exit-code and diagnostic tests.
- Replace generated files below `capabilities/` with the v2 layout defined in the spec.
- Modify `docs/CAPABILITY_SNAPSHOT.md` and `README.md`: document v2 use, scope selection, migration, and commands.

### Task 1: Strict v2 protocol models and formal JSON Schemas

**Files:**
- Create: `src/minimal_agent/capability_models.py`
- Create: `tests/test_capability_protocol_v2.py`
- Modify: `src/minimal_agent/capability_snapshot.py`

**Interfaces:**
- Consumes: existing `ProtocolModel` and canonical JSON/SHA-256 behavior.
- Produces: `SnapshotReference`, `LayerCapability`, `AgentSnapshotV2`, `ModuleSnapshotV2`, `IntentSnapshotV2`, `ToolSnapshotV2`, `calculate_snapshot_sha256(payload: dict[str, Any]) -> str`, and `snapshot_schema(snapshot_type: SnapshotType) -> dict[str, Any]`.

- [ ] **Step 1: Write failing protocol tests**

Add tests named:

```python
def test_all_v2_envelopes_forbid_unknown_fields(): ...
def test_reference_accepts_only_safe_relative_posix_paths(): ...
def test_supported_layer_requires_inputs_outputs_entrypoints_stop_nodes_and_evidence(): ...
def test_unsupported_and_unknown_layers_require_reason_and_no_fake_evidence(): ...
def test_module_and_agent_require_all_five_layers_exactly_once(): ...
def test_snapshot_hash_excludes_only_its_own_hash(): ...
def test_each_snapshot_type_exports_a_strict_json_schema(): ...
```

- [ ] **Step 2: Run protocol tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_capability_protocol_v2.py -q`

Expected: collection/import failure because v2 models do not exist.

- [ ] **Step 3: Implement the v2 model interfaces**

Use `StrEnum` values for snapshot type, support status, and five layer names. `SnapshotReference` validates typed IDs and safe paths. `LayerCapability` enforces the three-state invariants in a Pydantic `model_validator`; Agent and Module use a fixed model containing all five named layer fields rather than a free-form dictionary.

- [ ] **Step 4: Run protocol tests and existing snapshot tests**

Run: `.venv/bin/python -m pytest tests/test_capability_protocol_v2.py tests/test_capability_snapshot.py -q`

Expected: v2 tests PASS; old snapshot tests remain green until migration task replaces them.

- [ ] **Step 5: Commit the protocol boundary**

```bash
git add src/minimal_agent/capability_models.py src/minimal_agent/capability_snapshot.py tests/test_capability_protocol_v2.py
git commit -m "feat: define capability snapshot v2 protocol"
```

### Task 2: Six strict Tool capability snapshots

**Files:**
- Create: `src/minimal_agent/capability_catalog.py`
- Create: `tests/test_tool_capability_snapshots_v2.py`
- Modify: `src/minimal_agent/capability_models.py`

**Interfaces:**
- Consumes: `ToolSnapshotV2`, six current argument models, tool version constants, `ToolResult`, fault-mode sets, and canonical hash helpers.
- Produces: `TOOL_SNAPSHOT_IDS: frozenset[str]` and `build_tool_snapshots() -> dict[str, ToolSnapshotV2]` keyed by typed Tool ID.

- [ ] **Step 1: Write failing six-Tool catalog tests**

Assert the exact IDs:

```python
{
    "tool.query_information",
    "tool.prepare_resource",
    "tool.query_user_info",
    "tool.query_gift_info",
    "tool.query_pool_config",
    "tool.add_gift_to_backpack",
}
```

For every Tool assert strict Function Schema, all properties required, `additionalProperties=false`, read/write classification, result contracts, permission, confirmation, risk, idempotency, side effects, fault modes, result codes, terminal behavior, Trace events, and reproducible hash. Add representative runtime ToolResult validation for success, empty result, partial success, business error, timeout declaration, and confirmed idempotent write.

- [ ] **Step 2: Run Tool tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_tool_capability_snapshots_v2.py -q`

Expected: FAIL because `build_tool_snapshots` is missing.

- [ ] **Step 3: Implement Tool result-contract and builder models**

Add explicit per-code result-data schemas to `ToolSnapshotV2`; do not infer them from test fixtures. Derive parameter schemas from the existing Pydantic argument models, and derive supported fault modes from the current read/write fault contract. Represent unsupported timeout/rate-limit/empty/partial behaviors explicitly rather than omitting them.

- [ ] **Step 4: Run Tool and runtime tool tests**

Run: `.venv/bin/python -m pytest tests/test_tool_capability_snapshots_v2.py tests/test_tools.py tests/test_shadow_tools.py tests/test_shadow_write_tools.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Tool contracts**

```bash
git add src/minimal_agent/capability_catalog.py src/minimal_agent/capability_models.py tests/test_tool_capability_snapshots_v2.py
git commit -m "feat: build strict tool capability snapshots"
```

### Task 3: Seven Intent capability snapshots

**Files:**
- Modify: `src/minimal_agent/capability_catalog.py`
- Create: `tests/test_intent_capability_snapshots_v2.py`

**Interfaces:**
- Consumes: `build_tool_snapshots()`, `IntentSnapshotV2`, `build_default_intent_registry()`, formal missing-parameter vocabularies, and Prompt/contract version constants.
- Produces: `INTENT_SNAPSHOT_IDS: frozenset[str]` and `build_intent_snapshots(tools: Mapping[str, ToolSnapshotV2]) -> dict[str, IntentSnapshotV2]`.

- [ ] **Step 1: Write failing seven-Intent tests**

Assert exact IDs for `query_information`, `prepare_resource`, `query_user`, `query_gift`, `add_backpack_gift`, `query_pool`, and `unsupported`. Assert each parameter schema equals its registered intent model; status/action rules and missing parameters are explicit; Tool references are current and exact; `intent.unsupported` has no Tool reference; `intent.query_user` preserves all approved format, ambiguity, AND/OR, batch, and correction semantics.

- [ ] **Step 2: Run Intent tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_intent_capability_snapshots_v2.py -q`

Expected: FAIL because the Intent builder is missing.

- [ ] **Step 3: Implement Intent builders from formal registries**

Generate parameter schemas from `IntentDefinition.parameters_model`; keep per-intent semantic rules declarative in `mini_agent`; construct Tool references from built Tool objects so ID/version/hash/path cannot drift. Do not run the Agent or inspect evaluation outputs.

- [ ] **Step 4: Run Intent and intent-router tests**

Run: `.venv/bin/python -m pytest tests/test_intent_capability_snapshots_v2.py tests/test_intent_contracts.py tests/test_query_user_intent_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Intent contracts**

```bash
git add src/minimal_agent/capability_catalog.py tests/test_intent_capability_snapshots_v2.py
git commit -m "feat: build intent capability snapshots"
```

### Task 4: Eight Module snapshots with complete five-layer declarations

**Files:**
- Modify: `src/minimal_agent/capability_catalog.py`
- Create: `tests/test_module_capability_snapshots_v2.py`

**Interfaces:**
- Consumes: `build_intent_snapshots(...)`, `build_tool_snapshots()`, Module protocol models, and current public runtime schemas.
- Produces: `MODULE_SNAPSHOT_IDS: frozenset[str]` and `build_module_snapshots(intents: Mapping[str, IntentSnapshotV2], tools: Mapping[str, ToolSnapshotV2]) -> dict[str, ModuleSnapshotV2]`.

- [ ] **Step 1: Write failing eight-Module tests**

Assert exact Module IDs, all five layers, state rules, input/output schemas, execution boundaries, Mock dependencies, Trace types, upstream/downstream dependencies, and no dangling Intent/Tool references. Assert `module.intent_router` references all seven Intents, `module.tool_registry` references all six Tools, and Context explicitly supports session/run tool context and pending confirmation while declaring long-term Memory, RAG, user-profile memory, and cross-session semantic memory unsupported.

- [ ] **Step 2: Run Module tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_module_capability_snapshots_v2.py -q`

Expected: FAIL because the Module builder is missing.

- [ ] **Step 3: Implement five-layer Module builders**

Build every Intent/Tool reference from child objects. Use `supported`, `unsupported`, or `unknown` for every layer in every Module; never omit a layer and never mark a capability supported without public evidence.

- [ ] **Step 4: Run Module and integration tests**

Run: `.venv/bin/python -m pytest tests/test_module_capability_snapshots_v2.py tests/test_shadow_agent_integration.py tests/test_shadow_execution.py tests/test_shadow_fault_trace.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Module contracts**

```bash
git add src/minimal_agent/capability_catalog.py tests/test_module_capability_snapshots_v2.py
git commit -m "feat: build five-layer module snapshots"
```

### Task 5: Agent root snapshot and deterministic Bundle hash

**Files:**
- Create: `src/minimal_agent/capability_bundle.py`
- Create: `tests/test_capability_bundle_v2.py`

**Interfaces:**
- Consumes: all child builders and `SnapshotReference`.
- Produces: `CapabilityBundle`, `build_capability_bundle() -> CapabilityBundle`, and `calculate_capability_bundle_sha256(references: Sequence[SnapshotReference]) -> str`.

- [ ] **Step 1: Write failing Agent aggregation and propagation tests**

Assert `agent.mini_agent`, all three public entrypoints, eight Module references, exact module topology, current task types, registry/session/state versions, five-layer summary derived from Modules, sorted transitive references, and reproducible Bundle hash. Copy one child with a changed contract and assert both the Bundle hash and parent reference change.

- [ ] **Step 2: Run Bundle tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_capability_bundle_v2.py -q`

Expected: FAIL because `build_capability_bundle` is missing.

- [ ] **Step 3: Implement child-first Bundle construction**

`CapabilityBundle` holds Agent plus typed child maps but is not itself serialized as an extra snapshot. Calculate `capability_bundle_sha256` from all non-Agent references sorted by `snapshot_id`; construct Agent layer summaries from Module states and reject contradictory aggregation.

- [ ] **Step 4: Run Bundle tests**

Run: `.venv/bin/python -m pytest tests/test_capability_bundle_v2.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Agent aggregation**

```bash
git add src/minimal_agent/capability_bundle.py tests/test_capability_bundle_v2.py
git commit -m "feat: add agent capability bundle index"
```

### Task 6: Safe export, reload, and cross-snapshot validation

**Files:**
- Modify: `src/minimal_agent/capability_bundle.py`
- Modify: `tests/test_capability_bundle_v2.py`
- Modify: `src/minimal_agent/__init__.py`

**Interfaces:**
- Consumes: `CapabilityBundle` and four v2 snapshot models.
- Produces: `export_capability_bundle(output_root: str | Path) -> list[Path]`, `validate_capability_bundle(input_root: str | Path) -> BundleValidationResult`, and explicit `CapabilityBundleValidationError` diagnostics.

- [ ] **Step 1: Write failing export and malicious-bundle tests**

Cover round-trip export/reload, unknown fields, absolute/parent/backslash paths, duplicate IDs, duplicate normalized paths, missing files, type/version/hash/path mismatches, dangling Module/Intent/Tool references, child outside parent scope, stale Agent layer aggregation, and stale Bundle hash.

- [ ] **Step 2: Run validation tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_capability_bundle_v2.py -q`

Expected: FAIL on missing export/validation APIs.

- [ ] **Step 3: Implement transactional-style export and read-only validation**

Build and validate all objects before writing. Write children and JSON Schemas first and `agent.json` last. Validation resolves paths only below the supplied root, parses by declared snapshot type with strict Pydantic models, and accumulates deterministic diagnostics without modifying input files.

- [ ] **Step 4: Run Bundle tests and public import smoke test**

Run: `.venv/bin/python -m pytest tests/test_capability_bundle_v2.py -q`

Run: `.venv/bin/python -c "from minimal_agent import export_capability_bundle, validate_capability_bundle"`

Expected: PASS.

- [ ] **Step 5: Commit export and validation**

```bash
git add src/minimal_agent/capability_bundle.py src/minimal_agent/__init__.py tests/test_capability_bundle_v2.py
git commit -m "feat: export and validate capability bundles"
```

### Task 7: CLI, generated v2 artifacts, and v1 migration

**Files:**
- Modify: `src/minimal_agent/capability_snapshot.py`
- Create: `tests/test_capability_snapshot_cli.py`
- Replace: `capabilities/agent.json`
- Replace: `capabilities/modules/*.json`
- Create: `capabilities/intents/*.json`
- Replace: `capabilities/tools/*.json`
- Create: `capabilities/schemas/*.schema.json`
- Delete after v2 verification: `capabilities/intent_router.json`, `capabilities/query_user.json`
- Modify: `tests/test_capability_snapshot.py`

**Interfaces:**
- Consumes: `export_capability_bundle` and `validate_capability_bundle`.
- Produces: `python -m minimal_agent.capability_snapshot export --output PATH` and `python -m minimal_agent.capability_snapshot validate --input PATH`.

- [ ] **Step 1: Write failing CLI tests**

Assert export returns 0 and writes the exact 1/8/7/6 plus five Schema artifacts; validate returns 0 for a fresh export; corrupted child hash, unknown field, and dangling path each return nonzero with a concise machine-readable error on stderr.

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_capability_snapshot_cli.py -q`

Expected: FAIL because CLI subcommands are missing.

- [ ] **Step 3: Implement CLI and update the public facade**

Use `argparse`, no network access, and no environment API key. Keep `build_capability_snapshot(snapshot_id)` only as a compatibility function for current typed IDs during migration; its outputs must be v2.

- [ ] **Step 4: Generate into a temporary directory and validate before replacing checked-in artifacts**

Run:

```bash
tmp_dir="$(mktemp -d)"
.venv/bin/python -m minimal_agent.capability_snapshot export --output "$tmp_dir"
.venv/bin/python -m minimal_agent.capability_snapshot validate --input "$tmp_dir"
```

Expected: both commands exit 0 and the temporary directory has the exact artifact counts.

- [ ] **Step 5: Replace checked-in v1 artifacts using the validated exporter**

Run: `.venv/bin/python -m minimal_agent.capability_snapshot export --output capabilities`

Then remove the two reproducible v1 root snapshots with `apply_patch`, and run validation against `capabilities`.

- [ ] **Step 6: Run CLI and checked-in-artifact tests**

Run: `.venv/bin/python -m pytest tests/test_capability_snapshot_cli.py tests/test_capability_snapshot.py -q`

Expected: PASS with no v1 artifact accepted as a second capability source.

- [ ] **Step 7: Commit generated artifacts and CLI**

```bash
git add src/minimal_agent/capability_snapshot.py tests/test_capability_snapshot.py tests/test_capability_snapshot_cli.py capabilities
git commit -m "feat: publish capability snapshot v2 bundle"
```

### Task 8: Documentation and full regression verification

**Files:**
- Modify: `docs/CAPABILITY_SNAPSHOT.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: final v2 APIs and CLI.
- Produces: Builder-facing protocol instructions, Module/Intent/Tool Suite selection examples, and exact validation commands.

- [ ] **Step 1: Update Builder consumption documentation**

Document that `agent.json` is the only root; Module Suite `query_user` loads Agent + `module.intent_router` + `intent.query_user` while only validating the referenced `tool.query_user_info`; Link and E2E Suites additionally consume relevant execution Module and Tool contracts.

- [ ] **Step 2: Document current-versus-target and migration boundaries**

State that no target bundle exists, Builder must reject unknown as support, v1 root files are obsolete, and any child change requires a new parent reference and Bundle hash.

- [ ] **Step 3: Run focused v2 verification**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_capability_protocol_v2.py \
  tests/test_tool_capability_snapshots_v2.py \
  tests/test_intent_capability_snapshots_v2.py \
  tests/test_module_capability_snapshots_v2.py \
  tests/test_capability_bundle_v2.py \
  tests/test_capability_snapshot_cli.py -q
```

Expected: all focused v2 tests PASS.

- [ ] **Step 4: Run final full verification**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/python -m minimal_agent.capability_snapshot validate --input capabilities
```

Expected: all tests PASS except the existing opt-in paid OpenAI smoke skip; Ruff passes; bundle validation exits 0.

- [ ] **Step 5: Commit documentation and final verification state**

```bash
git add README.md docs/CAPABILITY_SNAPSHOT.md
git commit -m "docs: document capability snapshot v2"
```
