# Portable Capability Snapshot Kit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace MiniAgent-specific v3 snapshot catalogs with a reusable Capability Snapshot Kit that compiles portable Markdown/YAML Capability Specs plus Agent Adapter facts into the same Builder-compatible v3 Bundle.

**Architecture:** Add an import-independent `capability_snapshot_kit` package containing protocol models, Spec loading, compilation, validation, resolution, diff, and export. Keep portable evaluation requirements in versioned Markdown files with safe YAML Front Matter, and expose MiniAgent runtime facts through a thin adapter. Preserve every current `minimal_agent.capabilities.v3` entry point as a compatibility wrapper until semantic parity is proven and the old catalogs can be deleted.

**Tech Stack:** Python 3.11+, Pydantic 2, PyYAML safe loading, pytest, Ruff, setuptools

**Spec:** `docs/superpowers/specs/2026-10-08-portable-capability-snapshot-kit-design.md`

## Global Constraints

- `capability_snapshot_kit` must not import any module under `minimal_agent`.
- Capability Protocol remains `snapshot_format_version: "3.0"` with Agent, Module, Intent, Tool, Scope, Chain, Evidence, and Boundary artifacts.
- Existing v3 snapshot IDs, reference directions, artifact paths, CLI commands, and Python APIs remain compatible.
- `capabilities/` remains the frozen v2 Bundle and must not be modified.
- Spec Front Matter is machine-readable; Markdown prose is normative for humans but is never interpreted by a model during compilation.
- Spec requirements never prove support; only Adapter facts plus available Evidence can produce `supported`.
- Missing or unverifiable capability facts resolve to `unknown`; explicit `unsupported` takes precedence.
- Default MiniAgent export has zero Tool snapshots; `tool.query_user_info` appears only when its evaluation definition is explicitly registered.
- Generated `capabilities-v3/*.json` files are read-only build artifacts, not editing sources.
- Initial generator replacement requires an empty semantic diff for both default and QueryUser evaluation configurations; factual corrections must be separate changes.

## Review Focus

- A YAML object-construction tag or malformed Front Matter must fail safely without constructing Python objects; pinned in Task 2.
- A Spec module role that is missing or maps to multiple Module Facts must stop compilation with a deterministic diagnostic; pinned in Task 4.
- A `supported` Adapter claim whose Evidence is absent or unavailable must never survive as `supported`; pinned in Task 4.
- A non-MiniAgent adapter must be able to emit an Agent snapshot without importing `minimal_agent`; pinned in Tasks 1 and 4.
- A failed staged validation or filesystem replacement must preserve the previously exported Bundle byte-for-byte; pinned in Task 5.

---

## File Structure

### New generic package

- `src/capability_snapshot_kit/__init__.py` — stable generic exports.
- `src/capability_snapshot_kit/base.py` — strict Pydantic base model independent of MiniAgent.
- `src/capability_snapshot_kit/hashing.py` — canonical JSON and SHA-256 helpers.
- `src/capability_snapshot_kit/versions.py` — protocol constants only.
- `src/capability_snapshot_kit/models.py` — portable v3 snapshot models and schemas.
- `src/capability_snapshot_kit/bundle.py` — `CapabilityBundleV3`, references, paths, schema artifacts.
- `src/capability_snapshot_kit/spec_models.py` — strict Front Matter models using logical module roles and runtime binding keys.
- `src/capability_snapshot_kit/spec_loader.py` — safe Markdown/YAML loading and cross-Spec validation.
- `src/capability_snapshot_kit/facts.py` — Agent, Module, Intent, Tool, and Evidence Fact models.
- `src/capability_snapshot_kit/adapter.py` — `CapabilityAdapterV3` protocol.
- `src/capability_snapshot_kit/compiler.py` — bind Specs to Facts and build an in-memory Bundle.
- `src/capability_snapshot_kit/exporting.py` — deterministic serialization and atomic replacement.
- `src/capability_snapshot_kit/validation.py` — standalone v3 Bundle validation and loading.
- `src/capability_snapshot_kit/resolution.py` — three-state selection resolution.
- `src/capability_snapshot_kit/diffing.py` — directional Bundle diff and reverse impact index.
- `src/capability_snapshot_kit/cli.py` — generic CLI accepting an adapter factory and Spec root.

### New portable Specs

- `capability_specs/protocol.md`
- `capability_specs/scopes/{understanding,context,planning_execution,safety_recovery,result}.md`
- `capability_specs/chains/critical/{understanding_to_planning,planning_to_result}.md`
- `capability_specs/chains/end_to_end/end_to_end.md`
- `capability_specs/evidence/{intent_result,context_state,tool_trace,safety_recovery_event,final_response}.md`
- `capability_specs/boundaries/{understanding,context,planning_execution,safety_recovery,result,critical_chain,end_to_end}.md`

### MiniAgent integration

- `src/minimal_agent/capability_adapter.py` — adapter facade and Agent metadata.
- `src/minimal_agent/capability_facts/__init__.py` — fact builder exports.
- `src/minimal_agent/capability_facts/modules.py` — seven module facts and capability claims.
- `src/minimal_agent/capability_facts/intents.py` — IntentRegistry to Intent Facts.
- `src/minimal_agent/capability_facts/tools.py` — ToolRegistry/ToolContract to Tool Facts.
- `src/minimal_agent/capability_facts/evidence.py` — runtime observation interfaces to Evidence Facts.

### Compatibility and tests

- Existing `src/minimal_agent/capabilities/v3/*.py` files become thin re-export or delegation wrappers.
- Delete `src/minimal_agent/capabilities/v3/runtime_catalog.py` and `topology_catalog.py` only in the final switch task.
- Add focused tests under `tests/capability_snapshot_kit/` and retain all current `tests/test_capability_v3_*.py` compatibility tests.

---

### Task 1: Establish the import-independent v3 protocol core

**Files:**
- Create: `src/capability_snapshot_kit/__init__.py`
- Create: `src/capability_snapshot_kit/base.py`
- Create: `src/capability_snapshot_kit/hashing.py`
- Create: `src/capability_snapshot_kit/versions.py`
- Create: `src/capability_snapshot_kit/models.py`
- Create: `src/capability_snapshot_kit/bundle.py`
- Test: `tests/capability_snapshot_kit/test_protocol_core.py`

**Interfaces:**
- Consumes: Pydantic only.
- Produces: `SnapshotV3`, all eight snapshot models, `CapabilityBundleV3`, `reference_for_snapshot_v3(snapshot)`, `schema_artifacts_v3()`, `calculate_capability_bundle_sha256_v3(references)`, and protocol constants.

- [ ] **Step 1: Write failing protocol portability tests**

Add tests named:

```python
def test_generic_agent_snapshot_accepts_non_minimal_agent_id(): ...
def test_snapshot_models_and_hashes_are_deterministic(): ...
def test_generic_package_has_no_minimal_agent_imports(): ...
def test_reference_paths_preserve_current_v3_layout(): ...
```

The first test must validate `snapshot_id="agent.example_agent"` with `agent_id="example_agent"`. The import-boundary test must AST-scan every Python file under `src/capability_snapshot_kit` and reject `Import` or `ImportFrom` names beginning with `minimal_agent`.

- [ ] **Step 2: Run the tests and verify they fail because the package does not exist**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/capability_snapshot_kit/test_protocol_core.py -q`

Expected: FAIL during import of `capability_snapshot_kit`.

- [ ] **Step 3: Implement the generic protocol core**

Move the structural behavior from the existing v3 models, hashing, versions, and Bundle dataclass into the new package. Define `AgentSnapshotV3.snapshot_id` as a typed `agent.*` ID and require `agent_id` to equal its local ID; do not retain the current `Literal["agent.mini_agent"]`. Keep child artifact path rules byte-compatible for the current IDs, including `chains/critical/*.json` and `chains/end_to_end/end_to_end.json`.

- [ ] **Step 4: Run the focused tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/capability_snapshot_kit/test_protocol_core.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/capability_snapshot_kit tests/capability_snapshot_kit/test_protocol_core.py
git commit -m "feat: add portable capability protocol core"
```

### Task 2: Add safe, portable Capability Specs

**Files:**
- Modify: `pyproject.toml`
- Create: `src/capability_snapshot_kit/spec_models.py`
- Create: `src/capability_snapshot_kit/spec_loader.py`
- Create: all files under `capability_specs/` listed in File Structure
- Test: `tests/capability_snapshot_kit/test_spec_loader.py`

**Interfaces:**
- Consumes: YAML Front Matter and Markdown files under an explicit Spec root.
- Produces: `CapabilitySpecPackV3` and `load_capability_spec_pack_v3(spec_root: str | Path) -> CapabilitySpecPackV3`.

- [ ] **Step 1: Write failing Spec loader tests**

Add assertions for:

```python
def test_checked_in_spec_pack_loads_expected_ids_and_counts(): ...
def test_yaml_python_object_tag_is_rejected_without_execution(): ...
def test_duplicate_spec_id_is_rejected(): ...
def test_broken_evidence_or_boundary_reference_is_rejected(): ...
def test_markdown_body_is_required_but_never_compiled_as_fields(): ...
```

The checked-in pack must contain exactly 5 Scope, 3 Chain, 5 Evidence, and 7 Boundary specs with IDs matching the current v3 Bundle.

- [ ] **Step 2: Run the tests and verify loader imports fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/capability_snapshot_kit/test_spec_loader.py -q`

Expected: FAIL because `spec_loader` and the Spec files do not exist.

- [ ] **Step 3: Add the safe YAML dependency and strict Spec models**

Add `PyYAML>=6.0,<7` to project dependencies. Model providers using logical roles rather than MiniAgent IDs:

```python
class SpecProviderV3(StrictCapabilityModelV3):
    role: Literal["selected_intent", "selected_tool", "module_role"]
    module_role: str | None

class CapabilitySpecPackV3(StrictCapabilityModelV3):
    protocol: ProtocolSpecV3
    scopes: dict[str, ScopeSpecV3]
    chains: dict[str, ChainSpecV3]
    evidence: dict[str, EvidenceSpecV3]
    boundaries: dict[str, BoundarySpecV3]
```

Scope, Chain, Evidence, and Boundary specs must use `module_roles` and explicit runtime binding keys instead of concrete `module.*` IDs or `MinimalAgent.*` names. The seven initial roles are `orchestration`, `model_gateway`, `intent_routing`, `tool_loop`, `tool_registry`, `execution_guard`, and `observability`.

- [ ] **Step 4: Implement safe Front Matter loading and cross-reference validation**

Use `yaml.safe_load` only. Reject missing delimiters, non-mapping Front Matter, empty Markdown bodies, duplicate IDs, unknown Evidence/Boundary IDs, and invalid provider roles. Never evaluate tags or import paths found in YAML.

- [ ] **Step 5: Migrate the current topology into portable Specs**

Translate every definition from `topology_catalog.py` one-to-one into the listed Markdown files. Preserve current descriptions, inputs, outputs, requirements, branches, completion conditions, terminal states, and evidence semantics. Put the five Agent summary groups currently in `_AGENT_REQUIREMENTS` into `protocol.md` Front Matter as `agent_capability_groups`.

- [ ] **Step 6: Run the focused tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/capability_snapshot_kit/test_spec_loader.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml capability_specs src/capability_snapshot_kit/spec_models.py src/capability_snapshot_kit/spec_loader.py tests/capability_snapshot_kit/test_spec_loader.py
git commit -m "feat: add portable capability specifications"
```

### Task 3: Define Agent Facts and the Adapter protocol

**Files:**
- Create: `src/capability_snapshot_kit/facts.py`
- Create: `src/capability_snapshot_kit/adapter.py`
- Create: `tests/support/capability_adapter.py`
- Test: `tests/capability_snapshot_kit/test_adapter_contract.py`

**Interfaces:**
- Consumes: Agent-owned runtime metadata represented as strict Fact models.
- Produces: `CapabilityAdapterV3`, `AgentFactsV3`, `ModuleFactV3`, `IntentFactV3`, `ToolFactV3`, and `EvidenceFactV3`.

- [ ] **Step 1: Write failing Adapter contract tests**

Add tests named:

```python
def test_fake_adapter_is_structurally_independent_of_minimal_agent(): ...
def test_fact_ids_roles_and_claims_are_strict(): ...
def test_adapter_cannot_report_registered_false_tool_fact(): ...
def test_duplicate_module_roles_are_retained_for_compiler_diagnostics(): ...
```

The Fake Adapter must describe `agent.example_agent`, one module, one intent, zero tools, and the Evidence facts needed by a minimal understanding Scope.

- [ ] **Step 2: Run the tests and verify Fact imports fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/capability_snapshot_kit/test_adapter_contract.py -q`

Expected: FAIL during import.

- [ ] **Step 3: Implement strict Fact models**

Define exact adapter methods:

```python
class CapabilityAdapterV3(Protocol):
    def agent_facts(self) -> AgentFactsV3: ...
    def module_facts(self) -> tuple[ModuleFactV3, ...]: ...
    def intent_facts(self) -> tuple[IntentFactV3, ...]: ...
    def tool_facts(self) -> tuple[ToolFactV3, ...]: ...
    def evidence_facts(self) -> tuple[EvidenceFactV3, ...]: ...
```

`AgentFactsV3` owns agent identity, entrypoints, runtime binding values, schemas, versions, and contract version. `ModuleFactV3` owns module identity, one or more logical roles, responsibility, claims, trace events, and child Intent/Tool IDs. Intent and Tool facts own the current snapshot fields except hashes and references. Evidence facts own actual producers, timing, payload schema, observation interface, events, result paths, and availability.

- [ ] **Step 4: Implement the Fake Adapter and run tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/capability_snapshot_kit/test_adapter_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/capability_snapshot_kit/facts.py src/capability_snapshot_kit/adapter.py tests/support/capability_adapter.py tests/capability_snapshot_kit/test_adapter_contract.py
git commit -m "feat: define capability adapter facts"
```

### Task 4: Compile Specs and Facts into an in-memory v3 Bundle

**Files:**
- Create: `src/capability_snapshot_kit/compiler.py`
- Test: `tests/capability_snapshot_kit/test_compiler.py`

**Interfaces:**
- Consumes: `CapabilitySpecPackV3` and `CapabilityAdapterV3` from Tasks 2 and 3.
- Produces: `compile_capability_bundle_v3(specs: CapabilitySpecPackV3, adapter: CapabilityAdapterV3) -> CapabilityBundleV3` and `compile_capability_snapshot_v3(snapshot_id: str, specs: CapabilitySpecPackV3, adapter: CapabilityAdapterV3) -> SnapshotV3`.

- [ ] **Step 1: Write failing compiler tests**

Add tests named:

```python
def test_fake_adapter_compiles_a_valid_non_minimal_agent_bundle(): ...
def test_compilation_is_deterministic(): ...
def test_missing_or_ambiguous_module_role_fails_with_role_name(): ...
def test_supported_claim_with_missing_evidence_is_rejected(): ...
def test_missing_fact_is_not_synthesized_as_supported(): ...
```

The first test must assert the output root ID is `agent.example_agent`, all references close over existing snapshots, and no serialized value contains `mini_agent`.

- [ ] **Step 2: Run the tests and verify compiler imports fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/capability_snapshot_kit/test_compiler.py -q`

Expected: FAIL during import.

- [ ] **Step 3: Implement role and runtime-binding resolution**

Build indexes for Fact IDs and module roles. A singular provider role must resolve to exactly one Module Fact. Lists of allowed module roles may resolve to multiple distinct modules. Missing binding keys, missing roles, duplicate singular roles, and references to absent Evidence must raise `CapabilityCompilationErrorV3` with sorted diagnostics.

- [ ] **Step 4: Implement deterministic artifact construction**

Construct Tool and Intent snapshots first, then Module and Evidence snapshots, followed by Boundary, Scope, Chain, and Agent. Convert `module_role` providers to concrete `snapshot` providers in output. Match Intent `required_tool_name` only to explicitly supplied Tool Facts. Calculate source, snapshot, and Bundle hashes with sorted canonical JSON.

- [ ] **Step 5: Enforce truthful support and aggregate Agent capabilities**

Reject a `supported` claim if its Evidence Fact is absent or explicitly unavailable. Aggregate Agent claims from the `protocol.md` capability groups with precedence `unsupported`, then `unknown`, then `supported`; never infer a missing child as supported.

- [ ] **Step 6: Run compiler and protocol tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/capability_snapshot_kit/test_compiler.py tests/capability_snapshot_kit/test_protocol_core.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/capability_snapshot_kit/compiler.py tests/capability_snapshot_kit/test_compiler.py
git commit -m "feat: compile capability specs and agent facts"
```

### Task 5: Port validation and atomic export into the Kit

**Files:**
- Create: `src/capability_snapshot_kit/validation.py`
- Create: `src/capability_snapshot_kit/exporting.py`
- Test: `tests/capability_snapshot_kit/test_validation.py`
- Test: `tests/capability_snapshot_kit/test_exporting.py`

**Interfaces:**
- Consumes: generic Bundle/models/compiler from Tasks 1 and 4.
- Produces: `validate_capability_bundle_v3`, `load_capability_bundle_v3`, `collect_snapshot_references_v3`, `_write_capability_bundle_v3`, and `export_capability_bundle_v3(output_root, specs, adapter)`.

- [ ] **Step 1: Write failing generic validation tests**

Port the existing hash, path traversal, broken reference, cycle, unsupported Evidence, wrong Schema, and unexpected JSON tests. Add a non-MiniAgent root test and replace the fixed `MODULE_IDS_V3` expectation with the Agent root's exact Module reference set.

- [ ] **Step 2: Write failing atomic export rollback tests**

Add:

```python
def test_two_exports_are_byte_identical(): ...
def test_empty_tool_export_keeps_tools_directory(): ...
def test_validation_failure_preserves_existing_output_byte_for_byte(): ...
def test_replace_failure_restores_backup_byte_for_byte(monkeypatch): ...
```

- [ ] **Step 3: Run the tests and verify modules are missing**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/capability_snapshot_kit/test_validation.py tests/capability_snapshot_kit/test_exporting.py -q`

Expected: FAIL during import.

- [ ] **Step 4: Port and generalize validation**

Remove checks for `agent.mini_agent` and the fixed seven-module set. Validate that every child is rooted exactly once through the actual Agent references, supported claims use present and supported Evidence, module/boundary/spec references exist, hashes match, paths stay below the Bundle root, and schemas match the generic models.

- [ ] **Step 5: Implement deterministic writing and atomic replacement**

Write to a sibling temporary directory, validate the staged Bundle, replace the existing root through a unique backup, restore the backup on replacement failure, and remove the backup only after success. Preserve the empty `tools/.gitkeep` behavior.

- [ ] **Step 6: Run validation and export tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/capability_snapshot_kit/test_validation.py tests/capability_snapshot_kit/test_exporting.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/capability_snapshot_kit/validation.py src/capability_snapshot_kit/exporting.py tests/capability_snapshot_kit/test_validation.py tests/capability_snapshot_kit/test_exporting.py
git commit -m "feat: validate and export portable capability bundles"
```

### Task 6: Port resolution, diff, and the generic CLI

**Files:**
- Create: `src/capability_snapshot_kit/resolution.py`
- Create: `src/capability_snapshot_kit/diffing.py`
- Create: `src/capability_snapshot_kit/cli.py`
- Modify: `src/capability_snapshot_kit/__init__.py`
- Test: `tests/capability_snapshot_kit/test_resolution.py`
- Test: `tests/capability_snapshot_kit/test_diffing.py`
- Test: `tests/capability_snapshot_kit/test_cli.py`

**Interfaces:**
- Consumes: validated generic Bundles.
- Produces: current `CapabilitySelectionV3`, `ResolvedCapabilityGraphV3`, `BundleDiffV3`, resolver and diff functions; generic CLI command dispatch callable as `main(argv, *, adapter_factory, default_spec_root)`.

- [ ] **Step 1: Write failing resolver and diff tests**

Port all existing resolution status, mismatched Tool, optional requirement, recursive closure, changed-ID, removed-ID, and reverse-impact assertions to the Fake Adapter Bundle.

Add CLI tests asserting that all four commands emit machine-readable JSON, `export --spec-root` uses the supplied Spec Pack, invalid input returns code 1, and export receives its Agent through the injected adapter factory rather than importing MiniAgent.

- [ ] **Step 2: Run the tests and verify modules are missing**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/capability_snapshot_kit/test_resolution.py tests/capability_snapshot_kit/test_diffing.py tests/capability_snapshot_kit/test_cli.py -q`

Expected: FAIL during import.

- [ ] **Step 3: Port resolution and diff without Agent-specific assumptions**

Keep three-state precedence and selection rules unchanged. Build reverse indexes only in memory. Do not write reverse relationships into Tool or other snapshots.

- [ ] **Step 4: Add generic CLI dispatch**

Support `export`, `validate`, `resolve`, and `diff`. `export` accepts `--spec-root`; other commands operate only on the immutable Bundle they receive. Keep machine-readable JSON success and error output.

- [ ] **Step 5: Run focused tests and export the generic public surface**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/capability_snapshot_kit/test_resolution.py tests/capability_snapshot_kit/test_diffing.py tests/capability_snapshot_kit/test_cli.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/capability_snapshot_kit tests/capability_snapshot_kit/test_resolution.py tests/capability_snapshot_kit/test_diffing.py tests/capability_snapshot_kit/test_cli.py
git commit -m "feat: resolve and diff portable capability bundles"
```

### Task 7: Implement the MiniAgent Adapter and prove generator parity

**Files:**
- Create: `src/minimal_agent/capability_adapter.py`
- Create: `src/minimal_agent/capability_facts/__init__.py`
- Create: `src/minimal_agent/capability_facts/modules.py`
- Create: `src/minimal_agent/capability_facts/intents.py`
- Create: `src/minimal_agent/capability_facts/tools.py`
- Create: `src/minimal_agent/capability_facts/evidence.py`
- Test: `tests/test_minimal_agent_capability_adapter.py`
- Test: `tests/test_capability_v3_generator_parity.py`

**Interfaces:**
- Consumes: `IntentRegistry`, `ToolRegistry`, ToolContract, AgentResult/IntentResult/ToolCallRecord schemas, runtime versions, and Kit Fact models.
- Produces: `MiniAgentCapabilityAdapter(intent_registry: IntentRegistry, tool_registry: ToolRegistry)` implementing all `CapabilityAdapterV3` methods.

- [ ] **Step 1: Write failing MiniAgent Adapter truth tests**

Assert exact seven module IDs and roles, seven default Intent Facts, zero default Tool Facts, actual Evidence availability, and no fixture data in serialized Facts. Add a configured registry assertion that only `tool.query_user_info` and the matching Intent Tool binding appear.

- [ ] **Step 2: Run the Adapter test and verify the class is missing**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_minimal_agent_capability_adapter.py -q`

Expected: FAIL during import.

- [ ] **Step 3: Implement dynamic Tool and Intent Fact builders**

Move behavior from `build_tool_snapshots_v3` and `build_intent_snapshots_v3` into Fact construction without creating snapshots or references. Tool facts must derive rate-limit support, permissions, risk, confirmation, side effects, idempotency, simulation profile, and observation interfaces from the registered ToolContract.

- [ ] **Step 4: Implement Module, Evidence, and Agent Fact builders**

Move only MiniAgent-specific runtime facts from the old catalogs. Split them by responsibility across the listed files. Bind logical Spec roles and runtime keys to current module IDs, entrypoints, event names, schemas, and version constants. Keep unsupported Context facts explicit.

- [ ] **Step 5: Write default and QueryUser dual-generator parity tests**

For each configuration, build one Bundle with the old Catalog path and one with `compile_capability_bundle_v3(load_capability_spec_pack_v3(...), MiniAgentCapabilityAdapter(...))`. Assert:

```python
assert semantic_snapshot_payloads(new) == semantic_snapshot_payloads(old)
assert resolve_matrix(new) == resolve_matrix(old)
```

Exclude only schema relaxation needed to allow non-MiniAgent Agent IDs; do not exclude snapshot fields, status, references, source hashes, or Bundle hashes.

- [ ] **Step 6: Run Adapter and parity tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_minimal_agent_capability_adapter.py tests/test_capability_v3_generator_parity.py -q`

Expected: PASS for both default and QueryUser evaluation configurations.

- [ ] **Step 7: Commit**

```bash
git add src/minimal_agent/capability_adapter.py src/minimal_agent/capability_facts tests/test_minimal_agent_capability_adapter.py tests/test_capability_v3_generator_parity.py
git commit -m "feat: adapt mini agent capabilities to portable compiler"
```

### Task 8: Switch compatibility APIs, remove old catalogs, and publish the new Bundle

**Files:**
- Modify: `src/minimal_agent/capabilities/v3/__init__.py`
- Modify: `src/minimal_agent/capabilities/v3/bundle.py`
- Modify: `src/minimal_agent/capabilities/v3/cli.py`
- Modify: `src/minimal_agent/capabilities/v3/models.py`
- Modify: `src/minimal_agent/capabilities/v3/validation.py`
- Modify: `src/minimal_agent/capabilities/v3/resolution.py`
- Modify: `src/minimal_agent/capabilities/v3/diffing.py`
- Modify: `src/minimal_agent/capabilities/v3/versions.py`
- Delete: `src/minimal_agent/capabilities/v3/runtime_catalog.py`
- Delete: `src/minimal_agent/capabilities/v3/topology_catalog.py`
- Regenerate: `capabilities-v3/**`
- Modify: `README.md`
- Modify: `docs/CAPABILITY_SNAPSHOT_V3.md`
- Modify: relevant existing `tests/test_capability_v3_*.py`

**Interfaces:**
- Consumes: Kit APIs and `MiniAgentCapabilityAdapter`.
- Produces: unchanged MiniAgent-facing v3 imports and CLI behavior backed entirely by the portable Kit.

- [ ] **Step 1: Add failing compatibility assertions before switching**

Extend existing tests to assert that every name in `minimal_agent.capabilities.v3.__all__` resolves to the corresponding Kit implementation, the root `minimal_agent.__all__` remains exactly 13 names, CLI export accepts an optional `--spec-root`, and v2 rejects v3 exactly as before.

- [ ] **Step 2: Run compatibility tests and verify they fail against old implementations**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_cli.py tests/test_public_api.py tests/test_capability_v2_compatibility.py -q`

Expected: FAIL only on new Kit-delegation assertions.

- [ ] **Step 3: Replace v3 modules with thin compatibility wrappers**

Keep existing MiniAgent signatures:

```python
build_capability_bundle_v3(intent_registry, tool_registry)
build_capability_snapshot_v3(snapshot_id, intent_registry, tool_registry)
export_capability_bundle_v3(output_root, intent_registry, tool_registry)
```

Each wrapper loads the default `capability_specs/` root, constructs `MiniAgentCapabilityAdapter`, and delegates to the Kit. Re-export models, validation, resolution, diff, and constants without duplicating implementation. Delegate the existing CLI parser to the generic command handlers while preserving module name and JSON output.

- [ ] **Step 4: Delete old catalogs only after wrappers pass parity tests**

Remove `runtime_catalog.py` and `topology_catalog.py`, update all imports, and run `rg "runtime_catalog|topology_catalog" src tests` expecting no production references and no parity-test dependency after the final parity assertion has been captured.

- [ ] **Step 5: Regenerate and validate the checked-in v3 Bundle**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m minimal_agent.capabilities.v3.cli export --output capabilities-v3
PYTHONPATH=src .venv/bin/python -m minimal_agent.capabilities.v3.cli validate --input capabilities-v3
```

Expected counts: 1 Agent, 7 Module, 7 Intent, 0 Tool, 5 Scope, 3 Chain, 5 Evidence, and 7 Boundary. The v2 `capabilities/` bytes must remain unchanged.

- [ ] **Step 6: Update documentation**

Document the portable Spec/Adapter/Compiler flow, `--spec-root`, generated-artifact rule, MiniAgent Adapter, other-Agent integration steps, and the fact that natural-language prose is never dynamically interpreted.

- [ ] **Step 7: Run Builder and QueryUser end-to-end contract tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_capability_v3_builder_contract.py tests/test_capability_v3_query_user_bundle.py tests/test_query_user_evaluation_adapter.py -q`

Expected: PASS, including understanding supported, planning/execution supported with the selected registered Tool, Context unsupported, and no fixture data in snapshots.

- [ ] **Step 8: Run the full verification suite**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m ruff check .
git diff --check
```

Expected: all tests pass except the existing opt-in paid OpenAI smoke skip; Ruff and diff checks pass.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml capability_specs capabilities-v3 README.md docs/CAPABILITY_SNAPSHOT_V3.md src/capability_snapshot_kit src/minimal_agent/capabilities/v3 src/minimal_agent/capability_adapter.py src/minimal_agent/capability_facts tests/capability_snapshot_kit tests/test_minimal_agent_capability_adapter.py tests/test_capability_v3_generator_parity.py tests/test_capability_v3_cli.py tests/test_public_api.py tests/test_capability_v2_compatibility.py tests/test_capability_v3_builder_contract.py tests/test_capability_v3_query_user_bundle.py tests/test_query_user_evaluation_adapter.py
git commit -m "refactor: use portable capability snapshot kit"
```

---

## Final Acceptance Checklist

- [ ] `capability_snapshot_kit` has no `minimal_agent` imports.
- [ ] Fake Adapter exports a valid non-MiniAgent Bundle.
- [ ] Default MiniAgent Bundle has the current 35 non-Schema artifacts and zero Tools.
- [ ] QueryUser evaluation Bundle contains exactly `tool.query_user_info` and no fixture data.
- [ ] Scope/Chain resolution statuses match the current implementation.
- [ ] Existing Builder selection fixtures still resolve.
- [ ] Old Catalog modules are deleted and no longer referenced.
- [ ] Current MiniAgent v3 API and CLI remain compatible.
- [ ] v2 Bundle and root public API remain unchanged.
- [ ] Full tests, Ruff, Bundle validation, and diff checks pass.
