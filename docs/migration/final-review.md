# Independent migration review

Reviewed on 2026-10-28, through commit `41892aebbe27c37c676fe58dbf338ede684b42d7`, against imported baseline `08e20ac` and the approved migration design.

**Conclusion: no outstanding blocking findings in the reviewed changes.** Final clean-clone regression totals are coordinator-owned and recorded separately in `verification.md`.

## Scope and resolved findings

- Reviewed root subprocess dispatch, bundle validation/registration, Git source identity, independent installation profiles, shared contracts, optional Agent integration, resource packaging, offline demo, and current entrypoint documentation.
- The source identity finding is resolved: tracked checkout bytes and modes are checked against the pinned commit tree independently of Git index flags; Git replacement objects are disabled. The documented limits concerning ignored files and dependencies remain explicit.
- The optional dependency finding is resolved: Builder and Evaluator have independently resolved optional constraints. Optional installs now use `.venvs/builder-optional` and `.venvs/evaluator-optional`, leaving default environments intact. The test runner selects matching interpreters and separate log directories.
- Shared core models and validation retain their imported semantics. The contracts package has no reverse dependency on Builder, Evaluator, Inspect, or the reference Agent. Builder wheel limitations for repository-specific built-in Suites are documented.
- The demo uses actual Inspect execution/scoring, keeps Oracle values outside Agent messages, and distinguishes reference identity from runtime configuration. An actual core-only environment ran the demo without installing or importing `minimal_agent`.
- The suite-equivalence test correction excludes only the additional nested measured p50/p95 latencies. Performance sample count and Judge token fields remain compared, with explicit regressions proving changes to those fields still fail equality. Production scoring code was not changed by that correction.
- README Python setup, demo, CLI, core-only, and optional-profile instructions match the implementation; Make is an optional equivalent entrypoint.

## Independent verification

- Root CLI review: 25 tests initially passed; 28 passed after the initial source-identity repair. Later expanded source regressions were coordinator-owned.
- Core/optional-Agent/source-identity/demo/contracts checks: 6 passed. Separately ran the demo in `.venvs/core` after confirming `minimal_agent` was unavailable; observed exactly PASS, FAIL, and INCONCLUSIVE, with no Agent import afterward.
- Both complete local package combinations passed `pip install --dry-run --ignore-installed` with their optional constraint files. Those files exactly match the saved resolution reports: 71 external Builder dependencies and 125 external Evaluator dependencies.
- Inspected `.migration/profile-integrity.json`: all four clean-clone profiles report successful `pip check`; DeepEval is absent from defaults and present in optional profiles. This profile evidence was produced by the coordinator.
- Final focused command: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venvs/evaluator/bin/python -m pytest -q tests/integration/test_setup.py packages/evaluator/tests/test_suite_cli.py` — **9 passed in 2.12 seconds**.
- `git diff --check` passed at the reviewed commit.

The reviewer made no implementation changes and wrote only this report.
