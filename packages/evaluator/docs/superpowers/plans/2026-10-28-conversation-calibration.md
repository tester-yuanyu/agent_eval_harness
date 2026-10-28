# Conversation Judge pilot and calibration plan

> **For agentic workers:** Use superpowers:executing-plans inline, then one independent review.

**Goal:** Verify the real Judge pipeline, run repeated evaluations of 24 reviewable conversations, and prepare honest human calibration evidence.

**Architecture:** Existing Inspect business pipeline handles a real mini_agent/DeepSeek/SQLite pilot. A native Inspect Task scores fixed, explicitly synthetic conversation fixtures using the existing diagnostic adapter; Inspect owns repetitions and stored scores. Langfuse owns review editing; proposed labels are not human gold.

**Tech Stack:** Existing Inspect, DeepEval 4.2.9, DeepSeek model transport and local Langfuse SDK.

**Spec:** User-approved 3-step next action; `docs/conversation_completeness.md`; root/extension AGENTS.md.

## Constraints and decisions

- User approved using the existing DeepSeek account, through independent Judge env settings. Never print or export credentials.
- No additional production Runner/scoring engine, no changes to diagnostic thresholds, no changes to existing baselines.
- Fixed dialogue fixtures assess the Judge, not live Agent performance. Pilot and calibration have separate artifacts and labels.
- Draft expectations remain `PENDING_HUMAN_REVIEW`; no accuracy claim or gate eligibility until genuine human annotations exist.
- Existing symlink migration remains intact; work is performed in place, with a temporary backup.
- 24 cases, 3 repetitions each; first a small preflight to catch API errors. Record all errors and planned denominators.

## Tasks

- [x] Configure independent Judge env; run real multi-turn Agent/Judge pilot through existing Suite and local Langfuse.
- [x] Author 24 fixed Chinese conversations and proposed effective-intention judgments covering fulfilled, omitted, cancelled, changed, business evidence conflicts, injection and unavailable inputs.
- [x] Test the calibration dataset and native Task for Oracle isolation, actual-turn inputs, unknown preservation, repeat completeness and immutable projections.
- [x] Implement narrow native Inspect calibration example/CLI and stored-result analysis. Persist metrics only once, separate draft-label comparison from repeatability.
- [x] Execute real model evaluation (24 × 3); inspect repeated-score ranges and disagreements rather than tuning the corpus to the output.
- [x] Publish synthetic conversations and saved scores to local Langfuse, create review queue with draft-label warnings; read back scores/items.
- [x] Run appropriate checks and independent review. Write the empirical report and human review handoff; keep Gate disabled.

## Evidence and deviations

- Native run `UdxvVxV6qz55nJczuTWa8F`: 72 trials, 60 numeric, 9 ERROR and 3 NOT_APPLICABLE. CC-009 cancellation repeats 0.5 / 0.5 / 1.0. Labels were not changed.
- Live pilot `eval_run_c0da90ab7ecd4a17a23a4130a832a356`: three business FAIL outcomes; two open-conversation diagnostic errors and one real Judge score of 0.5. This verifies plumbing and reveals fixture/Agent behavior, not successful Agent release acceptance.
- Preflight exposed OpenAI SDK compatibility and missing service-prefix issues; fixed real transport construction and dependency ranges. mini_agent metadata only widened, no Agent logic changed.
- Local Langfuse verified 24 pending items and 132 persisted status/numeric scores. SDK batch acceptance response required a narrow resume path for stable-ID score upserts; accepted observations were not resent. Uncertain observation/queue operations still require explicit reconciliation.
- Independent read-only review approved the scoped implementation and separately the recovery fix. Full checks and details are in `docs/conversation_calibration_20261028.md`.
- Human annotation remains pending. Calibration-specific human snapshot import, Gate thresholds and Agent runtime fixes are subsequent work, not claimed complete here.

## Review focus

- Any label included in Judge messages or Sample target.
- Missing/failed repetitions silently excluded from statistics.
- Pending labels presented as human-approved accuracy.
- Stored scores re-evaluated or recomputed by report/export.
- Synthetic Judge fixtures mistaken for live Agent capability evidence.
