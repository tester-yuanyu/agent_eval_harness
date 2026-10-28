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
- Default Builder/Evaluator/core environments resolve normally and pass pip check. Independent optional dependency locks resolve the DeepEval/default click+rich version conflict found in review; final installation verification pending.
- First migrated full run: contracts 1 passed; Builder 353 passed / 5 optional skips; mini_agent 323 passed / 1 paid smoke skip; evaluator 598 passed / 14 optional/paid skips; integration 29 passed before subsequent source/setup regressions were added.
- Independent architecture review found no additional blockers. Remaining: refreshed final tests, clean clone setup/demo, optional environment installation, final evidence and local commit.
