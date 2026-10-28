# Inspect / Langfuse migration implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement inline.

**Goal:** Remove duplicated scoring paths and connect authoritative results to Langfuse.

**Architecture:** Inspect runs tasks, formal scorers and metrics. Evaluator provides
business evidence and policies. Langfuse consumes results for observation and review.

**Tech Stack:** Python 3.11, local Inspect 0.3.280, Langfuse SDK 5.0.2, pytest.

**Spec:** ../specs/2026-10-20-inspect-langfuse-ownership.md

## Global Constraints

- One production implementation and one metric producer.
- Frozen scoring contracts are authoritative; cloud experiments cannot alter gates.
- No Oracle leakage, implicit uploads, credential leakage, or unknown-as-half-score.
- Preserve historical result loading and the existing uncommitted repository state.

## Review Focus

- Retry uploads must not multiply Trial, experiment item or score records.
- Missing evidence and invalid runs must not become numerical passing scores.
- Imported reviews must belong to the selected run and retain revision provenance.
- Native grading errors and changed backend identity must remain distinguishable from failures.
- Existing results and business evidence must remain usable without Langfuse credentials.

## Task 1: Native Inspect Judge

Files: `judges/inspect.py`, `judges/__init__.py`, `cli.py`, `pyproject.toml`,
`scripts/bootstrap_inspect.py`, Judge tests. Remove accepted DeepEval paths.

Interface: `InspectJudgeClient.evaluate(JudgeRequest) -> object`,
`from_env(timeout_seconds=...)`, `metadata()`.

- [x] Add tests for native numeric model grading, invalid/missing grades, timeout,
  private credentials, immutable input and comparable backend metadata.
- [x] Run failing tests.
- [x] Implement native `model_graded_qa` adapter with a shared attempt deadline.
- [x] Validate replacement, remove DeepEval adapters/dependency and obsolete tests;
  preserve equivalent business-invariant coverage and historical result loading.
- [x] Run Judge and engine tests.

## Task 2: One metric producer inside Inspect

Files: `inspect_engine.py`, `inspect_metrics.py`, `runner.py`, `stability.py`.
Interface: native execution returns authoritative summary and stability snapshots.

- [x] Test Inspect log metrics match domain results for multiple trials and unknowns.
- [x] Run failing test.
- [x] Move domain aggregation into an Inspect metric; reuse native mean where exact.
- [x] Remove Runner's separate post-execution aggregation calls and duplicate aliases.
- [x] Run engine, stability, reporting, comparison and gate tests.

## Task 3: Langfuse export and experiment association

Files: `observability.py`, CLI, new integration tests.
Interface: `export_run(run_dir, *, include_content=False, client=None) -> dict`.

- [x] Test deterministic IDs, original timing, scores/unknowns, experiment mapping,
  immutable source, no secret export, SDK errors and repeat export via local transport.
- [x] Run failing tests.
- [x] Implement explicit SDK export and `export-langfuse` CLI. Reuse saved summary.
- [x] Retain receipts separately from authoritative results; allow safe retry.
- [x] Run offline SDK integration and CLI tests.

## Task 4: Review import and authority boundaries

Files: `adjudication.py`, CLI, review tests, versioned taxonomy configuration.
Interface: import structured Langfuse review scores into append-only snapshots.

- [x] Test source/run/result binding, invalid labels, duplicates and revised review.
- [x] Implement original-score preservation and idempotent revision import.
- [x] Remove duplicate manual review write CLI after replacement acceptance.
- [x] Run adjudication, gate and round-trip tests.

## Task 5: Documentation and acceptance

- [x] Update README, architecture and ownership/removal inventory; preserve historical notes.
- [x] Run full extension tests, lint and dependency checks.
- [x] Run fresh-context review and fix important findings with regression tests.
- [x] Cloud credentials configured; 5 smoke trials and all 71 score IDs read back; Trace and Experiments UI verified.
- [x] Run all 42 cases of the compatible query-user v2.0 module; verify 478 cloud scores and native Inspect results.
- [x] Replace initial three-dashboard prototype with one native analytical dashboard (9 widgets), a 42-row Tracing saved view and scoped Scores Analytics. Delete empty tools/redundant failures dashboards and 7 unused widgets; retain native Experiments.
- [x] Add 42 immutable scenario labels (520 Scores total); fix immutable observation retransmission with checkpoints and uncertain-upload protection; recover and verify 293 unique observations / 42 trials without rescoring. Export/review tests: 20 passed; Ruff passed.
- [x] Configure the structured human review score and queue; verify five PENDING items and the review form.
- [ ] Real human Annotation roundtrip remains pending; no synthetic human judgment was submitted.

## Execution notes

Working in place because extension sources are currently untracked inside an
existing vendor migration and a clean worktree would omit them. A pre-edit snapshot
is saved in `/tmp/agent-evaluator-langfuse-before`. Do not commit unrelated changes.
The user explicitly authorized implementation; proceed without another approval
round for the already agreed design. Plan adjustments and verification go here.


## Local acceptance (2026-10-20)

- Baseline before edits: 355 passed, 2 paid-model tests skipped.
- Replacement Judge RED: 14 failed (missing new adapter); GREEN: 14 passed.
- Native end-to-end Judge/historical compatibility: 23 passed.
- Initial full regression found two issues: native live metrics request partial
  datasets, and equivalence tests must ignore new per-Trial timestamps. Fixed
  by returning no partial business metrics, caching final metrics once, and
  normalizing volatile timing fields. The 42-case replay now passes.
- Final full suite: 348 passed, 2 paid-model tests skipped (69.14 s).
- Later taxonomy completeness correction: review + diagnostics tests 21 passed,
  including previously undetected PROTOCOL_NAMING_MISMATCH and ASSERTION_TURNS_MATCH.
- Ruff check of src/tests/examples/scripts/packages: passed. pip check: passed.
  Installed metadata requires Langfuse 5.0.2; DeepEval package is absent.
- Fresh-context review found missing Langfuse Scores field selection and missing
  builtin taxonomy labels. Both corrected and covered by regression tests.
- CLI now exposes export-langfuse and import-reviews. SDK integration tests use
  real generated clients with mock HTTP; no cloud requests or paid LLM calls.
- No custom Dashboard, second experiment runner or editable local review path.
  Cloud connection, score readback and experiment display were verified on the
  5-case real-model smoke run and the later 42-case full module run. Three native
  dashboards plus Experiments were visually verified. Human annotation roundtrip,
  actual tool execution coverage and multi-trial stability remain outstanding. Formal semantic
  threshold calibration and baseline rerun are required before using new Judge
  results for release comparison; no claim of G-Eval numerical equivalence.
