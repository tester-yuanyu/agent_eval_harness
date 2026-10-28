# Metric consolidation implementation plan

> Execution: inline, with regression tests first and review after implementation.

**Goal:** Remove duplicate metric calculations while preserving frozen business semantics and historical readability.
**Architecture:** Inspect owns aggregation. Evaluator adapts eligible populations and persists one performance snapshot. Gate and comparison consume that snapshot; scoped label metrics use the same eligibility function. No second scoring engine or new dependency.
**Spec:** User-approved audit in this conversation, 2026-10-28; ownership rules in AGENTS.md.

## Decisions and constraints

- Keep statistical median under its existing median name. P50/P95 use nearest-rank consistently. Rename the report's misleading P50 label for median.
- PASS rate excludes NOT_APPLICABLE and includes FAIL/INCONCLUSIVE. Record group applicable_count; all-inapplicable groups have a null rate. Framework-validation runs have no agent quality rate.
- Tag new summaries with a metric version; reject comparison across metric versions. Old files remain readable and are never rewritten by compatibility projection.
- Save run latency percentiles and per-Trial Judge token totals in summary.performance. Comparison embeds each side's saved performance; historical comparisons use one central delta adapter.
- Arbitrary gate label unions are a distinct scoped metric, computed once using shared eligibility and saved in gate checks. Never sum overlapping label aggregates.
- Preserve planned-Trial stability denominators, Oracle isolation, critical-failure precedence, explicit exports and existing uncommitted work.
- Judge retries currently repeat a whole multidimensional attempt; Inspect retries individual requests. Retain business attempt semantics unless an equivalent replacement is proven; verify native request retries remain disabled.
- Work directly in the existing symlinked extension, backed up to a temporary directory; do not commit unrelated migration work.

## Task 1 — Unified aggregation and persisted performance

Files: phase2_schemas.py, schemas.py, inspect_metrics.py, stability.py, inspect_engine.py; new metric_policy.py; tests/test_native_aggregation.py.
- [x] RED: cover common group denominator, all-NA groups, framework mode, native grouping/counting, saved P50/P95/token values.
- [x] Implement shared eligibility and nearest-rank, native grouped/frequency adapters, PerformanceSummary and versioned SummaryStats.
- [x] Pass saved run performance into stability; preserve standalone API and planned denominators.
- [x] GREEN: focused aggregation and stability tests.

## Task 2 — Gate, comparison and report consumers

Files: gating.py, comparison.py, reporting.py; tests/test_gating.py, test_comparison.py, test_reporting_cli.py.
- [x] RED: label unions and NA handling; saved values consumed without recomputation; legacy run/comparison loading; mismatched metric versions rejected; median label correct.
- [x] Gate reads canonical saved performance; comparison consumes per-Trial token totals and embeds source snapshots. Remove duplicate percentile/token implementations.
- [x] Centralize read-only legacy projection, with no persisted result mutation. Bump changed policy/backend versions.
- [x] GREEN: focused comparison, Gate and report tests.

## Task 3 — Retry assessment, documentation and verification

- [x] Characterize whole-attempt Judge retries and ensure production native request retries are zero; retain distinct business retry scope with explicit metadata/documentation.
- [x] Update metric dictionary, report specification and ownership docs with new authority and version boundaries.
- [x] Run extension pytest and Ruff; inspect focused diff against the pre-task backup, check historical compatibility and no extra dependency/upload path.

## Review focus

All-NA/empty groups; overlapping labels; partial token usage and zero tokens; even-sized latency samples; legacy summaries/comparisons with no new snapshot; metric version mismatch; missing planned trials; incomplete multi-dimension Judge attempts.

## Execution record

- Initial regression: 7 failures reproduced denominator, missing snapshot, and metric-version gaps; 10 existing checks passed.
- Focused verification: 89 tests passed. Final full extension suite: 572 passed, 2 paid-model tests skipped, 57 deprecation warnings (90.64s). Ruff passed.
- Independent review found no actionable defects; incremental stability-count review also clean.
- Final cleanup: stability categorical counts now reuse the same native frequency adapter; regression first failed, then all 30 focused aggregation/stability/authority tests passed.
- Documentation checks: all 22 assertion IDs, 20 SummaryStats fields, 20 GatePolicy fields, 6 performance fields and 10 candidate metrics covered; tables and local links valid. Dependency file unchanged; historical files and source symlinks preserved.
- Ruling: retain whole-attempt Judge retry because per-request retry would reuse successful dimensions from an incomplete attempt; regression verifies four model calls and only final-attempt scores.
