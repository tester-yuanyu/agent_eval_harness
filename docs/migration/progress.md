# Migration ledger

Plan: docs/superpowers/plans/2026-10-28-monorepo-migration.md

- User authorized local creation, integration and autonomous verification; no GitHub remote/push requested.
- Ruling: the newly created sibling repository is the isolated workspace; no worktree needed because it has independent Git state and no shared checkout.
- Sources imported from their current working trees; originals remain read-only.
- Private Git state, diffs, starting source hashes and baseline copies saved under .migration.
- Ruling: current package AGENTS instructions about keeping Agent in a separate project are superseded by the user's approved optional examples/mini_agent design.
- Status: source import complete; package extraction, CLI and environment integration pending.
