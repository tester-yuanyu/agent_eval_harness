# Evaluator packaging and offline demo

Task 3 implementation and verification, 2026-10-28.

## Changes

- `agent-evaluator` depends on `agent-eval-contracts` and public `inspect_ai==0.3.280`. `minimal-agent` is available through the `mini-agent` extra, not a core dependency. Default registry/catalog construction detects its availability without importing it; validation/execution lazily loads the integration. Existing `eval_framework` public names remain available.
- External Provider imports, catalog resolution, and static execution work with `minimal_agent` explicitly unavailable. A second regression verifies that catalog construction does not import an installed Agent.
- Removed the bootstrap script's nested Inspect source-checkout assumptions. Runtime evidence now identifies the installed Inspect distribution/version and source content, together with evaluator, trace SDK, shared contracts, and capability-protocol content hashes. Markdown specification resources participate in runtime identities. Historical results/files remain unchanged; new identity metadata intentionally distinguishes the migrated implementation for comparison controls.
- The trace SDK already had a standalone package configuration and the exact public Inspect dependency; no SDK source rewrite was necessary.
- `minimal-agent` consumes shared contracts and includes byte-identical capability Markdown specs as package data. Its compiler reads installed resources. A source/package parity regression detects drift. The evaluator derives current native capabilities from installed Agent code/specifications rather than a sibling checkout directory.
- Fixed evaluator tests that depended on the invocation directory or absolute original-project paths. The frozen reference fixture's empty `tools/` directory is represented by `.gitkeep`; no frozen JSON bytes changed. The legacy missing-directory compatibility test now explicitly creates that condition in its temporary copy.

## Demo contract

Run from the repository root:

```sh
.venvs/evaluator/bin/python scripts/demo.py --output-dir artifacts
```

The demo creates `artifacts/demo-*/` with a copied immutable v3 reference bundle, generated fixture cases and a suite. It uses `compile_suite`, `execute_compiled_suite`, the existing external static Provider, Inspect's real Solver/Scorer/eval-log lifecycle, and `write_report`. It uses no model, API key, external process Agent, hosted upload, or Langfuse service.

The fixture is explicitly `framework_self_test`, not a benchmark of mini_agent. Its external adapter reads supplied observations; it never sees the Oracle or case expectations. Case expectations are private to scoring. The reference bundle retains its original `mini_agent` identity; the selected Provider is `external_provider_v1` and the runtime binding is recorded separately.

Expected results are checked before exit success:

| Case | Observed value | Expected conclusion |
| --- | --- | --- |
| DEMO-PASS | 42 | PASS |
| DEMO-FAIL | 7 | FAIL |
| DEMO-INCONCLUSIVE | Missing | INCONCLUSIVE, score null |

All three executions complete; success of execution alone does not imply quality PASS. Stdout is one JSON object containing `suite`, `run_directory`, `report`, `results`, `inspect_log`, and `conclusions`. The same manifest is saved as `demo.json`. Integration coverage reads the native Inspect log, checks successful execution, empty Sample targets, and absence of a private Oracle marker from Agent messages.

## Verification evidence

- Initial optional-Agent regression failed on the eager composition import; after lazy registration, targeted external-provider/catalog coverage passed (29 tests). The installed-Agent no-import regression also failed first, then passed.
- Clean project evaluator environment: dependency installation and `pip check` passed.
- Full evaluator suite plus demo integration: **599 passed, 14 skipped, 59 warnings**, 91.11 seconds. Command: `.venvs/evaluator/bin/python -m pytest -q -c packages/evaluator/pyproject.toml packages/evaluator/tests tests/integration/test_demo.py`. Log: `.migration/evaluator-tests-final.log`. Skips are 12 optional conversation tests and two paid API smoke tests; warnings are existing deprecated compatibility APIs.
- After adding Markdown specification identity coverage, source identity/comparison/engine checks: **21 passed**, and the demo again produced exactly PASS/FAIL/INCONCLUSIVE.
- Full evaluator lint from `packages/evaluator`: `../../.venvs/evaluator/bin/ruff check --config pyproject.toml src tests examples scripts` — **all checks passed**.
- Resource packaging/parity checks: **4 passed**. Built the normal `minimal-agent` wheel with build isolation, extracted it to a temporary directory, ran isolated Python (`-I`), verified imports came from the extracted wheel, and successfully compiled its real capability bundle. Dependencies came from the fully resolved evaluator environment; no dependency installation was bypassed.
- Initial full evaluator run exposed one CWD-dependent schema-test path (595 passed / one failed); fixed and covered by the full passing run above.
- Running the mini_agent suite from repository root caused 23 collection errors due to its existing `tests.support` namespace expectations; the supported runner executes it from its package directory. Its first package-directory run had 322 passed / one failed / one skipped; the failure was the historical snapshot-kit staging script referring to the pre-extraction location. The contracts implementer repaired that script and its focused regression passed.
- Final full mini_agent suite from `examples/mini_agent`: **323 passed, one paid smoke test skipped**, 27.86 seconds. Command: `../../.venvs/evaluator/bin/python -m pytest -q -c pyproject.toml tests`. Log: `.migration/mini-agent-tests-complete.log`.

## Setup and scope

The root setup installs evaluator, shared contracts, trace SDK and the optional reference Agent into `.venvs/evaluator`. Core-only installation can omit the Agent and still run the external demo. The package's paid/conversation extras remain opt-in. The coordinator owns independent clean-clone/core-only environment acceptance and final locks.

No original repository was edited, no frozen JSON was rewritten, no credentials were used, and no changes were staged or committed by this worker.
