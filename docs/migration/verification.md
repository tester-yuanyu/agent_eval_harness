# Verification record

Verified on 2026-10-28 with Python 3.11.4 on macOS. Code acceptance commit: `41892aebbe27c37c676fe58dbf338ede684b42d7`; the following documentation-only commit records these results.

## Original baseline

Baseline tests ran against private copies of the original working trees, with required fixture deliveries and the original sibling directory layout. Original repositories were not edited. Model credentials and live-smoke flags were removed from test subprocess environments.

| Original package | Result |
| --- | --- |
| mini_agent | 321 passed, 1 skipped |
| agent_dataset_builder | 357 passed |
| agent_evaluator | 607 passed, 2 skipped |

The original environments include optional dependencies. Default monorepo environments deliberately omit optional DeepEval extras, so skip counts must be interpreted with the recorded dependency set.

## Migration verification

The repository was cloned with `git clone --no-hardlinks` into a new temporary directory outside the original projects. Both default environments were created from scratch by `python3.11 scripts/setup.py`, using declared dependencies and saved constraints. All local imports were checked to resolve inside that clone. No source checkout or old virtual environment was injected with `PYTHONPATH`.

| Test group | Default environments | Optional environments |
| --- | --- | --- |
| Shared contracts | 1 passed | 1 passed |
| Dataset Builder | 353 passed, 5 skipped | 358 passed |
| Reference Agent | 323 passed, 1 skipped | 323 passed, 1 skipped |
| Evaluator | 598 passed, 14 skipped | 610 passed, 2 skipped |
| Root integration | 35 passed | 35 passed |
| **Total** | **1,310 passed, 20 skipped** | **1,327 passed, 3 skipped** |

The 17 additional default skips are optional DeepEval SDK/metric tests. The three remaining skips require explicitly enabled paid API smoke calls; these were not run. Existing compatibility API deprecation warnings remain (59 in default Evaluator, 80 with optional tests). The trace SDK has no separate test directory and is exercised by Agent and Evaluator consumers.

Commands in the clean clone:

```bash
python3.11 scripts/setup.py
python3.11 scripts/test_all.py
python3.11 scripts/setup.py --only builder --optional-metrics
python3.11 scripts/setup.py --only evaluator --optional-metrics
python3.11 scripts/test_all.py --optional-metrics
```

Optional installs use `.venvs/builder-optional` and `.venvs/evaluator-optional`; they do not replace the default environments. All four environments passed `pip check`. DeepEval was absent from both defaults and present in both optional environments after installation.

## Additional acceptance checks

- The clean clone ran the offline demo through native Inspect and produced exactly `PASS`, `FAIL`, `INCONCLUSIVE`, plus Markdown/JSON results and a native `.eval` log. The root core-only environment also ran this demo without installing or importing `minimal_agent`.
- The installed CLI resolved and revalidated `mini_agent@0.1.0`, and prepared `mini_agent_query_user_intent_v2` offline in the clean clone. Canonical validation and source/registry edge cases are covered by 32 CLI tests within the integration group.
- `scripts/verify_assets.py` verified **1,172** imported reference/fixture files: 416 original reference assets and 756 manifest-bound Builder fixtures. Frozen JSON and hash algorithms were preserved.
- Builder and mini_agent wheels were built normally and their resources exercised outside the source checkout. See the component reports for the tested independent-use boundary.
- The 1,023 initially imported source files were re-hashed against their original locations: none changed. All three original repositories retained their original HEAD and working-tree status. The new repository contains no nested Git repository, external source symlink, virtual environment or detected credential file in its tracked content.
- The clean clone remained Git-clean after both full runs. Original repositories were never committed, moved or pushed by this migration.
- Independent review concluded with no remaining blocking findings: [review report](final-review.md).

## Issues resolved during acceptance

1. Historical tests depended on sibling project paths, external fixture deliveries and empty bundle directories. The migration uses compatible path resolution, verified fixture copies and non-JSON `.gitkeep` files where needed.
2. `git status` alone could miss tracked modifications hidden by index flags. Pinned source resolution now checks actual blob bytes, file types and modes against the commit tree.
3. DeepEval's Click/Rich requirements conflicted with default pins. Optional dependencies now have separately resolved constraints and separate environments.
4. An old Suite equivalence test compared two independently measured latency quantiles. Deterministic regression now excludes only those timing values and still rejects changes in sample count or Judge token totals; production scoring behavior was unchanged.
5. This host's `/usr/bin/make` is an Xcode placeholder. Acceptance used the documented equivalent Python entrypoints. Make targets remain available for systems with Make installed; they were not executed successfully on this host.

Local evidence is retained in ignored `.migration/clean-clone-*-final.log`, `.migration/profile-integrity.json`, and `artifacts/verification-clean-clone/`. Migration source backups and baseline logs remain under `.migration/`. These local logs are not committed, while this record and component reports are committed.

This migration establishes local packaging and reproducible offline execution. It does not publish a GitHub repository, execute paid evaluations, establish a production Agent success rate or substitute for human review of newly generated datasets.
