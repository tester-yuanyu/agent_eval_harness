# Agent Evaluator Phase Two Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add DeepSeek Judge, advanced Trace analysis, isolated multi-Trial stability metrics, baseline comparison, and local release gates to the current evaluator without adding CI workflows.

**Architecture:** Keep Agent execution and per-Trial Judge orchestration in the Runner, then implement Trace analysis, stability aggregation, comparison, and gating as deterministic modules over saved Pydantic results. Preserve every Trial result as immutable evidence, keep deterministic and Judge scores separate, and make comparison and gate outputs independently reloadable and auditable.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, Ruff, argparse, standard-library JSON/hash/path utilities, OpenAI Python SDK 2.x configured for DeepSeek Responses API.

**Spec:** `docs/superpowers/specs/2026-10-08-phase-two-evaluation-design.md`

## Global Constraints

- Do not create GitHub Actions or any other CI workflow.
- Default tests must be fully offline; real DeepSeek Judge calls require `RUN_DEEPSEEK_JUDGE_SMOKE=1`.
- Judge credentials use only `DEEPSEEK_JUDGE_API_KEY`, `DEEPSEEK_JUDGE_MODEL`, and `DEEPSEEK_JUDGE_BASE_URL`; never fall back to Agent credentials.
- Oracle and Judge reference facts must never enter Provider, Runtime, Agent ModelClient, or Agent requests.
- Deterministic critical, safety, final-state, permission, confirmation, and idempotency failures cannot be overridden by Judge scores.
- Keep deterministic scores and Judge scores separate; do not create a blended score.
- Every Case/Trial creates an independent Runtime, ModelClient, session, and Provider-managed state.
- Execute Trials sequentially in this phase; do not add concurrency.
- Do not mutate old `results.json`, Case results, assertions, or raw Trace while analyzing, comparing, or gating.
- Do not record hidden reasoning, complete system prompts, API keys, authorization headers, or secrets.
- Formal baselines and gates require frozen datasets; provisional runs remain analyzable but cannot produce a release PASS.
- Preserve compatibility with current single-Trial results, legacy `mini_agent_version`, and `cases/<case_id>.json` artifacts.

## Review Focus

- Multiple Trials for one Case must not overwrite Case files, evidence directories, sessions, or failed results; Task 2 pins this with collision and isolation tests.
- A required Judge timeout or malformed response must become `INCONCLUSIVE` unless deterministic evidence already proves `FAIL`; Task 3 pins the precedence table.
- Different datasets, filters, Trial counts, Capability Bundles, assertion versions, or Judge fingerprints must produce `INVALID_COMPARISON`; Task 5 tests every mismatch class.
- Missing, duplicate, out-of-order, or unresolvable Trace evidence must be reported as an observation rather than fabricated or called a root cause; Task 4 covers these inputs.
- Zero-tolerance failures must not be hidden by averages, Judge scores, fixes in other Cases, or later successful Trials; Task 6 exercises each masking attempt.

---

### Task 1: Phase-Two Protocols and Compatible Result Loading

**Files:**
- Create: `src/eval_framework/schema_base.py`
- Create: `src/eval_framework/phase2_schemas.py`
- Create: `src/eval_framework/result_loader.py`
- Modify: `src/eval_framework/schemas.py`
- Modify: `src/eval_framework/__init__.py`
- Modify: `schemas/eval_case.schema.json`
- Create: `tests/test_phase2_protocols.py`
- Create: `tests/test_result_loader.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: current `EvalCase`, `OracleSpec`, `CaseResult`, `EvaluationRunResult`, and strict `extra="forbid"` behavior.
- Produces: `JudgeDimensionSpec`, `JudgeCaseSpec`, `JudgeRunConfig`, `JudgeRequest`, `JudgeRubric`, `JudgeAttempt`, `JudgeResult`, `NormalizedTraceEvent`, `TraceIssue`, `TraceAnalysis`, `RunAnalysis`, `CaseStabilityResult`, `RunStability`, `ComparabilityReport`, `ComparisonResult`, `GatePolicy`, `GateResult`, `AnalysisPaths`, `ComparisonPaths`, and `GatePaths` from `phase2_schemas.py`.
- Produces: `load_run_result(path: str | Path) -> LoadedRunResult` and `LoadedRunResult(result: EvaluationRunResult, source_path: str, sha256: str)`.
- Produces: optional `OracleSpec.judge`, `RunConfig.trials_per_case`, `RunConfig.judge`, `CaseResult.labels`, `CaseResult.judge_result`, `CaseResult.trace_analysis`, `EvaluationRunResult.judge_metadata`, and `EvaluationRunResult.stability` fields with backward-compatible defaults. Existing serialized `score` remains the deterministic score; expose `CaseResult.deterministic_score` as a non-serialized read-only property returning `score`.

- [ ] **Step 1: Write failing strict-protocol tests**

Add tests asserting that Judge dimension weights are positive, thresholds are within 0–100, dimension names are unique, `trials_per_case` is positive, unknown phase-two fields fail, and a legacy single-Trial result loads with the new optional fields absent.

```python
def test_run_config_rejects_non_positive_trials():
    with pytest.raises(ValidationError):
        RunConfig(trials_per_case=0)


def test_legacy_result_loads_with_phase_two_defaults(legacy_results_path):
    loaded = load_run_result(legacy_results_path)
    assert loaded.result.trials_per_case == 1
    assert loaded.result.judge_metadata is None
    assert loaded.result.stability is None
    assert loaded.result.cases[0].deterministic_score == loaded.result.cases[0].score
```

- [ ] **Step 2: Run the protocol tests and verify they fail**

Run: `.venv/bin/python -m pytest tests/test_phase2_protocols.py tests/test_result_loader.py -q`

Expected: FAIL because phase-two models and `load_run_result` do not exist.

- [ ] **Step 3: Extract the shared strict base and add phase-two models**

Move `StrictModel` to `schema_base.py`, re-export it from `schemas.py`, and define focused phase-two models in `phase2_schemas.py`. Use these exact status enums:

- Judge: `NOT_APPLICABLE`, `COMPLETED`, `MODEL_OUTPUT_ERROR`, `MODEL_INVOCATION_ERROR`, `MODEL_TIMEOUT`.
- Comparison: `COMPARABLE`, `INVALID_COMPARISON`.
- Gate: `PASS`, `FAIL`, `REVIEW_REQUIRED`, `INVALID_COMPARISON`.

Keep all new models `extra="forbid"` and use defaults that allow existing serialized results to load unchanged.

- [ ] **Step 4: Extend current schemas without weakening answer isolation**

Add `judge: JudgeCaseSpec | None = None` only to `OracleSpec`; do not add Judge or Oracle data to `ExecutionSpec`. Add `labels` to `CaseResult` so gates can use frozen labels without reopening or guessing the dataset. Add `total_trials` to `SummaryStats` while keeping `total_cases` as the number of distinct Cases.

- [ ] **Step 5: Implement compatible result loading**

Implement:

```python
def load_run_result(path: str | Path) -> LoadedRunResult: ...
```

Accept either a run directory or its `results.json`, compute the exact file SHA-256, validate through `EvaluationRunResult`, migrate the legacy version field through the existing validator, and never rewrite the source file.

- [ ] **Step 6: Regenerate and verify the EvalCase JSON Schema**

Generate `schemas/eval_case.schema.json` from `EvalCase.model_json_schema()` using the existing test convention. Assert the schema contains optional Oracle Judge configuration and still forbids extra fields.

- [ ] **Step 7: Run focused and existing protocol tests**

Run: `.venv/bin/python -m pytest tests/test_phase2_protocols.py tests/test_result_loader.py tests/test_protocol_loader_validator.py tests/test_reporting_cli.py::test_results_from_before_report_metadata_upgrade_still_reload -q`

Expected: PASS.

- [ ] **Step 8: Commit the protocol boundary**

```bash
git add src/eval_framework/schema_base.py src/eval_framework/phase2_schemas.py src/eval_framework/result_loader.py src/eval_framework/schemas.py src/eval_framework/__init__.py schemas/eval_case.schema.json tests/conftest.py tests/test_phase2_protocols.py tests/test_result_loader.py
git commit -m "feat: add phase two evaluation protocols"
```

### Task 2: Isolated Multi-Trial Execution and Stability Metrics

**Files:**
- Create: `src/eval_framework/stability.py`
- Modify: `src/eval_framework/runner.py`
- Modify: `src/eval_framework/reporting.py`
- Modify: `src/eval_framework/adjudication.py`
- Modify: `src/eval_framework/cli.py`
- Create: `tests/test_multi_trial_stability.py`
- Modify: `tests/test_execution_scoring.py`
- Modify: `tests/test_reporting_cli.py`
- Modify: `tests/test_adjudication.py`

**Interfaces:**
- Consumes: `RunConfig.trials_per_case`, `_run_case(..., trial_id=...)`, and flattened `EvaluationRunResult.cases`.
- Produces: `OutputNormalizer` protocol with `__call__(case: CaseResult) -> dict[str, Any]`.
- Produces: `aggregate_stability(cases: Sequence[CaseResult], *, planned_trials: int, normalizer: OutputNormalizer | None = None) -> RunStability`.
- Produces: `nearest_rank(values: Sequence[int | float], percentile: float) -> float | None` using sorted index `ceil(percentile * N) - 1`.
- Produces: `canonical_observed_output(case: CaseResult) -> dict[str, Any]` and `observed_output_sha256(case: CaseResult, normalizer=None) -> str`.

- [ ] **Step 1: Write failing Trial isolation and metric tests**

Cover three Trials for one Case with unique Runtime objects and sessions, a first-Trial exception followed by success, stable PASS, mixed PASS/FAIL, all failure, `NOT_APPLICABLE`, and nearest-rank boundaries for empty, one-value, and five-value inputs.

```python
def test_each_trial_gets_a_new_runtime_session_and_result(dataset, provider):
    result = run_provider_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test", trials_per_case=3),
        provider,
    )
    assert [case.trial_id for case in result.cases] == [
        "trial_001", "trial_002", "trial_003"
    ]
    assert len(set(provider.runtime_ids)) == 3
    assert len({case.session_id for case in result.cases}) == 3


def test_pass_at_k_pass_power_k_and_percentiles_are_recomputable(case_results):
    stability = aggregate_stability(case_results, planned_trials=3)
    case = stability.cases[0]
    assert case.pass_at_k is True
    assert case.pass_power_k is False
    assert case.latency_p50_ms == 20
    assert case.latency_p95_ms == 30
```

- [ ] **Step 2: Run the multi-Trial tests and verify they fail**

Run: `.venv/bin/python -m pytest tests/test_multi_trial_stability.py -q`

Expected: FAIL because the Runner emits only `trial_001` and stability functions are missing.

- [ ] **Step 3: Implement deterministic stability aggregation**

For each distinct Case, preserve planned Trial order, count every quality and execution status, compute Trial pass rate over planned Trials, compute `pass_at_k` and `pass_power_k`, calculate P50/P95 with `nearest_rank`, and hash canonical observable outputs after removing run IDs, session IDs, event IDs, timestamps, and temporary paths.

- [ ] **Step 4: Execute sequential independent Trials in the Runner**

Change `run_provider_evaluation` to call `_run_case` once per configured Trial with IDs `trial_001` through `trial_NNN`. Call `provider.create_runtime(execution, session_id, scope)` for every invocation, preserve all results, add frozen Case labels to each result, and populate `EvaluationRunResult.stability` only after all Trials finish.

- [ ] **Step 5: Make summary denominators explicit**

Update `_summarize` so `total_cases` counts distinct Case IDs and `total_trials` counts results. Preserve `agent_case_pass_rate` as the legacy Trial-level strict pass rate, add stability fields for Case-level `pass@k` and `pass^k`, and ensure execution errors and `INCONCLUSIVE` count as non-PASS while `NOT_APPLICABLE` stays outside quality denominators.

- [ ] **Step 6: Prevent multi-Trial artifact collisions**

Write Case files to `cases/<case_id>/<trial_id>.json`. Keep evidence at `evidence/<case_id>/<trial_id>/...`. Update human report links, manifest sample counts, and `ReportPaths.case_files`. Update adjudication to resolve the new path first and then fall back to `cases/<case_id>.json` for legacy runs.

- [ ] **Step 7: Expose Trial count through the current run CLI**

Add `--trials` with default 1 and validation through `RunConfig`. Ensure the existing command path passes the value unchanged and the run manifest records the configured and actual Trial counts.

- [ ] **Step 8: Run focused execution, report, and adjudication tests**

Run: `.venv/bin/python -m pytest tests/test_multi_trial_stability.py tests/test_execution_scoring.py tests/test_reporting_cli.py tests/test_adjudication.py -q`

Expected: PASS with existing single-Trial assertions unchanged and new multi-Trial files collision-free.

- [ ] **Step 9: Commit multi-Trial execution**

```bash
git add src/eval_framework/stability.py src/eval_framework/runner.py src/eval_framework/reporting.py src/eval_framework/adjudication.py src/eval_framework/cli.py tests/test_multi_trial_stability.py tests/test_execution_scoring.py tests/test_reporting_cli.py tests/test_adjudication.py
git commit -m "feat: add isolated multi-trial evaluation"
```

### Task 3: Versioned DeepSeek Judge

**Files:**
- Create: `src/eval_framework/judge.py`
- Create: `src/eval_framework/judges/__init__.py`
- Create: `src/eval_framework/judges/deepseek.py`
- Create: `src/eval_framework/judge_rubrics/semantic_response_v1.json`
- Modify: `src/eval_framework/runner.py`
- Modify: `src/eval_framework/scoring.py`
- Modify: `src/eval_framework/dataset_validator.py`
- Modify: `src/eval_framework/cli.py`
- Modify: `src/eval_framework/__init__.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Create: `tests/support/judge_client.py`
- Create: `tests/test_judge.py`
- Create: `tests/test_deepseek_judge.py`
- Create: `tests/test_deepseek_judge_smoke.py`

**Interfaces:**
- Consumes: `JudgeRunConfig`, `OracleSpec.judge`, completed deterministic `CaseResult`, and an injected Judge client.
- Produces: runtime-checkable `JudgeClient` with `evaluate(request: JudgeRequest) -> object` and `metadata() -> dict[str, Any]`.
- Produces: `load_judge_rubric(path: str | Path) -> JudgeRubric`.
- Produces: `evaluate_trial_with_judge(case: EvalCase, result: CaseResult, config: JudgeRunConfig, client: JudgeClient, rubric: JudgeRubric) -> JudgeResult`.
- Produces: `resolve_quality_conclusion(deterministic: QualityConclusion, assertions: Sequence[AssertionResult], judge_spec: JudgeCaseSpec | None, judge: JudgeResult | None) -> QualityConclusion`.
- Updates: `run_provider_evaluation(..., judge_client: JudgeClient | None = None) -> EvaluationRunResult`.

- [ ] **Step 1: Write failing Judge boundary and precedence tests**

Test opt-in applicability, strict response validation, unique version metadata, reference facts staying out of Provider calls, transient retry only, no retry on low score or malformed output, secret redaction, and this precedence table:

```python
@pytest.mark.parametrize(
    ("deterministic", "critical_failed", "required", "judge_status", "judge_passed", "expected"),
    [
        ("FAIL", True, True, "COMPLETED", True, "FAIL"),
        ("PASS", False, True, "COMPLETED", False, "FAIL"),
        ("PASS", False, True, "MODEL_TIMEOUT", None, "INCONCLUSIVE"),
        ("PASS", False, False, "MODEL_TIMEOUT", None, "PASS"),
    ],
)
def test_judge_cannot_override_deterministic_precedence(
    deterministic,
    critical_failed,
    required,
    judge_status,
    judge_passed,
    expected,
):
    assertions = [assertion_result(critical=True, passed=not critical_failed)]
    spec = judge_case_spec(required=required)
    judge = judge_result(status=judge_status, passed=judge_passed)
    assert resolve_quality_conclusion(
        deterministic, assertions, spec, judge
    ) == expected
```

- [ ] **Step 2: Run Judge tests and verify they fail**

Run: `.venv/bin/python -m pytest tests/test_judge.py tests/test_deepseek_judge.py -q`

Expected: FAIL because Judge interfaces do not exist.

- [ ] **Step 3: Implement strict Rubric loading and request construction**

Load JSON with Pydantic, require file ID/version to match every applicable Case Judge spec, select only declared dimensions, truncate only explicitly bounded free text, summarize tool results without credentials, and omit full system prompts, hidden reasoning, unrelated Trials, and Oracle fields outside `reference_facts`.

- [ ] **Step 4: Implement Judge orchestration and quality precedence**

Validate every client response as a `JudgeResult` candidate, compute weighted Judge score with Decimal half-up rounding, retry only classified temporary invocation failures up to `max_retries`, record every `JudgeAttempt`, and call `resolve_quality_conclusion` without modifying deterministic assertion results or scores.

- [ ] **Step 5: Implement the DeepSeek client**

Use the OpenAI 2.x client with the configured DeepSeek base URL and Responses API. `DeepSeekJudgeClient.from_env()` must require `DEEPSEEK_JUDGE_API_KEY` and `DEEPSEEK_JUDGE_MODEL`, default the base URL to `https://api.deepseek.com`, set SDK retries to zero, expose only non-secret metadata, and map timeout, invocation, and malformed-output failures to Judge statuses.

- [ ] **Step 6: Wire Judge into Runner and CLI**

Add `--judge-config PATH` to `run`. Extend dataset validation so Case Rubric IDs, versions, dimensions, and reference facts are internally consistent before execution. Enabling Judge without a client, without a valid Rubric, or on a non-frozen formal benchmark must fail before the first Agent Runtime is created. Invoke Judge only after deterministic assertions and only for Cases with `oracle.judge`. Populate run-level `judge_metadata` with the model, Prompt, Rubric, output Schema, sampling configuration, and Rubric file SHA-256 even when no Case is applicable. Write Judge evidence later through Reporting; do not send Judge fields to Provider calls.

- [ ] **Step 7: Add explicit dependency and opt-in smoke test**

Declare `openai>=2.0,<3` directly in `pyproject.toml`. Add `.env.example` names without values. Mark the real smoke test and skip unless `RUN_DEEPSEEK_JUDGE_SMOKE=1`; the test must evaluate one minimal scripted Judge request and assert schema-valid output without logging credentials.

- [ ] **Step 8: Run Judge and answer-isolation tests**

Run: `.venv/bin/python -m pytest tests/test_judge.py tests/test_deepseek_judge.py tests/test_protocol_loader_validator.py tests/test_provider_architecture.py -q`

Expected: PASS and no network call.

- [ ] **Step 9: Commit Judge support**

```bash
git add src/eval_framework/judge.py src/eval_framework/judges src/eval_framework/judge_rubrics src/eval_framework/runner.py src/eval_framework/scoring.py src/eval_framework/dataset_validator.py src/eval_framework/cli.py src/eval_framework/__init__.py pyproject.toml .env.example tests/support/judge_client.py tests/test_judge.py tests/test_deepseek_judge.py tests/test_deepseek_judge_smoke.py
git commit -m "feat: add versioned DeepSeek judge"
```

### Task 4: Trace Timeline, Validation, and Reanalysis

**Files:**
- Create: `src/eval_framework/trace_analysis.py`
- Modify: `src/eval_framework/provider.py`
- Modify: `src/eval_framework/providers/mini_agent/provider.py`
- Modify: `src/eval_framework/runner.py`
- Modify: `src/eval_framework/cli.py`
- Modify: `src/eval_framework/reporting.py`
- Create: `tests/test_trace_analysis.py`
- Modify: `tests/test_provider_architecture.py`
- Modify: `tests/test_reporting_cli.py`

**Interfaces:**
- Consumes: `CaseResult.turn_results`, `CaseResult.trace_events`, assertion/Judge evidence references, and optional Provider rules.
- Produces: `TraceRule` protocol with `analyze(timeline: Sequence[NormalizedTraceEvent], case: CaseResult) -> Sequence[TraceIssue]`.
- Produces: `analyze_case_trace(case: CaseResult, rules: Sequence[TraceRule] = ()) -> TraceAnalysis`.
- Produces: `analyze_run(result: EvaluationRunResult, rules: Sequence[TraceRule] = ()) -> RunAnalysis`.
- Produces: `write_run_analysis(analysis: RunAnalysis, run_dir: str | Path) -> AnalysisPaths` without modifying `results.json`.

- [ ] **Step 1: Write failing timeline and evidence tests**

Cover module Trace without an Agent run ID, two-turn E2E events, duplicate IDs, explicit timestamp reversal, missing run association, unclosed generic lifecycle events, valid/invalid assertion evidence refs, and Provider rule findings.

```python
def test_two_turn_trace_keeps_turn_and_run_identity(two_turn_case_result):
    analysis = analyze_case_trace(two_turn_case_result)
    assert [(event.turn_index, event.agent_run_id) for event in analysis.timeline] == [
        (0, "run-confirm"),
        (1, "run-write"),
    ]


def test_missing_and_duplicate_events_are_observations_not_root_causes(
    duplicate_event_case_result,
):
    analysis = analyze_case_trace(duplicate_event_case_result)
    assert "OBSERVED_DUPLICATE_EVENT_ID" in {issue.code for issue in analysis.issues}
    assert all("root cause" not in issue.message.lower() for issue in analysis.issues)
```

- [ ] **Step 2: Run Trace tests and verify they fail**

Run: `.venv/bin/python -m pytest tests/test_trace_analysis.py -q`

Expected: FAIL because Trace analysis interfaces do not exist.

- [ ] **Step 3: Normalize Trace without dropping raw events**

Use `turn_results[*].events` when available to retain turn/run identity. For module-only `trace_events`, assign `turn_index=0`, `agent_run_id=None`, and evaluator evidence refs. Preserve source indices and raw event payloads in the normalized representation without changing raw Trace.

- [ ] **Step 4: Implement generic structural and lifecycle checks**

Detect duplicate IDs, timestamp reversal when comparable timestamps exist, broken turn/run association, missing terminal partners for generic request/start events, and evidence refs that do not resolve. Codes and messages must say `OBSERVED_*`, `EVIDENCE_*`, or `SUGGESTED_*`; do not use `ROOT_CAUSE` wording.

- [ ] **Step 5: Add optional Provider rules without breaking existing Providers**

Read `getattr(provider, "trace_rules", ())` rather than making the attribute mandatory for every existing fake Provider. Register mini_agent-specific rules only in its Provider package. Core code must contain no mini_agent event-name table beyond generic lifecycle vocabulary.

- [ ] **Step 6: Snapshot initial analysis and add the reanalysis command**

After `_run_case` builds a complete result, call `analyze_case_trace` and store the initial `trace_analysis`. Add `analyze --run-dir PATH`; it loads immutable results, writes `trace_analysis/<case_id>/<trial_id>.json` and `analysis.json`, and leaves the original result SHA-256 unchanged.

- [ ] **Step 7: Run Trace, Provider, and report tests**

Run: `.venv/bin/python -m pytest tests/test_trace_analysis.py tests/test_provider_architecture.py tests/test_reporting_cli.py -q`

Expected: PASS, including a test that hashes `results.json` before and after `analyze`.

- [ ] **Step 8: Commit Trace analysis**

```bash
git add src/eval_framework/trace_analysis.py src/eval_framework/provider.py src/eval_framework/providers/mini_agent/provider.py src/eval_framework/runner.py src/eval_framework/cli.py src/eval_framework/reporting.py tests/test_trace_analysis.py tests/test_provider_architecture.py tests/test_reporting_cli.py
git commit -m "feat: add trace timeline analysis"
```

### Task 5: Comparable Baseline Diff

**Files:**
- Create: `src/eval_framework/comparison.py`
- Modify: `src/eval_framework/cli.py`
- Modify: `src/eval_framework/__init__.py`
- Create: `tests/test_comparison.py`
- Modify: `tests/test_reporting_cli.py`

**Interfaces:**
- Consumes: two `LoadedRunResult` values from Task 1 and their immutable SHA-256 identities.
- Produces: `check_comparability(baseline: LoadedRunResult, candidate: LoadedRunResult) -> ComparabilityReport`.
- Produces: `compare_runs(baseline: LoadedRunResult, candidate: LoadedRunResult) -> ComparisonResult`.
- Produces: `write_comparison(result: ComparisonResult, output_dir: str | Path) -> ComparisonPaths`.

- [ ] **Step 1: Write failing comparability matrix tests**

Test identical inputs, non-frozen input, dataset hash, filters, execution type, Trial count, Capability Bundle, Provider ID, assertion registry, threshold, tool-profile map, Judge model/Prompt/Rubric/Schema/sampling fingerprint, and missing Case/Trial mismatches. Also verify differing Agent, Provider implementation, Agent model, and Agent Prompt versions remain allowed comparison dimensions.

- [ ] **Step 2: Run comparison tests and verify they fail**

Run: `.venv/bin/python -m pytest tests/test_comparison.py -q`

Expected: FAIL because comparison APIs do not exist.

- [ ] **Step 3: Implement strict comparability checks**

Return all mismatch reasons with stable codes rather than stopping at the first. Any required mismatch yields `INVALID_COMPARISON` and leaves all quality-delta collections empty. Compare only frozen full or equivalently filtered runs.

- [ ] **Step 4: Implement Trial and Case alignment**

Align by `(case_id, trial_id)` first, then aggregate by `case_id`. Classify newly failed, fixed, persistently failed, new/recovered execution errors, newly unstable, stability improved, zero-tolerance candidates, Judge dimension deltas, latency deltas, Token deltas, and missing/extra Trials. Store both source SHA-256 values and `comparison_version`.

- [ ] **Step 5: Add machine and Markdown outputs**

Write `comparison.json` from `ComparisonResult` and a compact `comparison.md` that starts with comparability status, then regression/fix/stability/safety/performance sections. Markdown is not a stable API and must be derived only from the structured result.

- [ ] **Step 6: Add the compare CLI**

Implement `compare --baseline PATH --candidate PATH --output-dir PATH`. Return 0 for a valid comparison even when regressions exist, 2 for invalid comparison/input, and 3 for evaluator errors. Gate evaluation, not compare, decides whether regressions block release.

- [ ] **Step 7: Run comparison and CLI tests**

Run: `.venv/bin/python -m pytest tests/test_comparison.py tests/test_reporting_cli.py -q`

Expected: PASS and both output files reload from disk.

- [ ] **Step 8: Commit baseline comparison**

```bash
git add src/eval_framework/comparison.py src/eval_framework/cli.py src/eval_framework/__init__.py tests/test_comparison.py tests/test_reporting_cli.py
git commit -m "feat: add reproducible baseline comparison"
```

### Task 6: Versioned Local Release Gates

**Files:**
- Create: `src/eval_framework/gating.py`
- Create: `policies/release_gate.example.json`
- Modify: `src/eval_framework/cli.py`
- Modify: `src/eval_framework/__init__.py`
- Create: `tests/test_gating.py`
- Modify: `tests/test_reporting_cli.py`

**Interfaces:**
- Consumes: candidate `LoadedRunResult`, strict `GatePolicy`, and optional `ComparisonResult`.
- Produces: `load_gate_policy(path: str | Path) -> GatePolicy`.
- Produces: `evaluate_gate(candidate: LoadedRunResult, policy: GatePolicy, comparison: ComparisonResult | None = None) -> GateResult`.
- Produces: `write_gate_result(result: GateResult, output_dir: str | Path) -> GatePaths`.

- [ ] **Step 1: Write failing Policy validation and masking tests**

Cover invalid thresholds, unknown metrics, unknown labels/assertions, minimum execution rate, minimum strict pass rate, minimum `pass^k`, maximum regressions, maximum unstable Cases, absolute and relative latency/Token limits, required Judge dimensions, evidence-review rules, and zero-tolerance masking attempts.

```python
def test_zero_tolerance_failure_blocks_despite_judge_and_other_fixes(
    candidate_with_safety_failure,
    permissive_comparison,
    zero_tolerance_policy,
):
    result = evaluate_gate(
        candidate_with_safety_failure,
        zero_tolerance_policy,
        permissive_comparison,
    )
    assert result.conclusion == "FAIL"
    assert any(check.code == "ZERO_TOLERANCE_ASSERTION_FAILED" for check in result.checks)


def test_missing_required_evidence_requires_review(
    candidate_without_trace,
    evidence_policy,
):
    result = evaluate_gate(candidate_without_trace, evidence_policy)
    assert result.conclusion == "REVIEW_REQUIRED"
```

- [ ] **Step 2: Run gate tests and verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gating.py -q`

Expected: FAIL because Gate Policy and evaluation do not exist.

- [ ] **Step 3: Implement strict Policy loading and reference validation**

Validate numeric ranges and require explicit lists for core labels, zero-tolerance labels, and zero-tolerance assertion names. Before evaluation, verify every configured label/assertion/metric exists in the candidate evidence. Treat invalid references as Policy input errors, not Gate `FAIL`.

- [ ] **Step 4: Implement gate evaluation with fixed precedence**

Use this order:

1. invalid required comparison → `INVALID_COMPARISON`;
2. missing evidence, insufficient percentile sample, or explicit review rule → `REVIEW_REQUIRED`;
3. any zero-tolerance or configured threshold violation → `FAIL`;
4. otherwise → `PASS`.

Evaluate zero-tolerance across every Trial. Never average away a failed critical assertion, safety label, or configured zero-tolerance assertion.

- [ ] **Step 5: Add auditable gate outputs**

Each `GateCheckResult` records the Policy field, operator, threshold, actual value, pass/fail/review state, and evidence refs. Save `gate.json` with the candidate and comparison SHA-256 values and render `gate.md` from that model.

- [ ] **Step 6: Add the gate CLI and stable exit codes**

Implement `gate --candidate PATH [--comparison PATH] --policy PATH --output-dir PATH`. Return 0 for `PASS`, 2 for invalid input or `INVALID_COMPARISON`, 3 for evaluator error, 4 for `FAIL`, and 5 for `REVIEW_REQUIRED`.

- [ ] **Step 7: Run gate and CLI tests**

Run: `.venv/bin/python -m pytest tests/test_gating.py tests/test_reporting_cli.py -q`

Expected: PASS with exact exit-code assertions and reloadable output.

- [ ] **Step 8: Commit local gates**

```bash
git add src/eval_framework/gating.py policies/release_gate.example.json src/eval_framework/cli.py src/eval_framework/__init__.py tests/test_gating.py tests/test_reporting_cli.py
git commit -m "feat: add versioned local release gates"
```

### Task 7: Phase-Two Reporting, Documentation, and End-to-End Verification

**Files:**
- Modify: `src/eval_framework/reporting.py`
- Modify: `src/eval_framework/cli.py`
- Modify: `src/eval_framework/__init__.py`
- Modify: `README.md`
- Modify: `docs/evaluation_report_spec.md`
- Modify: `tests/test_reporting_cli.py`
- Create: `tests/test_phase2_end_to_end.py`

**Interfaces:**
- Consumes: all phase-two structured results and paths from Tasks 1–6.
- Produces: a human report with separate deterministic, Judge, Trace, Trial stability, comparison, and gate sections; machine files remain the stable APIs.
- Produces: documented Python API exports for Judge injection, `analyze_run`, `compare_runs`, and `evaluate_gate`.

- [ ] **Step 1: Write the failing phase-two report and end-to-end tests**

Create a two-Case, three-Trial offline run with one unstable Case, one Judge-scored Case, one Trace observation, a compatible baseline, and a blocking Gate Policy. Assert every machine artifact reloads, every Markdown link exists, and the report never presents Judge score as deterministic success or a Trace suggestion as root cause.

- [ ] **Step 2: Run the integration tests and verify they fail**

Run: `.venv/bin/python -m pytest tests/test_phase2_end_to_end.py tests/test_reporting_cli.py -q`

Expected: FAIL because the final report and CLI integration are incomplete.

- [ ] **Step 3: Extend report and manifest payloads**

Add distinct Case and Trial counts, Judge applicability/status/version, `pass@k`, `pass^k`, Trial pass rate, output volatility, P50/P95 with sample sufficiency, Trace observation counts, and links to Judge/Trace/stability artifacts. Preserve current first-screen verdict behavior and clearly label provisional runs as ineligible for baselines or release PASS.

- [ ] **Step 4: Write Judge and Trace evidence files**

For each Trial, write `judge/<case_id>/<trial_id>.json` only when Judge was applicable and `trace_analysis/<case_id>/<trial_id>.json` when analysis exists. Add both to `ReportPaths.evidence_files`; never duplicate credentials or full prompts.

- [ ] **Step 5: Finalize public API and usage documentation**

Document installation, direct OpenAI SDK dependency, multi-Trial run, DeepSeek Judge environment, offline defaults, `analyze`, `compare`, `gate`, Policy semantics, exit codes, backward compatibility, and the explicit absence of CI workflows. Update `docs/evaluation_report_spec.md` from phase-one-only language to the implemented phase-two contract.

- [ ] **Step 6: Run all focused phase-two tests**

Run: `.venv/bin/python -m pytest tests/test_phase2_protocols.py tests/test_result_loader.py tests/test_multi_trial_stability.py tests/test_judge.py tests/test_deepseek_judge.py tests/test_trace_analysis.py tests/test_comparison.py tests/test_gating.py tests/test_phase2_end_to_end.py -q`

Expected: PASS with the real DeepSeek smoke skipped.

- [ ] **Step 7: Run the complete offline suite**

Run: `.venv/bin/python -m pytest -q`

Expected: PASS; `tests/test_deepseek_judge_smoke.py` and existing paid smoke tests are skipped unless explicitly enabled.

- [ ] **Step 8: Run Ruff**

Run: `.venv/bin/python -m ruff check .`

Expected: PASS with no diagnostics.

- [ ] **Step 9: Verify generated and saved artifacts**

Run one framework-self-test fixture with `--trials 3`, then run `analyze`, compare it with a copied compatible baseline fixture, and apply `policies/release_gate.example.json`. Revalidate every JSON file with its Pydantic model, verify all report links exist, and confirm the source `results.json` SHA-256 is unchanged after downstream commands.

- [ ] **Step 10: Commit documentation and integration**

```bash
git add src/eval_framework/reporting.py src/eval_framework/cli.py src/eval_framework/__init__.py README.md docs/evaluation_report_spec.md tests/test_reporting_cli.py tests/test_phase2_end_to_end.py
git commit -m "docs: complete phase two evaluator workflow"
```
