# Migration ledger

Plan: docs/superpowers/plans/2026-10-28-monorepo-migration.md

- User authorized local creation, integration and autonomous verification; no GitHub remote/push requested.
- Ruling: the newly created sibling repository is the isolated workspace; no worktree needed because it has independent Git state and no shared checkout.
- Sources imported from their current working trees; originals remain read-only.
- Private Git state, diffs, starting source hashes and baseline copies saved under .migration.
- Ruling: current package AGENTS instructions about keeping Agent in a separate project are superseded by the user's approved optional examples/mini_agent design.
- Baseline complete against copied original layouts: mini_agent 321 passed / 1 skipped; Builder 357 passed; Evaluator 607 passed / 2 skipped.
- Shared contracts, Builder independence and packaged resources complete; canonical schemas/hash implementations preserved. 756 required historical test fixture files imported with provenance.
- Evaluator optional-Agent packaging and actual Inspect offline demo complete; a core environment without minimal_agent ran the same demo successfully.
- CLI, immutable bundle registration and explicit pinned source sync complete. Independent review found a tracked-source status bypass; direct blob/type/mode checks and regression tests now cover it.
- Default Builder/Evaluator/core environments resolve normally and pass pip check. Independently resolved optional environments also install normally and pass pip check, without altering defaults.
- First migrated full run: contracts 1 passed; Builder 353 passed / 5 optional skips; mini_agent 323 passed / 1 paid smoke skip; evaluator 598 passed / 14 optional/paid skips; integration 29 passed before subsequent source/setup regressions were added.
- Final clean-clone acceptance at code commit 41892ae: default 1,310 passed / 20 skipped; optional 1,327 passed / 3 paid smoke skips. Both profiles left the clone Git-clean. Demo, registry resolution and Builder preparation also passed.
- Independent final review: no remaining blockers. The old equivalence test's nested latency flake was corrected with a deterministic regression and semantic comparison guards.
- Host ruling: Make is unavailable (Xcode placeholder), so documented Python entrypoints were used for actual acceptance. No system installation was needed.
- Source integrity: all 1,023 imported original files and all three original Git HEAD/status snapshots remain unchanged. All 1,172 preserved reference/fixture files verify.
- Integration ruling: the user authorized autonomous creation and local integration. This new repository has no pre-existing base branch; completed work is retained as local commits on codex/monorepo-migration. No GitHub remote or push was requested or created.
- Status: complete. Verification evidence and usage documentation saved; local implementation and acceptance commits retained.
