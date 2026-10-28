# Generator Comparison Implementation Plan

> Native execution in this session, following executing-plans; independent reviewer at the end. User has opted out of repeated approval questions. No commits/pushes.

**Goal:** Run and deliver a fair, auditable two-round Direct/DeepEval comparison.
**Architecture:** Reuse existing source preflight and slot rules; extract the shared slot task. New direct synthesizer and shared experiment loop use identical acceptance, deduplication and retry policies. Dedicated script controls provider settings, call logging and run ordering.
**Tech Stack:** Python 3.11, existing Pydantic/JSON Schema, httpx, DeepEval 4.3.2.
**Spec:** docs/superpowers/specs/2026-10-28-generator-comparison-design.md

## Constraints and review focus

- No seed oracle copying, absent contract expectations remain absent; old datasets untouched.
- Bad JSON/extra Oracle in input-only results must fail; all failed attempts retained.
- Unknown/missing outcomes, never-attempted slots and denominator selection cannot inflate pass rate.
- Provider settings must match actual wire requests; no hidden API retries.
- Dedup state resets per arm; one exhausted slot must not erase or stop later slots.

## Task 1: Shared input and direct generation

Files: src/dataset_builder/deepeval_generation.py, new src/dataset_builder/generation_comparison.py, tests/test_generation_comparison.py.
- [x] RED: direct valid Candidate; strict input-only rejection of extra Oracle; malformed JSON; equal shared slot instruction.
- [x] GREEN: extract build_slot_task unchanged; implement DirectSlotSynthesizer using injected complete(prompt,json_mode) and strict JSON parsing.

## Task 2: Experiment execution and metrics

Files: generation_comparison.py; scripts/compare_generators.py; tests/test_generation_comparison.py.
- [x] RED: first-pass denominator, exhaustion continues, duplicate retries preserve raw, explicit parameter payload, token/cache totals.
- [x] GREEN: common arm loop and metrics; controlled native SDK wrapper; timestamped isolated workspaces, record sources and history hashes.
- [x] Run targeted and full pytest; independent code review; resolve important findings before paid runs.

## Task 3: Live comparison and report

Files: new workspaces/generator_comparison_<timestamp>/*, docs/GENERATOR_COMPARISON.md.
- [x] Run two pairs AB / BA, preserving every attempt and unsuccessful run.
- [x] Validate supported subsets and source/settings equivalence; read all final inputs/oracles in a blinded packet.
- [x] Publish comparison table, limits, recommendation and artifact links; verify history and credentials; no freeze.
