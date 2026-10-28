# Full Generator Comparison Implementation Plan

> Native execution via executing-plans; independent fresh-context review before paid full run and final report. User has opted out of repeated approval. No commits/pushes.

**Goal:** Generate all847 mini_agent slots using both backends and deliver audited comparison.
**Architecture:** Metadata-only plan from historical full suite; source-bound context and strict candidate/semantic validators; reusable controlled provider and DeepEval adapter; resumable paired concurrent runner; stratified reports and independent AI review.
**Tech Stack:** Python3.11, Pydantic/JSONSchema, httpx, DeepEval4.3.2.
**Spec:** docs/superpowers/specs/2026-10-28-full-generator-comparison-design.md

## Global constraints
No historical candidate Oracle in prompts; unknown outcomes remain absent; same settings/budget/validator; 8 workers, alternating pair order,3 attempts; preserve raw failures; no approval/freeze.

## Review focus
- Missing-parameter enum is not case-specific Oracle evidence.
- Wrong parameter dimension may pass a whole-object JSONSchema check.
- Unsupported/unknown slots must not leak guessed assertions through input fields.
- Resume after interruption must neither erase rejected attempts nor rebill completed work.
- Concurrent completion order must not influence dedup acceptance or comparison denominators.

## Tasks
- [ ] Task1: plan/context/candidate protocol. RED tests for847 metadata slots, no seed payload exposure, stale source refusal, input-only reclassification and unknown Oracle rejection; implement full_comparison/plan.py and validation.py.
- [ ] Task2: source-grounded validation. RED tests for dimension mismatch, wrong static assertion, invented result/event, wrong intent params and structured duplicate semantics; implement bounded semantic checks and compile accepted candidates.
- [ ] Task3: backend/runner. RED tests for native strict extras, complete paired denominator, exhausted slots continue, resume retains all attempts, per-worker settings and source equality; implement backend.py, runner.py and scripts/compare_full_generators.py.
- [ ] Task4: offline tests and independent review; fix material findings before paid full run.
- [ ] Task5: run all847 paired slots; audit coverage/usage/settings/history. Independent AI semantic review of behavior candidates; source-check all static definitions. Report overall and per-target results with limitations and concrete artifact links.
