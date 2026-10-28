# V3-Only Capability Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Capability Snapshot Protocol v2 completely while preserving the existing unversioned Python API and CLI names as v3-only facades.

**Architecture:** `minimal_agent.capabilities` becomes a thin unversioned facade over `minimal_agent.capabilities.v3`; the portable Kit remains the only generator and validator implementation. Runtime version constants that are not capability-protocol-specific move to `minimal_agent.versions`, then all v2 artifacts, code, documentation, and tests are deleted.

**Tech Stack:** Python 3.11, Pydantic v2, PyYAML, pytest, Ruff, Capability Snapshot Protocol v3

**Spec:** `docs/superpowers/specs/2026-10-08-v3-only-capability-protocol-design.md`

## Global Constraints

- Preserve the 13 names in `minimal_agent.__all__`.
- Preserve unversioned `build_capability_bundle`, `export_capability_bundle`, and `validate_capability_bundle`, but map them to v3 behavior.
- Preserve both CLI module paths; both must execute the same v3-only implementation.
- Do not retain v2 parsing, migration, fallback, artifacts, or source modules.
- Capability Protocol structural failures reject input; only validated missing capability semantics may resolve to `unknown`.
- Keep `PyYAML` because the Agent-side v3 generator reads `capability_specs/`; Builder remains independent.
- Preserve unrelated user-owned untracked files.

## Review Focus

- A caller using the unversioned API must receive Kit v3 model instances, not merely JSON that resembles v3.
- Re-exported unversioned functions must retain the existing registry-based signatures.
- Both CLI paths must emit byte-identical v3 directories for the same configuration.
- A non-v3 root must fail closed through both CLI paths with machine-readable errors.
- Removing v2 modules must not remove runtime version values still embedded in current v3 snapshots.

---

### Task 1: Switch the unversioned Python and CLI facades to v3

**Files:**
- Modify: `tests/test_public_api.py`
- Modify: `tests/test_capability_v3_cli.py`
- Modify: `src/minimal_agent/capabilities/__init__.py`
- Modify: `src/minimal_agent/capabilities/cli.py`

**Interfaces:**
- Consumes: existing v3 wrappers in `minimal_agent.capabilities.v3`.
- Produces: unversioned registry-based functions `build_capability_bundle`, `build_capability_snapshot`, `export_capability_bundle`, and `validate_capability_bundle`; unversioned CLI `main(argv=None)`.

- [ ] **Step 1: Write failing public-facade tests**

Update `test_public_interfaces_run_and_export_empty_configuration` to assert:

```python
assert isinstance(bundle, capability_snapshot_kit.CapabilityBundleV3)
assert bundle.agent.snapshot_format_version == "3.0"
assert validate_capability_bundle(output).snapshot_counts == {
    "agent": 1,
    "module": 7,
    "intent": 7,
    "tool": 0,
    "scope": 5,
    "chain": 3,
    "evidence": 5,
    "boundary": 7,
}
```

Replace the v2-only CLI test with a test that exports through
`minimal_agent.capabilities.cli`, asserts the same v3 counts, and validates that output through both CLI paths. Add a byte-for-byte directory comparison between unversioned and explicit-v3 exports.

- [ ] **Step 2: Run the focused tests and verify the old facade fails**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_public_api.py \
  tests/test_capability_v3_cli.py -q
```

Expected: FAIL because the unversioned facade and CLI still produce v2.

- [ ] **Step 3: Replace the unversioned package facade**

In `src/minimal_agent/capabilities/__init__.py`, alias the existing names to v3 implementations while preserving their registry-based signatures:

```python
CapabilityBundle = CapabilityBundleV3
BundleValidationResult = BundleValidationResultV3
CapabilityBundleValidationError = CapabilityBundleValidationErrorV3
build_capability_bundle = build_capability_bundle_v3
build_capability_snapshot = build_capability_snapshot_v3
export_capability_bundle = export_capability_bundle_v3
validate_capability_bundle = validate_capability_bundle_v3
```

Remove `UnsupportedCapabilityError` from the facade because it belongs only to the deleted v2 protocol.

- [ ] **Step 4: Replace the unversioned CLI with a v3 delegate**

Implement `minimal_agent.capabilities.cli.main(argv: Sequence[str] | None = None) -> int` as a thin call to `minimal_agent.capabilities.v3.cli.main`. Do not add version detection or fallback.

- [ ] **Step 5: Run focused and public compatibility tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_public_api.py \
  tests/test_capability_v3_cli.py \
  tests/test_capability_v3_builder_contract.py -q
```

Expected: PASS; the root `minimal_agent.__all__` remains exactly 13 names.

- [ ] **Step 6: Commit**

```bash
git add src/minimal_agent/capabilities/__init__.py src/minimal_agent/capabilities/cli.py tests/test_public_api.py tests/test_capability_v3_cli.py
git commit -m "refactor: switch capability facade to v3"
```

### Task 2: Move runtime versions out of the legacy capability package

**Files:**
- Create: `src/minimal_agent/versions.py`
- Modify: `src/minimal_agent/capability_adapter.py`
- Create: `tests/test_runtime_versions.py`
- Modify: `tests/test_capability_v3_export.py`
- Modify: `tests/test_capability_v3_validation.py`

**Interfaces:**
- Consumes: current values from `minimal_agent.capabilities.versions` and Kit hashing helpers.
- Produces: `MODEL_CLIENT_PROTOCOL_VERSION`, `TOOL_REGISTRY_CONTRACT_VERSION`, and `agent_package_version()` in `minimal_agent.versions`.

- [ ] **Step 1: Write the failing runtime-version ownership test**

Create `tests/test_runtime_versions.py` importing the three runtime values from `minimal_agent.versions` and assert:

```python
assert MODEL_CLIENT_PROTOCOL_VERSION == "environment-configured-responses-api-v1"
assert TOOL_REGISTRY_CONTRACT_VERSION == "tool-registry-v2"
assert agent_package_version() == "0.1.0"
```

The `tool-registry-v2` value is a ToolRegistry contract version, not Capability Snapshot Protocol v2, and must remain unchanged to preserve v3 snapshot hashes.

- [ ] **Step 2: Run the test and verify the new module is missing**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_runtime_versions.py -q`

Expected: FAIL during import of `minimal_agent.versions`.

- [ ] **Step 3: Create the runtime version module and update the Adapter**

Move the three runtime-owned values/functions into `src/minimal_agent/versions.py`. Update `minimal_agent.capability_adapter` to import from the new module. Do not change their values.

- [ ] **Step 4: Remove v2 hashing imports from v3 tests**

Update v3 export and validation tests to import `calculate_snapshot_sha256` from `capability_snapshot_kit`, proving current v3 code no longer relies on the legacy hashing module.

- [ ] **Step 5: Verify snapshot parity and runtime versions**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_runtime_versions.py \
  tests/test_capability_v3_generator_parity.py \
  tests/test_capability_v3_export.py \
  tests/test_capability_v3_validation.py -q
```

Expected: PASS with the checked-in v3 Agent and Bundle hashes unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/minimal_agent/versions.py src/minimal_agent/capability_adapter.py tests/test_runtime_versions.py tests/test_capability_v3_export.py tests/test_capability_v3_validation.py
git commit -m "refactor: separate runtime versions from capability protocol"
```

### Task 3: Delete v2 artifacts, implementation, documentation, and tests

**Files:**
- Create: `tests/test_v3_only_repository.py`
- Delete: `capabilities/**`
- Delete: `src/minimal_agent/capabilities/bundle.py`
- Delete: `src/minimal_agent/capabilities/catalog.py`
- Delete: `src/minimal_agent/capabilities/hashing.py`
- Delete: `src/minimal_agent/capabilities/models.py`
- Delete: `src/minimal_agent/capabilities/versions.py`
- Delete: `docs/CAPABILITY_SNAPSHOT.md`
- Delete: `docs/RUNTIME_CAPABILITY_MIGRATION.md`
- Delete: `tests/test_capability_protocol_v2.py`
- Delete: `tests/test_capability_snapshot.py`
- Delete: `tests/test_capability_snapshot_cli.py`
- Delete: `tests/test_capability_v2_compatibility.py`
- Delete: `tests/test_configured_capabilities.py`
- Modify: `tests/test_capability_v3_export.py`
- Modify: `tests/test_capability_v3_validation.py`
- Modify: `README.md`
- Modify: `docs/CAPABILITY_SNAPSHOT_V3.md`

**Interfaces:**
- Consumes: the v3-only facades and runtime-version module from Tasks 1–2.
- Produces: a repository containing no Capability Snapshot Protocol v2 implementation or artifact.

- [ ] **Step 1: Write the failing repository-boundary test**

Create `tests/test_v3_only_repository.py` asserting:

```python
assert not (PROJECT_ROOT / "capabilities").exists()
assert not (PROJECT_ROOT / "docs/CAPABILITY_SNAPSHOT.md").exists()
assert not (PROJECT_ROOT / "docs/RUNTIME_CAPABILITY_MIGRATION.md").exists()
for name in ("bundle", "catalog", "hashing", "models", "versions"):
    assert not (PROJECT_ROOT / f"src/minimal_agent/capabilities/{name}.py").exists()
```

Also walk tracked source, active documentation, and tests to assert that Capability Snapshot format version `2.0` and the deleted module paths do not remain. Exclude historical `docs/superpowers/` design/plan records from this scan.

- [ ] **Step 2: Run the boundary test and verify it fails on existing v2 files**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_v3_only_repository.py -q`

Expected: FAIL listing the existing `capabilities/` directory and legacy modules.

- [ ] **Step 3: Delete the v2 files and v2-only tests**

Delete only the files listed in this task. Preserve `src/minimal_agent/capabilities/__init__.py`, `cli.py`, and the complete `v3/` directory.

- [ ] **Step 4: Retain non-v3 rejection coverage under v3 names**

Rename v3 tests that mention v2 generically to “non-v3” or “wrong protocol version” while keeping fixtures that prove version `2.0` is rejected. Replace the v3 export test that protects the old Bundle with an assertion that export does not create a legacy `capabilities/` sibling.

- [ ] **Step 5: Update active documentation to v3-only**

Remove the v2 compatibility section and commands from `README.md`. Replace the v2/v3 isolation section in `docs/CAPABILITY_SNAPSHOT_V3.md` with a v3-only rule stating there is no legacy loader, migration, or fallback.

- [ ] **Step 6: Run boundary, facade, Builder, and QueryUser tests**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_v3_only_repository.py \
  tests/test_public_api.py \
  tests/test_capability_v3_cli.py \
  tests/test_capability_v3_builder_contract.py \
  tests/test_capability_v3_query_user_bundle.py \
  tests/test_query_user_evaluation_adapter.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A capabilities src/minimal_agent/capabilities docs README.md tests
git commit -m "refactor: remove capability protocol v2"
```

### Task 4: Verify the v3-only release boundary

**Files:**
- Modify only if verification exposes a requirement violation.

**Interfaces:**
- Consumes: the completed v3-only repository.
- Produces: final evidence that the public facade, generated Bundle, and repository boundary are coherent.

- [ ] **Step 1: Export with both CLI paths and compare bytes**

Export into two temporary directories with:

```bash
PYTHONPATH=src .venv/bin/python -m minimal_agent.capabilities.cli export --output <unversioned>
PYTHONPATH=src .venv/bin/python -m minimal_agent.capabilities.v3.cli export --output <explicit-v3>
```

Recursively compare every file. Expected: byte-identical directories with v3 counts of 1 Agent, 7 Module, 7 Intent, 0 Tool, 5 Scope, 3 Chain, 5 Evidence, and 7 Boundary.

- [ ] **Step 2: Validate the checked-in v3 Bundle**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m minimal_agent.capabilities.cli \
  validate --input capabilities-v3
```

Expected: `valid: true` and `snapshot_format_version: "3.0"` at the root.

- [ ] **Step 3: Scan for active v2 implementation references**

Run targeted `rg` checks over `src`, `tests`, `README.md`, and active protocol documentation. Historical `docs/superpowers/` records are allowed to describe the migration; active code and docs must contain no Capability Protocol v2 implementation, loader, artifact path, or fallback.

- [ ] **Step 4: Run full verification**

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m ruff check .
git diff --check
```

Expected: all tests pass except the existing opt-in paid OpenAI smoke skip; Ruff and diff checks pass.

- [ ] **Step 5: Review the complete branch diff**

Confirm that no unrelated user-owned untracked files changed, `minimal_agent.__all__` remains 13 names, the checked-in `capabilities-v3/` bytes are unchanged, and the only deleted generated directory is `capabilities/`.

No commit is required if verification makes no changes. If a verification-driven fix is needed, use a focused commit describing that fix.

---

## Final Acceptance Checklist

- [ ] `capabilities/` does not exist.
- [ ] No v2 capability source module remains.
- [ ] Unversioned Python API names execute v3.
- [ ] Both CLI paths execute the same v3-only implementation.
- [ ] Non-v3 roots fail closed.
- [ ] Runtime version metadata in v3 snapshots is unchanged.
- [ ] `capabilities-v3/` remains Builder-ready and independently valid.
- [ ] Builder and QueryUser contract tests pass.
- [ ] Root public API remains exactly 13 names.
- [ ] Full tests, Ruff, and diff checks pass.
