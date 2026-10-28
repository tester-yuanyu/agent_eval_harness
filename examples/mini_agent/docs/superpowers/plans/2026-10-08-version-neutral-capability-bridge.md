# Version-Neutral Capability Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `capabilities/agent.json` and unversioned Python/CLI names the only advertised Agent-to-Builder/Evaluator bridge while preserving wire format `3.0` and every generated snapshot byte.

**Architecture:** Add unversioned public aliases over the retained concrete implementation, then rename the immutable Bundle root without changing files below it. Consumer documentation and contract tests use only the canonical unversioned boundary; versioned modules remain internal compatibility symbols.

**Tech Stack:** Python 3.11, Pydantic v2, PyYAML, pytest, Ruff, Capability Snapshot Kit

**Spec:** `docs/superpowers/specs/2026-10-08-version-neutral-capability-bridge-design.md`

## Global Constraints

- Keep `snapshot_format_version: "3.0"` in every wire artifact.
- Keep all current snapshot, reference, and Bundle hashes unchanged.
- The only checked-in Bundle root after migration is `capabilities/`.
- Do not retain `capabilities-v3/` as a duplicate, symlink, fallback, or auto-detected path.
- Builder consumes the directory and must not import `minimal_agent`, invoke its CLI, or read `capability_specs/`.
- Keep version-suffixed implementation symbols available for internal compatibility, but do not advertise them in active consumer documentation.
- Do not add dataset generation, fixtures, scoring, Judge, reports, model credentials, or Builder/Evaluator business logic.
- Preserve unrelated user-owned untracked files.

## Review Focus

- A non-`3.0` root passed through an unversioned API or CLI must fail closed rather than select a fallback.
- An unversioned Kit alias must be object-identical to its retained concrete symbol so models and exception handling do not fork.
- Moving the Bundle root must not rewrite relative references or change JSON bytes or hashes.
- A configured Tool Bundle must still bind the ToolRegistry used for runtime execution; the default checked-in Bundle remains zero-Tool.
- Active Builder/Evaluator examples must not reintroduce `.v3`, `V3`, or `capabilities-v3` as a routing choice.

---

### Task 1: Add the version-neutral Kit and MiniAgent public surface

**Files:**
- Create: `tests/capability_snapshot_kit/test_public_api.py`
- Modify: `src/capability_snapshot_kit/__init__.py`
- Modify: `src/minimal_agent/capabilities/__init__.py`
- Modify: `tests/test_public_api.py`

**Interfaces:**
- Consumes: concrete Kit symbols such as `CapabilityBundleV3`, `CapabilityAdapterV3`, `validate_capability_bundle_v3`, and `resolve_capability_graph_v3`.
- Produces: object-identical unversioned aliases including `CapabilityBundle`, `CapabilityAdapter`, `CapabilitySelection`, `Snapshot`, `validate_capability_bundle`, `load_capability_bundle`, `resolve_capability_graph`, `diff_capability_bundles`, `compile_capability_bundle`, and `export_capability_bundle`.

- [ ] **Step 1: Write failing Kit alias tests**

Create `tests/capability_snapshot_kit/test_public_api.py` with a table that asserts every stable unversioned alias is the same object as its concrete implementation symbol. Cover public models, Facts, Adapter, compilation, export, load, validation, resolution, diff, schemas, hashing, and the version constant. Assert all unversioned names are in `capability_snapshot_kit.__all__`.

- [ ] **Step 2: Tighten the MiniAgent facade test**

Update `tests/test_public_api.py` so consumer-facing assertions import `CapabilityBundle` and validation functions from unversioned packages. Keep one compatibility assertion proving retained versioned symbols resolve to the same objects.

- [ ] **Step 3: Run the public API tests and verify aliases are missing**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/capability_snapshot_kit/test_public_api.py \
  tests/test_public_api.py -q
```

Expected: FAIL because the Kit does not export the unversioned alias set.

- [ ] **Step 4: Add object-identical aliases in the Kit package root**

In `src/capability_snapshot_kit/__init__.py`, assign unversioned names directly to retained symbols. Do not subclass models, wrap exceptions, or add alternate implementations. Include both alias and compatibility names in `__all__`.

The alias set covers:

```text
SNAPSHOT_FORMAT_VERSION
AgentFacts, AgentSnapshot, BoundarySnapshot
BundleDiff, BundleValidationResult
CapabilityAdapter, CapabilityBundle
CapabilityBundleValidationError, CapabilityCompilationError
CapabilityClaim, CapabilityProvider, CapabilityRequirement, CapabilitySelection
CapabilitySpecLoadError, CapabilitySpecPack
ChainNode, ChainSnapshot, EvidenceFact, EvidenceSnapshot
IntentFact, IntentSnapshot, ModuleFact, ModuleSnapshot, ScopeSnapshot
ResolvedCapabilityGraph, ResolvedRequirement
Snapshot, SnapshotReference, SnapshotType, SupportStatus
ToolFact, ToolSnapshot
calculate_capability_bundle_sha256
compile_capability_bundle, compile_capability_snapshot
collect_snapshot_references, diff_capability_bundles
export_capability_bundle, load_capability_bundle, load_capability_spec_pack
reference_for_snapshot, resolve_capability_graph
schema_artifacts, snapshot_schema, validate_capability_bundle
```

Existing already-unversioned hashing helpers remain unchanged.

- [ ] **Step 5: Make the MiniAgent facade consume unversioned Kit aliases**

Update `src/minimal_agent/capabilities/__init__.py` so stable model and validation names come from the unversioned Kit boundary, while registry-bound build/export functions continue to use the MiniAgent host wrapper. Preserve the root `minimal_agent.__all__` cardinality of 13.

- [ ] **Step 6: Run focused tests and Ruff**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/capability_snapshot_kit/test_public_api.py \
  tests/test_public_api.py \
  tests/test_capability_v3_cli.py -q
PYTHONPATH=src .venv/bin/python -m ruff check \
  src/capability_snapshot_kit/__init__.py \
  src/minimal_agent/capabilities/__init__.py \
  tests/capability_snapshot_kit/test_public_api.py \
  tests/test_public_api.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/capability_snapshot_kit/__init__.py \
  src/minimal_agent/capabilities/__init__.py \
  tests/capability_snapshot_kit/test_public_api.py \
  tests/test_public_api.py
git commit -m "refactor: add unversioned capability interfaces"
```

### Task 2: Make `capabilities/` the canonical immutable Bundle

**Files:**
- Rename: `capabilities-v3/` → `capabilities/`
- Modify: `tests/test_capability_v3_builder_contract.py`
- Modify: `tests/test_capability_v3_generator_parity.py`
- Modify: `tests/test_capability_v3_cli.py`
- Modify: `tests/test_capability_v3_export.py`

**Interfaces:**
- Consumes: unversioned export/validate/resolve interfaces from Task 1.
- Produces: checked-in Builder input rooted at `capabilities/agent.json`, with byte-identical artifacts and unchanged Bundle Hash.

- [ ] **Step 1: Write failing canonical-root assertions**

Change checked-in Bundle fixtures in Builder-contract and generator-parity tests to use `PROJECT_ROOT / "capabilities"`. Assert the canonical root exists and `PROJECT_ROOT / "capabilities-v3"` does not.

Update consumer-facing CLI test outputs to `capabilities` and invoke only `minimal_agent.capabilities.cli` for normal export, validate, resolve, and diff flows. Keep one compatibility test for the retained implementation module.

- [ ] **Step 2: Run focused tests and verify the canonical root is missing**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_capability_v3_builder_contract.py \
  tests/test_capability_v3_generator_parity.py \
  tests/test_capability_v3_cli.py \
  tests/test_capability_v3_export.py -q
```

Expected: FAIL because the checked-in Bundle still lives at `capabilities-v3/`.

- [ ] **Step 3: Rename the Bundle root without rewriting artifacts**

Move `capabilities-v3/` to `capabilities/` as a mechanical repository rename. Do not regenerate or edit files below the root.

- [ ] **Step 4: Update remaining test-local output directory names**

Replace consumer-facing temporary output names with `capabilities`. Internal tests may retain `v3` in test names and concrete imports where they intentionally exercise the implementation.

- [ ] **Step 5: Verify parity, hashes, CLI, and configured Tool behavior**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_capability_v3_builder_contract.py \
  tests/test_capability_v3_generator_parity.py \
  tests/test_capability_v3_cli.py \
  tests/test_capability_v3_export.py \
  tests/test_capability_v3_query_user_bundle.py \
  tests/test_query_user_evaluation_adapter.py -q
PYTHONPATH=src .venv/bin/python -m minimal_agent.capabilities.cli \
  validate --input capabilities
```

Expected: PASS with Bundle Hash `99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8`, format `3.0`, and zero Tool snapshots in the checked-in Bundle.

- [ ] **Step 6: Confirm the move changed paths only**

Compare every old Git blob at `HEAD:capabilities-v3/<relative-path>` with the corresponding working-tree file at `capabilities/<relative-path>` before committing the rename. Expected: every byte matches.

- [ ] **Step 7: Commit**

```bash
git add -A capabilities-v3 capabilities tests
git commit -m "refactor: make capabilities the canonical bundle"
```

### Task 3: Remove version routing from active bridge documentation

**Files:**
- Rename: `docs/CAPABILITY_SNAPSHOT_V3.md` → `docs/CAPABILITY_SNAPSHOT.md`
- Modify: `README.md`
- Modify: `docs/CAPABILITY_SNAPSHOT.md`
- Modify: `src/capability_snapshot_kit/__init__.py`
- Modify: `src/capability_snapshot_kit/cli.py`
- Modify: `src/minimal_agent/capabilities/__init__.py`

**Interfaces:**
- Consumes: canonical directory and unversioned names from Tasks 1–2.
- Produces: one active integration contract with no version selector in paths, Provider names, imports, or commands.

- [ ] **Step 1: Rename the active protocol guide**

Move `docs/CAPABILITY_SNAPSHOT_V3.md` to `docs/CAPABILITY_SNAPSHOT.md` and change its title to `Capability Snapshot Protocol`.

- [ ] **Step 2: Update active consumer documentation**

In `README.md` and the renamed guide:

- use `capabilities/agent.json` and the complete `capabilities/` tree;
- use `minimal_agent.capabilities` and its CLI in public examples;
- describe `snapshot_format_version: "3.0"` as wire data, not a Provider choice;
- include Agent, Scope, Chain, Module, Intent, optional Tool, Evidence, and Boundary in the Builder IR mapping;
- require an evaluator-owned handler and same-Registry Bundle for QueryUser execution;
- keep Builder/Evaluator logic and credentials outside MiniAgent.

- [ ] **Step 3: Make package descriptions version-neutral**

Update only public package, CLI, and facade docstrings. Do not rename internal modules, concrete symbols, test files, fixture directories, Spec IDs, or historical records.

- [ ] **Step 4: Scan active bridge material**

Run:

```bash
rg -n "capabilities-v3|CAPABILITY_SNAPSHOT_V3|minimal_agent\.capabilities\.v3|CapabilityAdapterV3" \
  README.md docs/CAPABILITY_SNAPSHOT.md
```

Expected: no matches. Format value `3.0` is expected and required.

- [ ] **Step 5: Run contract tests and Ruff**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/capability_snapshot_kit/test_public_api.py \
  tests/test_public_api.py \
  tests/test_capability_v3_builder_contract.py \
  tests/test_capability_v3_cli.py \
  tests/test_query_user_evaluation_adapter.py -q
PYTHONPATH=src .venv/bin/python -m ruff check .
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A README.md docs src/capability_snapshot_kit/__init__.py \
  src/capability_snapshot_kit/cli.py \
  src/minimal_agent/capabilities/__init__.py
git commit -m "docs: publish version-neutral capability bridge"
```

### Task 4: Verify the complete bridge boundary

**Files:**
- Modify only if verification exposes a requirement violation.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: evidence that Agent, Builder, and Evaluator bind the sole supported protocol without a version-labelled integration path.

- [ ] **Step 1: Exercise the unversioned bridge**

Export to a temporary `capabilities/` directory, validate it, resolve the QueryUser understanding selection, and diff it against the checked-in Bundle using `minimal_agent.capabilities.cli`. Expected: valid, resolved `supported`, and no added, removed, or changed IDs.

- [ ] **Step 2: Verify structural failures remain fail-closed**

Run the non-`3.0`, hash mismatch, dangling reference, cycle, and out-of-scope artifact validation tests. Expected: all invalid inputs are rejected.

- [ ] **Step 3: Verify repository and public boundaries**

Confirm that `capabilities/agent.json` and `docs/CAPABILITY_SNAPSHOT.md` exist; their old version-labelled paths do not; `minimal_agent.__all__` contains exactly 13 names; and the Bundle Hash is unchanged. Scan active consumer docs for version-labelled routes, excluding internal code, tests, fixtures, and historical records.

- [ ] **Step 4: Run full verification**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m ruff check .
git diff --check
```

Expected: all tests pass except the opt-in paid OpenAI smoke skip; Ruff and diff checks pass.

- [ ] **Step 5: Review the complete branch diff**

Confirm only the approved public aliases, generated-root rename, active docs, and tests changed. Confirm unrelated user-owned untracked files are untouched.

No commit is required if verification makes no changes. If verification exposes a defect, add a focused regression test and commit the minimal correction.

---

## Final Acceptance Checklist

- [ ] Builder receives `capabilities/agent.json` as the sole canonical root.
- [ ] Active Builder/Evaluator bridges do not require a `v3` Provider or path.
- [ ] Unversioned Kit and MiniAgent aliases are object-identical to the implementation.
- [ ] Wire format `3.0`, Schemas, snapshot hashes, and Bundle Hash are unchanged.
- [ ] Default Bundle still declares zero Tools.
- [ ] QueryUser evaluation adapter still requires an explicit evaluator-owned handler.
- [ ] Non-compatible wire formats fail closed.
- [ ] Full tests, Ruff, and diff checks pass.
