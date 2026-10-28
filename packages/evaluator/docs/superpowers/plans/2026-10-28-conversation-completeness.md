# Conversation Completeness and current baseline implementation plan

> **For agentic workers:** Use superpowers:executing-plans; implement inline, then request one independent review.

**Goal:** Add opt-in Conversation Completeness inside Inspect and establish a real, frozen-input baseline with verified local Langfuse delivery.

**Architecture:** Inspect executes and scores every Trial. DeepEval supplies only its standalone metric algorithm; an Inspect model adapter supplies grading. Immutable results are the authority for reporting and Langfuse; this diagnostic does not affect quality conclusions or release gates before calibration.

**Tech Stack:** Inspect 0.3.280, optional pinned DeepEval 4.2.9, existing Langfuse 5.0.2.

**Spec:** `docs/metric_dictionary.md` B0/B1; root and extension AGENTS.md; user-approved baseline and first metric implementation.

## Global constraints

- No second Runner, model transport, aggregation engine, or hosted upload.
- Default off; use explicit independent Judge environment settings.
- Actual ordered multi-turn messages only; no unused scripted follow-ups or Oracle inputs.
- Error/missing verdicts are unknown, never zero or success; no new gate threshold.
- Version/model/template/input provenance accompanies formal results.
- Preserve historical result readability and existing symlink migration; no unrelated commits.

## Review focus

- Empty intentions and partial verdicts must not become a high score.
- Truncated/failed conversations must not be evaluated as complete.
- Ambient Confident credentials and dotenv must not enable uploading.
- Diagnostic error and low scores must not change deterministic verdicts.
- Reports/export/comparison must consume stored snapshots, including missing values.

### Task 1: Metric adapter and contract

Files: new `diagnostic_metrics.py`, `judges/conversation.py`; schema and optional dependency edits; `tests/test_conversation_metric.py`.

- [x] Tests: actual-turn selection, malformed input, public real metric with Inspect mock model, zero/partial/invalid verdicts, timeout, independent per-Trial instances, no external network.
- [x] Verify failing tests before implementation.
- [x] Implement strict configuration/result models and lazy optional adapter using public `a_measure`, fixed LLM mode, fixed template identity, Inspect transport and zero request retries.
- [x] Verify targeted tests pass.

### Task 2: Formal pipeline and consumers

Files: `runner.py`, `inspect_engine.py`, `inspect_metrics.py`, `schemas.py`, `cli.py`, `comparison.py`, `reporting.py`, `observability.py`; integration tests.

- [x] Tests: optional default absence, Suite/CLI configuration, Scorer integration, diagnostic failure isolation, saved summaries/export and configuration comparability.
- [x] Execute metric once inside existing Scorer; aggregate once using Inspect; persist run metadata and result evidence.
- [x] Render and export saved diagnostic status/score/summary without recomputation; compare diagnostic fingerprints.
- [x] Update usage and metric ownership docs.

### Task 3: Baseline and verification

- [x] Run extension tests and lint with its own pyproject.
- [x] Independent review; resolve findings and reverify changed behavior.
- [x] After code stabilizes, execute fixed DeepSeek Agent on the frozen 42-case query-user dataset; retain immutable artifacts and source fingerprints.
- [x] Exercise comparison/Gate with explicit inputs; label self-comparison as plumbing verification, not regression evidence.
- [x] Verify stored summary/report/Gate/local Langfuse scores agree via API readback.
- [ ] Run a real multi-turn Judge pilot after credentials are authorized; independent Judge settings remain absent and the user account-choice question is pending. Controlled Judge/Agent outputs have completed the full real-library/local-service pipeline.

## Ledger

- Backup before this implementation: `/var/folders/p4/1c0yhj5d3_91l0vf59sn38700000gn/T/conversation-metric-6k43ck8o`.
- Ruling: Build the final baseline after implementation; extension source identity changes invalidate comparisons with an earlier runtime.
- Ruling: Leave existing migration uncommitted and operate through symlinks; worktree creation would omit the untracked extension.
- Local Langfuse is enabled and healthy at loopback port 3300. Agent DeepSeek credentials exist; independent Judge settings are absent; user clarification is pending.

- Final verification: 599 passed, 2 opt-in paid smoke tests skipped; Ruff passed.
- Independent review found two issues (orphaned concurrent verdict requests and incomplete terminal runtime states); both reproduced with failing tests, fixed, and independently rechecked (7 targeted tests).
- Frozen real Agent baseline: 42/42 PASS, DeepSeek deepseek-flash, one Trial per case. Runtime fingerprint unchanged through verification.
- Self-comparison COMPARABLE and example-policy validation Gate PASS; old baseline rejected for METRIC_VERSION_MISMATCH/EVALUATION_BACKEND_MISMATCH. Self-comparison is not regression evidence.
- Local Langfuse API readback matched 89 baseline scores and 22 diagnostic self-test scores; 4 missing numerical scores correctly absent.
- Durable records: artifacts/metric_baseline_20261028/REPORT.md, tests.log, langfuse_readback.json.
