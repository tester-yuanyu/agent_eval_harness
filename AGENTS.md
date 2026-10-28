# Agent Eval Suite

The user authorized the monorepo migration on 2026-10-28. Work only in this new repository. The original three projects under the parent directory are read-only references. Their current working trees, not just committed HEADs, were imported.

- Inspect owns execution and formal scoring. Evaluator provides domain contracts, adapters, evidence and policies. Langfuse displays saved results and hosts review; no automatic hosted uploads or paid model calls in tests/demo.
- Preserve Python API/CLI compatibility where feasible, frozen JSON content and historical Hash semantics. Do not edit frozen datasets to make tests pass.
- The shared contracts package owns common capability/evaluation structures. Builder's generation IR stays internal. Keep the trace SDK independent.
- Agent adapters are optional. A missing mini_agent must not prevent importing core evaluator or using an external Provider.
- Keep Oracle/expected answers out of execution inputs and model messages. A process returning successfully does not mean the Agent passed.
- Keep reference capability identity separate from current runtime capability identity. Comparison pins the reference dataset/contracts and controls; new runtime identity may be a supported experimental variable.
- Each package has its own environment/lock. The root CLI uses subprocesses, not direct runtime imports. Builder must not require the whole evaluator merely for common dataset validation.
- New asset registration is immutable, version-to-Hash binding is verified, and mutable aliases are resolved before formal use. Preserve v3 agent.json; no extra JSON manifest inside a v3 bundle.
- Retain source provenance in docs/migration and private baseline records in .migration. Do not copy credentials or nested Git histories into tracked files.
- Tests must not call live model APIs or hosted services. Run focused checks during development, package regressions after integration, then clean-clone installation/demo verification.
- Subagents have explicit file ownership. Do not commit or stage another agent's changes; the coordinator integrates and commits.

