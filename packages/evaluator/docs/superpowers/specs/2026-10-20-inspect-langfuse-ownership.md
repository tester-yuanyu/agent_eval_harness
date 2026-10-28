# Inspect / Evaluator / Langfuse ownership

Status: user approved the detailed responsibility split and implementation.

## Scope

One production execution and scoring path through Inspect. Native model grading
replaces the DeepEval backend; preserve business rubrics, independent credentials,
unknown/error semantics and critical veto. Backend identity changes require a new
baseline, not a claim that G-Eval and Inspect grading are equivalent.

Langfuse Cloud is the preferred observation and collaboration endpoint. Add explicit
SDK export of saved runs, deterministic IDs, original timestamps, categorical
unknown states, scores with evidence references, experiment association and review
import. No custom web UI or second experiment runner. Credentials remain outside
artifacts. Missing credentials block cloud acceptance, not local development.

## Non-negotiable rules

- Langfuse or Inspect capability replacements delete accepted legacy production paths.
- Every metric has one producer; dashboards read authoritative results.
- Every data class has one authority; no two editable rubric/review/baseline stores.
- Retained code must be a business rule, adapter, or demonstrated native gap.
- Inspect invokes custom business Scorers; there is no independent scoring engine.
- Agent runtime never receives Oracle or grading reference answers.
- Trial environment creation, independent state reads and cleanup remain Provider work.
- Unknown evidence is never numeric half-credit or a passing result.
- Formal, experimental and human scores have distinct provenance.
- Review imports append snapshots; never mutate automated results or auto-change gates.
- Existing uncommitted vendor/extension migration is preserved.

## Authorities and outputs

Builder freezes datasets; Evaluator validates them and maps samples to Inspect.
Inspect EvalLog is the execution record. `results.json` is the immutable domain
snapshot consumed by compare/gate/export; other local files are derived views.
Formal Rubrics and Taxonomy are versioned in the repository. Langfuse is the review
editing source; imported snapshots retain source IDs and result hashes.
Baseline remains the explicit baseline argument to compare/gate.

Metrics run in the Inspect pipeline, preserving business-specific denominator and
validity policies. Prefer native metrics for matching operations; keep only the
business aggregation code needed for nonstandard semantics. Run display exports
reuse computed values rather than counting trace rows to infer case pass rate.

## Acceptance

Offline tests exercise real Inspect model grading with mock model outputs and the
real Langfuse SDK against a recording local transport. Verify no paid calls or
hosted writes in default tests. Verify unknowns, critical failures, all Trial IDs,
partial/retried export, immutable local results, original timestamps, review
identity/validation, metadata-only safe defaults and explicit payload opt-in.
Run the complete extension suite and lint after removing obsolete paths.
Cloud validation is a separate opt-in check using configured credentials; document
what was and was not verified. Do not claim UI/dashboard availability was tested
without a live project.
