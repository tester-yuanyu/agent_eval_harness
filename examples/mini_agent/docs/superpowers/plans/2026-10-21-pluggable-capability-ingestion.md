# Pluggable Capability Ingestion Implementation Plan

> Execute inline using executing-plans and test-driven-development. User confirmed implementation in this task; preserve existing uncommitted work.

**Goal:** Generate evaluation-compatible snapshots for different Agents using replaceable collectors and constrained LLM extraction.

**Architecture:** Add a source-backed input document and ingestion service around the existing compiler. Keep provider loading explicit and candidate claims untrusted. Ship a zero-tool conversation profile and standalone wheel.

**Tech Stack:** Python 3.11+, existing Pydantic/PyYAML, pytest, setuptools.

**Spec:** `docs/superpowers/specs/2026-10-21-pluggable-capability-ingestion-design.md`.

## Global Constraints

- Preserve Snapshot 3.0 and current adapter API; reports are outside bundle.
- No embedded model SDK, paid calls, remote publishing or external business mutations.
- Never load code from a candidate file; explicit local plugin selection is trusted code execution.
- Source hashes do not prove business behavior; configured and observed are distinct.
- No fixed 7-module/7-intent topology; unknown information remains unknown.

## Review Focus

- Candidate attempts to promote support or register a tool without runtime configuration.
- Conflicting schemas, versions, duplicate IDs and source references.
- File path traversal, symlink escape, stale hashes, oversized files and request tampering.
- Profile/Agent incompatibility, zero-tool chains and missing evidence.
- Independent wheel assets, output collisions and deterministic report hashes.

## Tasks

- [x] 1. Add `ingestion/models.py`, `sources.py`, `providers.py`: strict FactDocument, source validation, explicit collector/extractor protocols and existing Adapter wrapper. RED/GREEN tests for duplicates, stale/escaped sources and plugin type errors.
- [x] 2. Add `ingestion/reconcile.py`, `service.py`: configured/candidate trust rules, conflict rejection, immutable delivery with manifest and diagnostics. RED/GREEN tests for candidate promotion, unknowns, conflicts and output collisions.
- [x] 3. Add packaged extraction instructions/profile, `ingestion/cli.py`, Kit `__main__.py`: prepare/extract/export/schema commands and delegate validate/resolve/diff to existing CLI. Test offline request-to-export and explicit plugin path.
- [x] 4. Add runnable customer-service example and mini_agent collector, documentation and standalone build script. Test zero-tool scope/chain and mini_agent parity, wheel outside repo, Builder trusted loading.
- [x] 5. Run repository tests/lint, independent review, generate example deliveries and record verification.

## Execution ledger

- Baseline: 295 passed, 1 paid smoke skipped; pre-existing dirty files recorded before edits.
- Existing user confirmation authorizes the proposed architecture and implementation; continue without another approval gate.

- Tasks 1–4: completed with RED→GREEN tests for input contracts, provenance, explicit plugins, candidate trust handling, immutable delivery, CLI, conversation profile and packaging.
- Full suite after independent review fixes: **321 passed, 1 skipped** (paid OpenAI smoke); `ruff check .` passed.
- Independent review: request re-import missed per-file limit. Reproduced with a 1,000,001-byte source, then enforced the limit before extractor execution; regression passed.
- Review also found source kind could be relabeled without changing path/hash. Treated as a provenance integrity defect; reproduced and fixed by binding path, hash AND kind. No review findings remain deferred.
- Final review scope exclusions match the design: behavior truth, real model-provider integration and hostile trusted-plugin sandboxing are not claimed. Runtime verification belongs to Evaluator; plugins are explicitly trusted local code.
- Generated `exports/customer_service_v1/` (1 module, 1 business intent, 0 tools, 1 scope, 1 chain) and `exports/mini_agent_portable_v1/` (7 modules, 7 intents, 6 tools, 5 scopes, 3 chains).
- Both bundles passed Builder's actual trusted-profile loader, using Builder source with the Evaluator dependency environment. This is ingestion compatibility, not a full Builder/Evaluator assessment run.
- MiniAgent bundle hash remains `215a9a3a445c8857f3bdd8dbecba935ce646bd8c784f16ecfc4a5da6042cce3c`; customer bundle hash is `a72639d1aa8dea275b2898e6cfa52fbe6f4d66879fbe002e3cdad5d6fe3a5329`.
- Verified all 22 customer and 55 MiniAgent manifest file digests. Generated an offline extraction request at `exports/customer_service_request_v1.json`.
- Initial independent wheel installation passed in a fresh environment outside the checkout, with neither minimal_agent nor openai installed: collect/export/validate/resolve/prepare/candidate import and Agent execution. Final rebuilt wheel passed all eight checks; results are recorded in `exports/standalone_dist/verification.json`. Wheel SHA256: `86f290b18f0b1f160824d6b89861010a09c8d682fcba88219b351d9fcac33ff8`.
