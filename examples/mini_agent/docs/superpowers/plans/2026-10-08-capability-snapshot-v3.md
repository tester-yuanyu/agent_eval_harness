# Capability Snapshot Protocol v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a truthful, composable Capability Snapshot Protocol v3 that preserves v2 unchanged and lets Builder resolve Scope/Chain + Intent + optional registered Tool into a three-state capability graph.

**Architecture:** Keep the existing `minimal_agent.capabilities` v2 API and checked-in `capabilities/` bundle immutable. Implement v3 in a separate `minimal_agent.capabilities.v3` package and export to `capabilities-v3/`; v3 uses a one-way DAG of Agent, Scope, Chain, Module, Intent, Tool, Evidence, and Boundary artifacts. A separate resolver computes combination support after selection, while the exporter only records configuration-bound facts and requirements.

**Tech Stack:** Python 3.11+, Pydantic v2, dataclasses, canonical JSON/SHA-256, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-10-08-capability-snapshot-v3-design.md`

## Global Constraints

- Existing v2 models, schemas, CLI behavior, checked-in `capabilities/`, public functions, hashes, and default 20-artifact bundle remain unchanged.
- Every v3 artifact uses `snapshot_format_version: "3.0"`; v3 strong references may target only v3 artifacts.
- The default runtime and default v3 bundle contain zero Tools; `Intent.tool_refs` is empty unless a matching Tool is explicitly registered.
- `required_tool_name` expresses an Intent requirement and never creates a Tool snapshot or reference.
- Scope and Chain contain requirements and topology, never a precomputed universal `support_status`.
- Builder/resolver computes `supported`, `unsupported`, or `unknown`; missing facts never become supported.
- The reference graph is one-way. Tool snapshots contain no reverse references.
- Evaluation adapter snapshots may describe simulator protocol and supported result categories but never fixture rows, concrete responses, or fault-trigger data.
- Do not materialize Tool × Scope or Tool × Chain combination snapshots.
- No new runtime dependency is added; top-level `minimal_agent.__all__` remains 13 names.

## Review Focus

- A crafted v3 cycle through permitted Module dependency references must be rejected with a cycle path; Task 6 adds the test.
- An Intent requiring a Tool while the selected/default bundle has no matching registered Tool must resolve `unsupported`, not be inferred or crash; Task 7 adds the test.
- A v3 reference carrying a valid v2 ID/hash but format `2.0` must be rejected before graph traversal; Tasks 2 and 6 add tests.
- A required capability marked supported but lacking required Evidence, or referencing Evidence whose availability is not supported, must not resolve supported; Task 7 adds the test.
- Re-exporting over a directory containing stale Tool/Scope/Chain files must remove them and produce byte-identical canonical output; Task 6 adds the test.

## File Structure

- `src/minimal_agent/capabilities/v3/models.py`: strict v3 envelopes,
  requirements, claims, references, and resolved-result models.
- `src/minimal_agent/capabilities/v3/versions.py`: v3-only format and contract
  version constants.
- `src/minimal_agent/capabilities/v3/runtime_catalog.py`: facts derived from
  configured Intent/Tool registries and the versioned runtime Module catalog.
- `src/minimal_agent/capabilities/v3/topology_catalog.py`: reusable Evidence,
  Boundary, Scope, and Chain requirement definitions.
- `src/minimal_agent/capabilities/v3/bundle.py`: bundle construction, canonical
  serialization, schema artifacts, and atomic export integration.
- `src/minimal_agent/capabilities/v3/validation.py`: typed loading, hashes,
  reference closure, cycle checks, and bundle validation.
- `src/minimal_agent/capabilities/v3/resolution.py`: selection binding and
  three-state Resolved Capability Graph computation.
- `src/minimal_agent/capabilities/v3/diffing.py`: bundle delta and in-memory
  affected-root analysis.
- `src/minimal_agent/capabilities/v3/cli.py`: v3-only export, validate, resolve,
  and diff commands.
- `src/minimal_agent/testing/query_user_tool.py`: fixture-free QueryUser
  evaluation Tool contract and injected handler adapter.
- `capabilities-v3/`: checked-in default v3 bundle, separate from immutable v2
  `capabilities/`.
- `tests/fixtures/capability_v3/`: machine-readable Builder selection and
  resolved-graph contract fixtures; no business fixture rows.
- `docs/CAPABILITY_SNAPSHOT_V3.md`: consumer protocol and migration guide.

---

### Task 1: Freeze v2 and add implementation metadata to Tool contracts

**Files:**
- Modify: `src/minimal_agent/contracts/tools.py`
- Test: `tests/test_capability_v2_compatibility.py`
- Test: `tests/test_runtime_tool_registry.py`

**Interfaces:**
- Consumes: current `ToolContract` and v2 `build_capability_bundle`/`export_capability_bundle`.
- Produces: `ToolContract.implementation_profile: Literal["production", "evaluation_adapter", "test_fixture"]`, `ToolContract.simulation_capabilities: tuple[str, ...]`, and `ToolContract.observation_interfaces: tuple[str, ...]`, all with backward-compatible defaults.
- Preserves: every v2 serialized artifact and the current default bundle hash.

- [ ] **Step 1: Write failing v2 compatibility and Tool metadata tests**

Add tests named:

```python
def test_v2_default_export_is_byte_identical_after_v3_metadata_extension(): ...
def test_tool_contract_defaults_to_production_without_simulation_metadata(): ...
def test_tool_contract_accepts_explicit_evaluation_adapter_metadata(): ...
```

The first exports v2 to a temporary directory and compares every relative file and byte with checked-in `capabilities/`. The metadata tests assert the exact defaults and explicit evaluation values.

- [ ] **Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v2_compatibility.py tests/test_runtime_tool_registry.py -q`

Expected: metadata tests FAIL because the three fields do not exist; all pre-existing registry tests still pass.

- [ ] **Step 3: Extend `ToolContract` with optional metadata**

Append the three defaulted fields after existing required fields. Validate that evaluation-only simulation capability strings and observation interfaces are non-empty; do not add them to any v2 model or exporter.

- [ ] **Step 4: Verify GREEN and v2 stability**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v2_compatibility.py tests/test_capability_protocol_v2.py tests/test_capability_snapshot.py tests/test_runtime_tool_registry.py -q`

Expected: PASS; temporary v2 export is byte-identical to `capabilities/`.

- [ ] **Step 5: Commit**

```bash
git add src/minimal_agent/contracts/tools.py tests/test_capability_v2_compatibility.py tests/test_runtime_tool_registry.py
git commit -m "feat: add configuration profile metadata to tool contracts"
```

### Task 2: Define strict v3 artifact and requirement models

**Files:**
- Create: `src/minimal_agent/capabilities/v3/__init__.py`
- Create: `src/minimal_agent/capabilities/v3/models.py`
- Create: `src/minimal_agent/capabilities/v3/versions.py`
- Test: `tests/test_capability_protocol_v3.py`

**Interfaces:**
- Consumes: `ProtocolModel`, canonical typed IDs, and the spec's one-way graph.
- Produces: `SnapshotTypeV3`, `SupportStatusV3`, `SnapshotReferenceV3`, `CapabilityClaimV3`, `CapabilityProviderV3`, `CapabilityRequirementV3`, `AgentSnapshotV3`, `ModuleSnapshotV3`, `IntentSnapshotV3`, `ToolSnapshotV3`, `ScopeSnapshotV3`, `ChainNodeV3`, `ChainSnapshotV3`, `EvidenceSnapshotV3`, `BoundarySnapshotV3`, `SnapshotV3`, and `snapshot_schema_v3(snapshot_type)`.
- Produces constants `SNAPSHOT_FORMAT_VERSION_V3 = "3.0"` and `AGENT_CONTRACT_VERSION_V3 = "mini-agent-capability-contract-v3"`.

- [ ] **Step 1: Write failing envelope and reference tests**

Add tests that assert:

- all eight artifact models reject unknown fields;
- typed IDs use `agent|module|intent|tool|scope|chain|evidence|boundary` prefixes;
- references require relative POSIX JSON paths and literal format `3.0`;
- a `2.0` reference fails validation even with an otherwise valid target ID/hash;
- Scope and Chain reject a top-level `support_status` field;
- Capability claims require a reason for `unsupported`/`unknown` and Evidence for `supported` when the claim declares observable output;
- every v3 snapshot type emits a strict JSON Schema.

- [ ] **Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_protocol_v3.py -q`

Expected: FAIL because `minimal_agent.capabilities.v3` does not exist.

- [ ] **Step 3: Implement the v3 models**

Use these binding shapes:

```python
class CapabilityProviderV3(ProtocolModel):
    role: Literal["selected_intent", "selected_tool", "snapshot"]
    snapshot_id: str | None

class CapabilityRequirementV3(ProtocolModel):
    requirement_id: str
    capability_key: str
    provider: CapabilityProviderV3
    mandatory: bool
    evidence_ids: list[str]

class CapabilityClaimV3(ProtocolModel):
    capability_key: str
    support_status: SupportStatusV3
    evidence_ids: list[str]
    reason: str | None
```

Every snapshot uses the strict v3 envelope and `source_hashes`. Agent contains typed reference lists for every child type. Scope and Chain contain requirements/topology only. Tool has no generic child reference list.

Use these additional binding fields:

- Agent: `capabilities` plus `module_refs`, `intent_refs`, `tool_refs`,
  `scope_refs`, `chain_refs`, `evidence_refs`, and `boundary_refs`.
- Module: `capabilities`, `module_refs`, `intent_refs`, and `tool_refs`.
- Intent: parameter/decision/semantic contracts, `required_tool_name`,
  `capabilities`, and optional `tool_refs`.
- Tool: execution/result/safety metadata, `registered: Literal[True]`, and
  `capabilities`; no outbound strong references.
- Evidence: producer/consumer/timing/payload/observation fields plus one
  availability `CapabilityClaimV3`.
- Boundary: entry/stop/allowed/prohibited/terminal/Evidence fields.
- Scope: Module/Evidence/Boundary refs, requirements, and completion condition.
- Chain: ordered `ChainNodeV3` values, Module/Evidence/Boundary refs,
  requirements, branch definitions, and completion condition.

- [ ] **Step 4: Verify GREEN and static checks**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_protocol_v3.py -q
PYTHONPATH=src .venv/bin/python -m ruff check src/minimal_agent/capabilities/v3 tests/test_capability_protocol_v3.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/minimal_agent/capabilities/v3 tests/test_capability_protocol_v3.py
git commit -m "feat: define capability snapshot protocol v3 models"
```

### Task 3: Build truthful Module, Intent, and Tool catalogs

**Files:**
- Create: `src/minimal_agent/capabilities/v3/runtime_catalog.py`
- Test: `tests/test_capability_v3_runtime_catalog.py`

**Interfaces:**
- Consumes: Task 2 models, configured `IntentRegistry`, configured `ToolRegistry`, and Task 1 Tool metadata.
- Produces: `reference_for_snapshot_v3(snapshot: SnapshotV3) -> SnapshotReferenceV3`.
- Produces: `build_module_snapshots_v3(intents: Mapping[str, IntentSnapshotV3], tools: Mapping[str, ToolSnapshotV3]) -> dict[str, ModuleSnapshotV3]`.
- Produces: `build_intent_snapshots_v3(registry: IntentRegistry, tools: Mapping[str, ToolSnapshotV3]) -> dict[str, IntentSnapshotV3]`.
- Produces: `build_tool_snapshots_v3(registry: ToolRegistry) -> dict[str, ToolSnapshotV3]`.
- Produces: `aggregate_agent_capabilities_v3(modules: Mapping[str, ModuleSnapshotV3]) -> list[CapabilityClaimV3]` using mandatory dependency closure, not any-child support.

- [ ] **Step 1: Write failing runtime catalog tests**

Cover:

- seven Module snapshots exist and no Module claims all five layers generically;
- `module.intent_router` supports formal intent validation with actual intent Evidence;
- general multi-turn inheritance/override/cleanup claims are `unsupported` or `unknown` with reasons;
- zero-Tool export produces no Tool snapshots and every Intent has empty `tool_refs` while retaining `required_tool_name`;
- registering only `query_information` produces exactly that Tool snapshot and only the matching Intent reference;
- Tool v3 output includes implementation profile, result protocols, permissions, risk, side effects, idempotency, retry/timeout/rate-limit claims, and observation interfaces without fixture values;
- Agent aggregation refuses a supported parent when a mandatory child claim is unsupported or unknown.

- [ ] **Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_runtime_catalog.py -q`

Expected: FAIL because the runtime catalog functions do not exist.

- [ ] **Step 3: Implement a versioned, code-backed runtime catalog**

Declare capability keys per real entrypoint and emitted event. Do not copy v2's blanket `_supported_layer` behavior. Treat registered-Tool availability as a separate configuration fact so Module code support does not manufacture an executable Tool path.

- [ ] **Step 4: Verify GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_runtime_catalog.py tests/test_configured_capabilities.py -q`

Expected: PASS; v2 configured-capability tests remain unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/minimal_agent/capabilities/v3/runtime_catalog.py tests/test_capability_v3_runtime_catalog.py
git commit -m "feat: export truthful v3 runtime capability facts"
```

### Task 4: Add reusable Evidence, Boundary, Scope, and Chain catalogs

**Files:**
- Create: `src/minimal_agent/capabilities/v3/topology_catalog.py`
- Test: `tests/test_capability_v3_topology.py`

**Interfaces:**
- Consumes: Task 2 requirement/topology models and Task 3 Module IDs/capability keys.
- Produces: `build_evidence_snapshots_v3() -> dict[str, EvidenceSnapshotV3]` with five artifacts: intent output, context state, Tool trace, safety/recovery event, and final response.
- Produces: `build_boundary_snapshots_v3() -> dict[str, BoundarySnapshotV3]` with five single-layer boundaries plus critical-chain and end-to-end boundaries.
- Produces: `build_scope_snapshots_v3(modules: Mapping[str, ModuleSnapshotV3], evidence: Mapping[str, EvidenceSnapshotV3], boundaries: Mapping[str, BoundarySnapshotV3]) -> dict[str, ScopeSnapshotV3]` for the five canonical layers.
- Produces: `build_chain_snapshots_v3(modules: Mapping[str, ModuleSnapshotV3], evidence: Mapping[str, EvidenceSnapshotV3], boundaries: Mapping[str, BoundarySnapshotV3]) -> dict[str, ChainSnapshotV3]` for understanding→planning, planning→result, and reusable end-to-end chains.

- [ ] **Step 1: Write failing topology tests**

Assert exact catalog IDs and that:

- Scope/Chain have no resolved support status;
- each Scope declares entry, stop, allowed/prohibited Modules, requirements, Evidence, and completion condition;
- Context requires inheritance, correction, cancellation, isolation, residual-state handling, and cleanup without claiming those requirements are met;
- Chains order nodes and declare normal, error, and early-stop paths;
- generic Chains use `selected_intent`/`selected_tool` provider roles and contain no concrete Tool ID;
- every referenced Evidence/Boundary/Module exists;
- event-type lists are a subset of events actually emitted by runtime code, while unavailable context-state Evidence is explicitly unavailable rather than fabricated.

- [ ] **Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_topology.py -q`

Expected: FAIL because the topology catalog does not exist.

- [ ] **Step 3: Implement the topology catalogs**

Keep completion conditions structural—entry reached, required nodes traversed, stop boundary reached, required Evidence observed. Do not include coverage counts, expected answers, scoring, or Judge rules.

- [ ] **Step 4: Verify GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_topology.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/minimal_agent/capabilities/v3/topology_catalog.py tests/test_capability_v3_topology.py
git commit -m "feat: add reusable v3 scope and chain topology"
```

### Task 5: Build and deterministically serialize separate v3 bundles

**Files:**
- Create: `src/minimal_agent/capabilities/v3/bundle.py`
- Test: `tests/test_capability_v3_export.py`

**Interfaces:**
- Consumes: Tasks 2–4 catalogs and existing canonical hashing helpers.
- Produces: frozen `CapabilityBundleV3` with Agent plus all seven child maps.
- Produces: `build_capability_bundle_v3(intent_registry: IntentRegistry, tool_registry: ToolRegistry) -> CapabilityBundleV3`.
- Produces: `build_capability_snapshot_v3(snapshot_id: str, intent_registry: IntentRegistry, tool_registry: ToolRegistry) -> SnapshotV3`.
- Produces internal `_write_capability_bundle_v3(output_root: Path, bundle: CapabilityBundleV3) -> list[Path]`; public validated export is added in Task 6.
- Produces: `schema_artifacts_v3() -> dict[str, dict[str, object]]` for Agent, Module, Intent, Tool, Scope, Chain, Evidence, Boundary, and reference schemas.

- [ ] **Step 1: Write failing bundle/serialization tests**

Assert:

- root Agent references every child artifact type and is the sole root;
- default bundle contains 7 Modules, 7 Intents, 0 Tools, 5 Scopes, 3 Chains, 5 Evidence artifacts, and 7 Boundaries;
- all nine strict Schema artifacts are exported under `capabilities-v3/schemas/`;
- every snapshot and root bundle hash is deterministic;
- two independent serializations are byte-identical;
- an empty Tool directory contains only `.gitkeep`, which is excluded from artifact counts and hashes;
- existing `capabilities/` is not read or modified.

- [ ] **Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_export.py -q`

Expected: FAIL because v3 bundle/serialization functions do not exist.

- [ ] **Step 3: Implement construction, hashing, and deterministic serialization**

Reuse v2 canonical JSON/hash helpers but not v2 model unions or schemas. `_write_capability_bundle_v3` writes only into a caller-supplied fresh directory; it never replaces an existing bundle and is not exported from `v3.__init__`.

- [ ] **Step 4: Verify GREEN and v2 isolation**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_export.py tests/test_capability_snapshot.py -q`

Expected: PASS; v2 checked-in bundle comparison remains green.

- [ ] **Step 5: Commit**

```bash
git add src/minimal_agent/capabilities/v3/bundle.py tests/test_capability_v3_export.py
git commit -m "feat: build isolated capability v3 bundles"
```

### Task 6: Validate v3 schemas, references, DAGs, and truthful aggregation

**Files:**
- Create: `src/minimal_agent/capabilities/v3/validation.py`
- Modify: `src/minimal_agent/capabilities/v3/bundle.py`
- Test: `tests/test_capability_v3_validation.py`

**Interfaces:**
- Consumes: `CapabilityBundleV3`, all v3 models, reference mapping, schema artifacts, and Agent aggregation from previous tasks.
- Produces: `CapabilityBundleValidationErrorV3` with sorted structured diagnostics.
- Produces: `BundleValidationResultV3` with per-type counts, bundle Hash, and Agent Hash.
- Produces: `validate_capability_bundle_v3(input_root: str | Path) -> BundleValidationResultV3`.
- Produces: `load_capability_bundle_v3(input_root: str | Path) -> CapabilityBundleV3`, which validates first and returns the complete typed bundle.
- Produces: `export_capability_bundle_v3(output_root: str | Path, intent_registry: IntentRegistry, tool_registry: ToolRegistry) -> list[Path]`, which stages, validates, and atomically replaces a complete v3 root.
- Produces: `collect_snapshot_references_v3(snapshot: SnapshotV3) -> tuple[SnapshotReferenceV3, ...]`.

- [ ] **Step 1: Write failing validation tests**

Cover valid default/configured bundles and rejection of:

- unknown fields and malformed Schema artifacts;
- file or bundle Hash mismatch;
- duplicate IDs, illegal paths, path/ID/type mismatch, dangling references, and artifacts outside Agent scope;
- a crafted Module A→Module B→Module A dependency cycle with the full cycle path in diagnostics;
- any `2.0` strong reference in a v3 artifact;
- illegal outbound/reverse references from Tool;
- Scope/Chain references to absent Evidence, Boundary, or Module;
- Agent capability summary inconsistent with mandatory Module dependencies;
- a supported observable claim lacking valid Evidence;
- exporting zero Tools over a configured root removes stale Tool and unrelated stale JSON files;
- stale Scope/Chain files disappear because export atomically replaces the complete root;
- repeated atomic exports are byte-identical.

- [ ] **Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_validation.py -q`

Expected: FAIL because the validator does not exist.

- [ ] **Step 3: Implement validation and public atomic export**

Traverse generic references from the root, perform DFS cycle detection with a recursion stack, verify closure and schemas, recompute hashes, and recompute Agent aggregation. Public export builds into a sibling temporary directory through Task 5's internal writer, validates the staged root, then atomically replaces the destination with rollback on failure.

- [ ] **Step 4: Verify GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_validation.py tests/test_capability_v3_export.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/minimal_agent/capabilities/v3/validation.py src/minimal_agent/capabilities/v3/bundle.py tests/test_capability_v3_validation.py
git commit -m "feat: validate capability v3 reference graphs"
```

### Task 7: Resolve selected capabilities into a three-state graph

**Files:**
- Create: `src/minimal_agent/capabilities/v3/resolution.py`
- Test: `tests/test_capability_v3_resolution.py`

**Interfaces:**
- Consumes: a validated `CapabilityBundleV3`, Scope/Chain requirements, selected Intent, and optional selected Tool.
- Produces: `CapabilitySelectionV3(scope_or_chain_id: str, intent_id: str, tool_id: str | None)`.
- Produces: `ResolvedRequirementV3(requirement_id, capability_key, provider_snapshot_ids, evidence_ids, support_status, diagnostics)`.
- Produces: `ResolvedCapabilityGraphV3(selection, support_status, snapshot_ids, requirements, diagnostics)`.
- Produces: `resolve_capability_graph_v3(bundle: CapabilityBundleV3, selection: CapabilitySelectionV3) -> ResolvedCapabilityGraphV3`.

- [ ] **Step 1: Write failing resolution tests**

Pin the rules:

- a mandatory provider claim explicitly `unsupported` makes the requirement and graph unsupported;
- otherwise a missing provider, missing claim, or unknown claim makes it unknown;
- supported requires every mandatory provider claim, compatible version, and required Evidence to be supported;
- optional unmet requirements appear in diagnostics but do not lower overall status;
- default `intent.query_user` plus an execution Scope requiring its Tool resolves unsupported because no matching Tool is registered;
- selecting an unrelated registered Tool resolves unsupported with a required-tool mismatch diagnostic;
- missing required Evidence or Evidence with unavailable support never resolves supported;
- Scope/Chain source snapshots remain unchanged and contain no cached result;
- repeated resolution returns identical canonical output.

- [ ] **Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_resolution.py -q`

Expected: FAIL because the resolver does not exist.

- [ ] **Step 3: Implement deterministic requirement binding and resolution**

Resolve provider roles as follows: `selected_intent` binds the selected Intent; `selected_tool` binds the selected Tool only after matching the Intent's `required_tool_name`; `snapshot` binds its exact ID. Apply explicit unsupported first, then missing/unknown, then supported. Include the dependency path in every diagnostic.

- [ ] **Step 4: Verify GREEN**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_resolution.py tests/test_capability_v3_validation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/minimal_agent/capabilities/v3/resolution.py tests/test_capability_v3_resolution.py
git commit -m "feat: resolve composable capability v3 selections"
```

### Task 8: Add a fixture-free QueryUser evaluation adapter

**Files:**
- Create: `src/minimal_agent/testing/__init__.py`
- Create: `src/minimal_agent/testing/query_user_tool.py`
- Test: `tests/test_query_user_evaluation_adapter.py`
- Test: `tests/test_capability_v3_query_user_bundle.py`

**Interfaces:**
- Consumes: existing `QueryUserInfoArguments`, `ToolDefinition`, `ToolResult`, Task 1 Tool metadata, and v3 exporter/resolver.
- Produces: `QUERY_USER_EVALUATION_CONTRACT: ToolContract` named `query_user_info`, versioned independently, with `implementation_profile="evaluation_adapter"`.
- Produces: `QueryUserEvaluationHandler = Callable[..., ToolResult]`.
- Produces: `query_user_evaluation_definition(handler: QueryUserEvaluationHandler) -> ToolDefinition`.
- Preserves: no built-in users, responses, database path, fault triggers, or automatic registry mutation.

- [ ] **Step 1: Write failing adapter and configured-bundle tests**

Assert:

- the adapter cannot be constructed without an explicit handler;
- strict single/multi-condition QueryUser arguments are validated by the existing model;
- the injected handler supplies deterministic results owned by the test fixture;
- the Tool contract declares evaluation profile, simulator protocol/version, result categories, no side effects, low risk, no confirmation, and Evidence interfaces;
- default v3 bundle remains zero Tool and `intent.query_user.tool_refs=[]`;
- explicitly registering the adapter creates exactly `tool.query_user_info`, adds only the matching Intent reference, changes root/bundle hashes, and leaves fixture values absent from every artifact;
- understanding and applicable QueryUser execution selections resolve from the configured bundle without turning unsupported Context features into supported facts.

- [ ] **Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_query_user_evaluation_adapter.py tests/test_capability_v3_query_user_bundle.py -q`

Expected: FAIL because `minimal_agent.testing.query_user_tool` does not exist.

- [ ] **Step 3: Implement the injected adapter contract**

The adapter binds only contract metadata and the caller's handler. It never stores or synthesizes records. Export sees it only when the caller registers its returned `ToolDefinition`.

- [ ] **Step 4: Verify GREEN and default isolation**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_query_user_evaluation_adapter.py tests/test_capability_v3_query_user_bundle.py tests/test_capability_snapshot.py -q`

Expected: PASS; v2 default bundle remains byte-identical and zero Tool.

- [ ] **Step 5: Commit**

```bash
git add src/minimal_agent/testing tests/test_query_user_evaluation_adapter.py tests/test_capability_v3_query_user_bundle.py
git commit -m "feat: add query user evaluation adapter"
```

### Task 9: Publish v3 CLI, checked-in bundle, diff, docs, and Builder fixtures

**Files:**
- Create: `src/minimal_agent/capabilities/v3/cli.py`
- Create: `src/minimal_agent/capabilities/v3/diffing.py`
- Create: `tests/test_capability_v3_cli.py`
- Create: `tests/test_capability_v3_diff.py`
- Create: `tests/test_capability_v3_builder_contract.py`
- Create: `tests/fixtures/capability_v3/query_user_understanding.selection.json`
- Create: `tests/fixtures/capability_v3/query_user_understanding.resolved.json`
- Create: `capabilities-v3/agent.json`
- Create: `capabilities-v3/modules/*.json`
- Create: `capabilities-v3/intents/*.json`
- Create: `capabilities-v3/tools/.gitkeep`
- Create: `capabilities-v3/scopes/*.json`
- Create: `capabilities-v3/chains/critical/*.json`
- Create: `capabilities-v3/chains/end_to_end/*.json`
- Create: `capabilities-v3/evidence/*.json`
- Create: `capabilities-v3/boundaries/*.json`
- Create: `capabilities-v3/schemas/*.schema.json`
- Create: `docs/CAPABILITY_SNAPSHOT_V3.md`
- Modify: `README.md`
- Test: `tests/test_public_api.py`

**Interfaces:**
- Consumes: v3 build/export/validation/resolution and the default registries.
- Produces CLI commands `python -m minimal_agent.capabilities.v3.cli export|validate|resolve|diff` with JSON stdout and structured JSON errors on stderr.
- Produces: `BundleDiffV3(added_ids, removed_ids, changed_ids, affected_selection_roots)`.
- Produces: `diff_capability_bundles_v3(old_root: str | Path, new_root: str | Path) -> BundleDiffV3`.
- Produces: a checked-in default v3 bundle and stable Builder contract fixtures.

- [ ] **Step 1: Write failing CLI, diff, and Builder contract tests**

Cover:

- v2 CLI still selects only v2 and emits its existing output;
- v3 export/validate operate only on v3 roots and report all per-type counts;
- v3 validate rejects `capabilities/`, and v2 validate rejects `capabilities-v3/`;
- resolve accepts selection JSON and emits `ResolvedCapabilityGraphV3`;
- diff reports added/removed/changed IDs and walks reverse indexes only in memory to list affected Scope/Chain/Intent selections;
- checked-in `capabilities-v3/` equals a fresh default export;
- Builder fixture selects understanding + QueryUser with no Tool, recursively closes references, and exactly matches the checked-in resolved JSON;
- no Source Pack fixture contains coverage counts, expected answers, scoring, Judge rules, or fixture user data;
- `minimal_agent.__all__` remains exactly the existing 13 names.

- [ ] **Step 2: Run tests to verify RED**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_cli.py tests/test_capability_v3_diff.py tests/test_capability_v3_builder_contract.py tests/test_public_api.py -q`

Expected: FAIL because CLI, diffing, checked-in v3 bundle, docs, and fixtures do not exist.

- [ ] **Step 3: Implement CLI and diff API**

Use the root `snapshot_format_version` to reject the wrong parser explicitly. Diff compares validated artifact IDs and snapshot hashes, then derives affected roots from an in-memory reverse index; it never mutates snapshots.

- [ ] **Step 4: Export and check in the default v3 bundle and Builder fixtures**

Run the v3 exporter with `build_default_intent_registry()` and an empty `ToolRegistry()`. Generate the selection/resolution fixture from public v3 models and resolver; do not hand-author resolved capability facts.

- [ ] **Step 5: Document consumption and migration**

Document artifact responsibilities, DAG direction, three-state resolution, v2/v3 isolation, default/configured export examples, QueryUser adapter construction, Suite selection shape, Source Pack closure, Hash binding, and the prohibition on Builder inference.

- [ ] **Step 6: Run complete verification**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m ruff check .
PYTHONPATH=src .venv/bin/python -m minimal_agent.capabilities.cli validate --input capabilities
PYTHONPATH=src .venv/bin/python -m minimal_agent.capabilities.v3.cli validate --input capabilities-v3
PYTHONPATH=src .venv/bin/python - <<'PY'
import minimal_agent
assert len(minimal_agent.__all__) == 13
PY
```

Expected: all offline tests and Ruff PASS; only the documented paid OpenAI smoke may skip; both bundles validate with their own parser; v2 remains 1 Agent, 7 Modules, 7 Intents, and 0 Tools.

- [ ] **Step 7: Commit**

```bash
git add src/minimal_agent/capabilities/v3/cli.py src/minimal_agent/capabilities/v3/diffing.py tests/test_capability_v3_cli.py tests/test_capability_v3_diff.py tests/test_capability_v3_builder_contract.py tests/fixtures/capability_v3 capabilities-v3 docs/CAPABILITY_SNAPSHOT_V3.md README.md tests/test_public_api.py
git commit -m "feat: publish capability snapshot protocol v3"
```
