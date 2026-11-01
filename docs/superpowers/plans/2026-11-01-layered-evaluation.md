# Layered evaluation implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for independent owned files; root integrates and verifies.

**Goal:** executable module/chain/E2E suites with scoped deterministic and GEval scores, verified Langfuse delivery, and a bounded τ integration.

**Architecture:** extend the existing Inspect/DeepEval Harness. Keep frozen v1 assets and trials unchanged. Real modules, real Agent trials, and diagnostic Judge observations are distinct populations.

**Tech Stack:** Python, Inspect 0.3.280, DeepEval 4.2.9, Langfuse 5.0.2, external nanobot SDK.

**Spec:** `docs/superpowers/specs/2026-11-01-layered-evaluation-design.md`.

## Global constraints

- Source Agent repositories are read-only. Work in the existing dedicated checkout.
- No oracle or expected/checkpoint values in Agent requests.
- Default tests/demo make no paid requests or hosted uploads; explicit live delivery is authorized.
- Preserve historical files and results. Missing evidence/failed Judge calls are never successful scores.
- No claim of human calibration without independent completed human annotations.

## Review focus

- Malformed checkpoint selectors or missing snapshots must not silently pass.
- Module calls are executed by real nanobot code; reference execution is never labeled real.
- Event scores resolve to the correct child observation and preserve idempotent export IDs.
- Failed/missing Judge responses and N/A recovery cases do not inflate scoring coverage.
- Mutable runtime, dataset, rubric or score versions cannot silently resume a prior run.

## Task 1: Three executable layers

Owner: dataset/module implementer. Files: `tasks.py`, `module_runtime.py`, `module_worker.py`, `data/benchmarks/file-tools-v2/`, new focused tests. Implement validated task fields, isolated real-module execution, three-layer generation and private execution projection. Test malformed inputs, expected-answer separation, real module error semantics, immutable generation, split/family accounting. Deliver the interfaces in the spec.

## Task 2: Scoped deterministic scoring and traces

Owner: trajectory implementer. Files: `trajectory.py`, `nanobot_worker.py`, `langfuse_export.py`, new focused tests. Capture per-tool before/after state, validate/evaluate declared checkpoints, score individual events with DeepEval BaseMetric, link scores to actual child observations. Test failed intermediate state despite correct final state, missing evidence, valid alternate paths, invalid links and exported score IDs.

## Task 3: GEval diagnostics and quantification

Owner: Judge implementer. Files: `judging.py`, `judge_calibration.py`, rubric data, new focused tests. Implement the three fixed rubric dimensions using existing real Judge adapter. Test applicability, failed calls, missing evidence, scope association, repetition summaries, label joining and no fabricated human agreement. No paid worker calls; root performs live integration.

## Task 4: Integrate and run

Owner: coordinator. Files: `runner.py`, `metrics.py`, `cli.py`, `regrade.py`, reports and scripts. Add layered execution routing, scoped metric identities, explicit Judge/regrade commands, separate population summaries. Run focused tests then evaluator regressions and root integration checks. Execute real suites and GEval; preserve immutable result provenance. Export and verify Langfuse scores.

## Task 5: τ-family plugin and final audit

After core integration, inspect and pin official source; implement a bounded domain adapter/pilot preserving official semantics. Document concrete blockers if upstream/model compatibility prevents completion. Independently review code and delivered artifacts. Update architecture and a seven-question resolution ledger with evidence and unresolved work.

## Execution ledger

- Plan accepted by the user's explicit request to execute the previously proposed sequence. No additional approval round is needed.
- Existing checkout was clean at start; continue on its dedicated `codex/` branch to retain installed environments and authorized original-repository boundaries.

- Frozen file-tools-v2 contains 420 instances across program modules, critical chains and E2E; model-decisions-v1 adds 24 one-decision instances. Combined coverage is 444 instances / 112 families, including parameter variants.
- Completed 612 original executions: program modules 60/60 PASS, model decisions 72/72, chains 151/180, E2E 273/300. Chain repetitions yielded 43/60 tasks passing all three trials. Deterministic v2.1 regrades preserve source observations and are not new Agent executions.
- Completed GEval primary review: 3,274 applicable / 3,273 scored / 1 missing-score response error. Stability review adds 69 evidence items × 2 reviews, with mean range 0.031884 and maximum 0.4. All Judge scores remain diagnostic pending independent human calibration.
- Delivered 36 blank, independently labelable calibration rows (12 per dimension), without Judge predictions. Public evidence removes machine-specific temporary path prefixes only; original local evidence remains unchanged.
- Completed official τ²-bench v1.0.1 retail task 0, one real nanobot trial, official reward 1.0, evidence complete. Its 23 Langfuse observations and 2 scores passed service-side readback. This pilot is separate from the file/decision totals and is not a full benchmark reproduction.
- Independent reviews found and fixed exact module-output checks, typed decision parameters, recovery sequencing and formal-failure precedence. Evaluator regression: 843 passed / 2 explicit live smokes skipped; root integration: 46 passed before final report additions; optional τ offline validation: 11 passed. Subsequent changed-scope tests are recorded in reports/file-tools-v2/verification.json.
- Minimal core environment passed dependency checks and a 5-case offline integration demo. Wheel build included the new runtime/Judge/τ modules; 1,172 imported historical artifacts/fixtures were verified unchanged.
- Langfuse UI was inspected on a real model-decision node with deterministic and GEval scores plus its Judge child. The public screenshot omits account email. Local report browser preview was blocked by browser URL policy; static HTML/JSON/link checks were performed and are not described as browser validation.

- Final cloud verification: all six exported runs VERIFIED. Chains: 180 trials / 4,139 observations / 4,641 scores; E2E: 300 trials / 5,551 observations / 5,789 scores. Observation totals include 179 / 479 separately receipted original-metadata evidence children, added because the cloud metadata API parses JSON strings. Verification requires both original structured content and exact encoded bytes/Hash/parent binding; no Agent execution or Judge scoring was added. Original results, spans and original export receipts remain unchanged.
- Final checks: full evaluator 864 passed / 2 explicit paid smoke tests skipped, root integration 56 passed, latest metadata/evidence/scoped regression 28 passed. Ruff passed using evaluator pyproject configuration. Final wheel was rebuilt and installed offline in the isolated minimal environment; installed-code identity normalization and dependency checks passed, with a 5-case offline demo verified separately from Agent performance.
- Delivered static portfolio, independent blank calibration starter, Langfuse screenshot, real failure case and seven-question remaining-work ledger. Human labels, calibrated thresholds, wider product/domain coverage, one Judge response-format recovery and full τ reproduction are explicitly not claimed. No GitHub push or public website publication performed.
