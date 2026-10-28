# Automatic Agent Intake Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans. Preserve the existing migration and use the extension configuration.

**Goal:** Automatically import supported new-Agent evaluation deliveries and execute runnable partitions through the existing Inspect pipeline.

**Architecture:** Intake validates and snapshots data, produces standard Suites, and selects trusted Providers. Generic observation assertions and runtime bindings supply compatibility without a second scoring engine.

**Tech Stack:** Python 3.11, Pydantic, JSON Schema, Inspect 0.3.280, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-24-agent-onboarding-design.md`.

## Global Constraints

- Inspect owns execution, scoring and metric aggregation.
- Oracle values never enter ExecutionSpec or Agent/worker requests.
- Preserve original source bytes, readiness/support state and source-ID mappings.
- No data-provided commands/imports; runtime bindings are separate explicit inputs.
- No upstream Nanobot/Builder edits, model calls, hosted upload or broad migration commits.
- Existing historical results and mini_agent behavior remain readable and compatible.

## Review Focus

- ZIP traversal/symlinks/duplicate roots and source hash or pointer tampering.
- Generic return assertions cannot bypass missing independent state evidence.
- Execution binding must match Agent identity and not expose environment credentials.
- Partial/static/draft results must not appear as complete release approval.
- Empty/blocked-only partitions must emit a valid intake report without fake scores.

## Progress and acceptance boundary

Implementation of Tasks 1–3 and the CLI/documentation portion of Task 4 is present in the shared workspace. Component regression evidence is recorded in `artifacts/agent_onboarding_20261024/progress.md` and the task reports. Checked implementation items do not claim final release acceptance. Root owns the final integrated test/lint run, actual Nanobot execution, source-integrity checks, and coverage readout.

## Tasks

### Task 1: Generic observation contract and neutral capabilities

Own schemas.py, provider.py, runner.py, assertions.py, dataset_validator.py, evidence_requirements.py, gating.py, capability_loader.py, mini_agent/capability_adapter.py and focused tests/schema files.

- [x] Write failing tests for generic return observations with no intent/goal-state, missing evidence and preserved critical mismatches, neutral v3 payload identity, and intake gate exclusion.
- [x] Add optional `ExecutionSpec.adapter_input`, `AdapterOutput.observations`, `CaseResult.observations`, `DatasetBundle.onboarding`, `EvaluationRunResult.onboarding`.
- [x] Add `observation_assertions.py` with `ObservationCheckConfig` and `evaluate_observations(observations, config)`; config shape: `{checks:[{path: JSONPointer, operator: equals|contains|not_contains|ends_with|schema_valid, expected: Any}], channel: returned|independent}`. Register `observations_match` for all scopes; returned observations do not imply independent process/state evidence.
- [x] Keep existing structural validation for old assertions; permit observation-only cases without fictitious intent/goal-state/tool constraints. Add independent-channel requirements. Copy onboarding into results and reject ineligible intake results in gate.
- [x] Extract `load_capability_bundle(root, expected_sha256=None)` into neutral capability_loader.py, preserve original v3 payload; retain mini_agent compatibility normalization wrapper.
- [x] Regenerate schema files and run focused tests/lint.
- [x] Include non-None generic observations in the existing normalized output hash, preserving historical None-output hashes and explicit custom normalizers; focused stability regression verifies changed/repeated outputs.

### Task 2: Trusted execution adapters

Own new `providers/external/` package and tests. No core file changes; root wires registration.

- [x] Write failing tests for strict stdio response, only execution sent, environment values absent from metadata, output bounds, timeout and cleanup.
- [x] Implement `ExternalProviderFactory` with `create(dataset, model_client_factory=None, **config)` and `validate_dataset(dataset, **config)`. Config contains `binding` (separate trusted input) and sibling `runtime_files`; Agent identity comes from dataset and binding, factory has no fixed provider_id.
- [x] Binding shape: `{version:'1.0', agent_id, adapter:'static'|'nanobot_local'|'stdio', agent_root?:absolute path, python?:absolute path, argv?:list[str], env_names?:list[str], timeout_seconds?:number, max_output_bytes?:integer}`. Reject extra keys and inline env values. `adapter='static'` requires no Agent runtime.
- [x] Implement `binding_supports(binding, execution_payload) -> tuple[bool,str|None]` with fixed supported operation dispatch. Payload contains `{input:dict, preconditions:list}` and bounded `source_files` metadata where the fixed adapter requires it; static input contains inline bound schema or declared value. Expected values never passed.
- [x] Return AdapterOutput(observations=...) with no self-reported pass/score. Strict stdio response `{protocol_version:'1.0', observations:dict}`; request `{protocol_version:'1.0', execution:ExecutionSpec.model_dump()}`. Optional independent evidence is not inferred from stdout.
- [x] Nanobot worker supports `construct_and_serialize/RunResult` and `invoke_module/result_from_response` only. It directly loads hash-bound `nanobot/runtime_context.py` and `nanobot/sdk/types.py` under fixed names without package initializers, and uses in-memory fixtures without initializing a model/tool/session runtime. Other operations yield readiness findings. This fixed worker is not an OS sandbox for arbitrary trusted local code.
- [x] Provider uses neutral capability loader and explicit profiles; diagnostics empty; metadata includes only safe source/interpreter/adapter identity. Run focused tests/lint.

- [x] Snapshot selected runtime files using `snapshot_runtime_binding`; record hashes beside binding, require exact file identity for non-static Providers, and recheck before launch. stdio binds the executable/interpreter and selected absolute code-file arguments; Nanobot additionally binds its two fixed source modules. No claim of hashing every transitive library dependency.

### Task 3: Verified delivery import and Suite preparation

Root owns new `onboarding/` package plus loader/catalog registration and tests.

- [x] Write tests for verified directory/ZIP, neutral second Agent, candidate mapping and blocked-only delivery, traversal/hash/pointer errors.
- [x] Implement strict candidate records, safely snapshot directory/ZIP inputs into run output, verify manifest counts/hashes and source references, auto-detect existing Suite and EvalCase formats.
- [x] Implement `CandidateDatasetLoader` returning DatasetBundle with source mapping/onboarding metadata and immutable split static/behavior subsets. Consume only explicitly declared sources. Convert dot-subjects conservatively to JSON pointers; unknown ambiguous mappings remain blocked.
- [x] Prepare generated Suite JSON with all source dependency hashes and neutral capability contract; registered external Provider receives explicit binding, never binding from imported package. Candidate drafts run provisionally, ineligible for gates.
- [x] Emit intake.json ledger for every source record with disposition and reason owner, without computing business metrics.

### Task 4: CLI integration and acceptance

CLI/docs are delegated to the core-integration agent; root owns onboarding orchestration and final acceptance.

- [x] Add mutually exclusive source options `--input`/`--suite`/`--dataset`; candidate inputs accept either `--agent-root` or `--binding`. Auto-select known registered adapters from Agent identity and preserve existing CLI flags.
- [x] Run each nonempty partition through compile_suite/execute_compiled_suite/write_report; link authoritative summaries. Invalid package returns 2; incomplete valid intake returns 5, complete execution returns existing result semantics. No blocked-only success score.
- [x] Add end-to-end test using a second Agent stdio stub, verify Oracle never crosses subprocess, historical CLI tests, and malformed package structured failure.
- [x] Root reports actual Nanobot CLI execution completed: 2,128 static checks and 3 supported SDK behavior cases passed; draft/blocked status is retained. Final artifact/source-integrity reconciliation remains below.
- [x] Document supported protocol, binding examples, automatic behavior, runtime identity checks, host-process trust boundary and upstream gaps.
- [x] Independent review identified and prompted fixes for snapshot races, derived-dataset provenance, eager schema-reference closure, and runtime executable identity.
- [x] Root final acceptance: final extension suite 496 passed / 2 paid-API tests skipped; full Ruff passed. Final Nanobot CLI run completed 2,128 static and 3 SDK cases with PASS, retaining 247 blocked records. Original 263 files unchanged; saved results and native Inspect logs verified; both partitions rejected for release by the provisional-intake gate. Evidence: root artifacts/agent_onboarding_20261024/README.md and acceptance_verification.json.
