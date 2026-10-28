# Local Langfuse Automatic Delivery Implementation Plan

> **For agentic workers:** Use TDD and independent review. The user has approved execution; continue without another planning approval.

**Goal:** Run Langfuse locally and automatically deliver a report plus a scoped native dashboard after every evaluation.

**Architecture:** Inspect retains execution and scoring. A post-run delivery adapter reads immutable run/intake/invalid artifacts, uses the existing Langfuse exporter and native dashboard API, and records delivery independently of evaluation outcome. Local deployment and CLI integration are independent of exporter/dashboard implementation and may proceed concurrently with separate file ownership.

**Tech Stack:** Python 3.11, Inspect, Langfuse SDK 5.0.2, official Docker Compose, Docker Desktop on Apple Silicon.

**Spec:** `docs/superpowers/specs/2026-10-24-local-langfuse-auto-delivery-design.md`

## Global Constraints

- Preserve existing migration work and symlinked extension sources; work on the existing `codex/inspect-ai-migration` checkout. No broad staging or commits of unrelated changes.
- Do not recalculate formal metrics, rerun Agents to populate UI, fabricate blocked Trials, or silently contact Cloud.
- Automatic delivery uses only an explicitly enabled loopback configuration, never the existing `.env.langfuse` Cloud credentials.
- Preserve immutable result/native-log hashes and historical Cloud export receipts.
- Local service failure cannot change evaluation verdicts or exit codes.
- Default content mode excludes business input/output. Credentials stay in ignored, permission-restricted local files.
- Run tests/lint with the extension's `pyproject.toml`.

## Review Focus

1. All-blocked and invalid input have no results.json: create status delivery without fake scores.
2. A successful partition followed by a failed one retains the partial-intake view.
3. Uncertain observation ingestion must not cause blind replay; preserve checkpoints.
4. Cloud environment credentials or redirect responses must not escape the local target.
5. Repeated publishing must not duplicate observations, widgets or dashboards, or change formal files.

## Task 1: Local delivery adapter and native dashboard

**Files:** Create `src/eval_framework/local_delivery.py` and supporting small modules as needed; modify `observability.py`; create `tests/test_local_delivery.py`; extend `tests/test_langfuse_export.py`.

**Interfaces:** `finalize_delivery(source: str | Path, *, config_path: str | Path | None = None, retry_pending: bool = True) -> dict`. Source is a saved run directory, intake JSON path, or invalid-run directory/file. No configuration returns `DISABLED` without network or report changes. Explicit config path comes from CLI, then `AGENT_EVALUATOR_LOCAL_LANGFUSE_CONFIG`, then cwd `.env.langfuse.local.json` if present. Config contains `enabled`, `base_url`, `project_id`, `public_key`, `secret_key`, optional `include_content` (false), and optional `state_dir`. Return status plus report/dashboard links when available, with sanitized errors on failure.

- [x] Add failing tests for local-only config, Cloud exclusion, immutable results, legacy receipt preservation, pending/uncertain retry, idempotent dashboards, and blocked/invalid status sources.
- [x] Extend the existing exporter with optional target identity and target-specific receipt path; preserve old call defaults. Do not manipulate global environment for local requests.
- [x] Implement result delivery plus native widgets using only saved scalars. Candidate dashboard separates partitions and includes saved intake counts/provisional/gate status. Invalid/blocked sources have descriptive status without quality scores.
- [x] Persist sanitized delivery JSON and human-readable report/index with links. A pending queue is attempted on later delivery calls and explicit retries, with bounded network time.
- [x] Run focused tests and Ruff. Report RED/GREEN evidence and modified files.

## Task 2: Automatic CLI integration

**Files:** Modify `src/eval_framework/cli.py`; create `tests/test_local_delivery_cli.py`; documentation updates later by root.

**Consumes:** Task 1 `finalize_delivery`; it returns `DISABLED`, successful, or pending/error status without changing evaluation outcome.

- [x] Add failing CLI tests: normal run, candidate partial/all blocked, partition error, preflight invalid, delivery failure, and explicit saved-result sync.
- [x] Add optional `--local-langfuse-config` to run and `sync-local --source PATH [--local-langfuse-config PATH]` for no-rerun delivery.
- [x] Call delivery after authoritative files are saved. Candidate sync occurs after final intake write, outside partition execution exception handling. Local sync errors preserve original CLI exit codes and cannot append a fake execution error.
- [x] Include delivery links/state in CLI JSON while preserving existing fields. Disabled config leaves current behavior compatible.
- [x] Run focused CLI tests and Ruff.

## Task 3: Local deployment and current-run acceptance

**Files:** Create `scripts/local_langfuse.py` and deployment README/config assets; local secrets `.env.langfuse.local.json` and ignored `artifacts/local_langfuse_20261024/`.

- [x] Install vendor-signed Docker Desktop from official Apple Silicon image; user handles agreement/system prompts if shown.
- [x] Pin official compose source and image versions/digests; generate random secrets and a local admin/project/API keys through supported headless initialization. Bind exposed services to 127.0.0.1, persist data, disable available telemetry, avoid Cloud defaults.
- [x] Start/verify health; publish the existing Nanobot v3 intake through `sync-local`, then verify accepted counts/saved values and open native dashboard in browser.
- [x] Repeat sync to verify no duplicate observations/widgets and unchanged formal result/native log hashes. Verify automatic delivery with an isolated local fixture run, plus service-down behavior covered by tests.
- [x] Run full extension tests/lint, fresh independent review, and update docs with actual URLs, local startup/retry instructions, and delivery status.

## Progress and rulings

- 2026-10-24: User approved execution. Existing dirty migration tree is the required working state; copying a clean HEAD to a new worktree would omit current business sources. Preserve it and use scoped before/after snapshots for review.
- 2026-10-24: Installation/download and source code work are independent; parallel workers own disjoint files. No further design confirmation is needed.

- 2026-10-24 acceptance: 558 passed / 2 paid-smoke skipped; Ruff/format passed. Local Langfuse :3300, native UI/readback/idempotency/persistent-volume restart and both CLI automatic paths verified. Evidence: artifacts/local_langfuse_20261024/README.md.
