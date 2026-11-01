# Evaluator extension

This package hosts a task-dataset + Harness benchmark. The user authorized DeepEval as the formal scoring backend on 2026-11-01, retaining Inspect execution/logging. Existing Inspect scoring paths are historical compatibility. Preserve Python namespace, frozen contracts, Provider isolation, independent evidence, domain verdicts and historical result compatibility.

- Run this package's checks with its own configuration: `python -m pytest -c pyproject.toml tests` and `ruff check --config pyproject.toml src tests examples scripts packages`.
- Use the extension's existing style for migrated code. New Inspect-facing interfaces should have type annotations. Do not apply upstream-wide formatting to this package or vice versa.
- The Suite, evidence and audit storage contract is intentionally local-file based. Do not silently interpret remote URLs or execute code from data/configuration files.
- Never put Oracle/reference answers into the Provider's ExecutionSpec or Agent messages. Inspect Sample targets stay empty for business tasks; the trusted Scorer resolves Oracle privately.
- Agent code stays in its separate project. The SQLite Provider is a real isolated local test environment, not a Docker sandbox. Keep container support and verification status explicit.
- Paid model tests are opt-in. No hosted upload is part of default local evaluation.
- Use public Inspect execution/logging and DeepEval metric APIs. Domain-only requirements stay here; core patches need demonstrated API gaps and focused tests.
