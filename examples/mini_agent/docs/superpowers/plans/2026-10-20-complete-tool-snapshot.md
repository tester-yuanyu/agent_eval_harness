# Complete Tool Snapshot Implementation Plan

> Execute inline with the executing-plans workflow; use test-driven-development for code changes.

**Goal:** Deliver a validated Snapshot 3.0 bundle containing all six required business tools with executable, explicitly labelled test-fixture bindings.

**Architecture:** Reuse the existing ToolContract, Registry and compiler. Add a generic, strict registry assembly/factory interface shared by the runtime CLI and capability export CLI. Keep synthetic business data and handlers in an explicit example integration, outside the production runtime. Deliver coverage of the capability inventory and a machine-readable gap report without claiming production backends or unsupported runtime features.

**Tech Stack:** Existing Python 3.11, Pydantic, pytest, Capability Snapshot Kit.

**Spec:** `docs/superpowers/specs/2026-10-20-langgraph-orchestration-design.md`, tool assembly and snapshot sections.

## Global Constraints

- Preserve existing dirty worktree changes and frozen capabilities/ and exports/trace_v1.
- Snapshot format remains 3.0; zero-tool default remains valid for intent-only use.
- Complete means six required tool bindings, not seven (unsupported has no tool).
- Fixture contracts must not claim production, automatic retries, confirmation resume or context.
- Snapshot files must not contain synthetic user records or evaluator expected results.
- LangGraph migration and the full reviewed evaluation dataset remain separate work items.

## Review Focus

- Unknown, missing or non-callable handlers must fail before a complete export.
- A runtime factory selected explicitly by the caller must be identical for CLI execution and export; no imports inferred from input bundles.
- Successful fixture writes must affect only isolated instance state; repeated preparation IDs must detect conflicting requests.
- Gift grants must fail closed without a separate fixture approval, even when requested through an unrelated read intent.
- Multi-condition queries must obey AND, scalar-mode exclusivity and partial/empty semantics.

## Tasks

### 1 Assembly and CLI

Files: `runtime/tool_binding.py`, `cli.py`, `capabilities/v3/cli.py`, `tests/test_tool_binding.py`.

- [x] Write failing tests for complete/missing/unknown/noncallable binding, trusted factory loading, runtime/export parity.
- [x] Add `bind_tools(contracts, handlers) -> ToolRegistry` and separate `require_complete_tools(intents, tools)`.
- [x] Add `load_tool_registry(factory_path) -> ToolRegistry`, explicit module:callable only.
- [x] Add export/runtime `--tool-registry-factory` selection and export `--require-complete-tools`.
- [x] Verify old CLI commands retain their zero-tool behavior.

### 2 Executable fixture integration

Files: `examples/full_tool_fixture/contracts.py`, `environment.py`, `results.py`, `__init__.py`, `tests/test_full_tool_fixture.py`.

- [x] Write failing tests for all six tool semantics, state isolation, argument rejection and confirmation boundaries.
- [x] Define six explicit test_fixture contracts, deriving existing argument constraints where available.
- [x] Implement in-memory queries, resource preparation, and approval-guarded gift grants with caller-owned synthetic data.
- [x] Keep all fixture values out of contract metadata.
- [x] Export factory `examples.full_tool_fixture:create_registry`.

### 3 Snapshot and delivery validation

Files: `tests/test_full_tool_snapshot.py`, `docs/FULL_TOOL_CAPABILITY_BUNDLE.md`, `README.md`.

- [x] Verify 7 modules, 7 intents, 6 tools, 2 critical chains, 1 end-to-end chain.
- [x] Verify every business intent references its matching tool, and unsupported has no tool reference.
- [x] Verify duplicate exports are deterministic and the bundle resolves a QueryUser chain.
- [x] Correct the obsolete fresh-equals-frozen test to preserve frozen integrity and current export reproducibility.
- [x] Generate `exports/full_tools_fixture_v1/` with the selected factory.
- [x] Generate sibling validation, capability inventory and gap reports tied to bundle hash.
- [x] Run complete repository tests and lint; report pre-existing failures separately.
- [x] Verify Builder can load the new bundle using its own trusted validation.

## Definition of done

The bundle exists on disk, all six tool snapshots are present, the source factory can recreate it, all references/hashes validate, tests demonstrate actual fixture behavior, and the report distinguishes registered execution from production availability and unfinished runtime capabilities. No claim that human review or full evaluation dataset production has occurred.


## Execution and verification — 2026-10-20

- Delivered `exports/full_tools_fixture_v1/bundle/`, with 7 modules, 7 intents, 6 tools, 2 critical chains and 1 end-to-end chain. Builder must consume this `bundle/` directory.
- Bundle SHA256: `215a9a3a445c8857f3bdd8dbecba935ce646bd8c784f16ecfc4a5da6042cce3c`. Verified all 54 file digests recorded in the delivery manifest.
- Repository verification: `295 passed, 1 skipped` (paid OpenAI smoke test), and `ruff check .` passed. Baseline had an obsolete current-export-equals-frozen assertion; replaced it with frozen integrity plus current export reproducibility checks.
- Independent review found incomplete nested result schemas. Added five strict result record models shared by handler output validation and snapshot schemas; regression tests and follow-up review passed.
- Builder trusted-profile validation passed using the actual `dataset_builder.capability_bundle.load_validated_bundle` and Builder trust store. It ran with the Evaluator virtual environment and Builder source on `PYTHONPATH`, because Builder's own environment lacks `langfuse`. This verifies bundle ingestion only; it does not establish dataset generation or evaluation execution.
- Frozen `capabilities/` and `exports/trace_v1/` were preserved. No source commit was created for this change.
- The six tools are executable isolated test fixtures. Production service bindings, LangGraph migration, confirmation resume, full layered JSONL datasets, case coverage matrix and human review are not completed by this delivery. Machine-readable gaps are included alongside the bundle.
