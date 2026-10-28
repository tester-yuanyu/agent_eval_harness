# Agent Eval Suite Implementation Plan

> For agentic workers: use subagent-driven-development. The user authorized autonomous execution. Do not pause for routine choices.

**Goal:** Produce an independently runnable local monorepo with preserved behavior, shared contracts, optional Agent adapters, pinned artifacts and an offline demo.

**Architecture:** Four internal packages, optional reference Agent, root subprocess CLI and independent environments. Inspect is the sole formal engine.

**Tech Stack:** Python 3.11+, existing Inspect 0.3.280, Pydantic 2, pytest, existing Langfuse SDK. Preserve package-specific model dependencies.

**Spec:** ../specs/2026-10-28-monorepo-design.md

## Global Constraints
- Do not modify the three source repositories or invoke paid models/hosted services.
- Preserve frozen bytes/hash semantics, Oracle isolation and verdict policy.
- Shared contracts cannot depend on mini_agent, Builder or the evaluator engine.
- Builder IR remains internal; Agent Provider is optional; root CLI only orchestrates subprocesses.
- Fixed reference identity and variable runtime identity are distinct.
- No silently accepted version overwrite, path traversal or baseline mismatch.

## Review Focus
- Clean installation reveals stale editable dependencies or undeclared transitive imports.
- Frozen fixtures refer to source-machine paths or source roots.
- Optional Agent import occurs transitively via an eager module import.
- Registry accepts tampered assets, mutable aliases or inconsistent registration.
- Offline demo accidentally reads live credentials, auto-syncs or hides incorrect verdicts.

### Task 1: Preserve/import baseline and source identity
- [x] Create separate new repository on codex/monorepo-migration.
- [x] Materialize current source including uncommitted implementation; exclude environments, credentials and Git internals.
- [x] Save source Git state and file hashes under ignored .migration; copy starting sources for baseline tests.
- [ ] Run offline baseline in copied sources and record any original failures.

### Task 2: Shared contracts and Builder independence
**Files:** packages/contracts/**, packages/dataset-builder/**; coordinated wrappers in packages/evaluator/src/eval_framework/{schemas,schema_base,capabilities,capability_loader,tool_catalog,dataset_loader,dataset_validator}.py and examples/mini_agent snapshot namespace.
**Consumes:** imported package source. **Produces:** installable agent-eval-contracts, capability_snapshot_kit public API, eval_contracts evaluation loader/validator/models; Builder without agent-evaluator dependency.
- [ ] First add tests proving contract imports require no evaluator/mini_agent and Builder's validation still enforces frozen constraints.
- [ ] Extract only shared modules; keep wrappers to preserve historical imports; move snapshot kit with compatibility.
- [ ] Correct package/resource roots and Builder monorepo path anchors without editing frozen content.
- [ ] Run Builder and contract tests; report failures and public interfaces to coordinator.

### Task 3: Evaluator packaging and offline demo
**Files:** packages/evaluator/** excluding Task 2 coordinated wrappers; packages/agent-trace-sdk/**; examples/mini_agent/pyproject.toml (coordinate Task 2); scripts/demo.py and tests/integration/test_demo.py.
**Consumes:** imported evaluator and eventual shared contracts. **Produces:** evaluator[mini-agent] optional dependency/lazy Provider, root-neutral resource paths, offline demo producing expected PASS/FAIL/INCONCLUSIVE via real Inspect.
- [ ] Add regression proving core import/external Provider do not need minimal_agent.
- [ ] Make Agent imports lazy and eliminate stale nested Inspect/root installation assumptions.
- [ ] Build demo using existing real execution/evidence pipeline; no Oracle-driven model behavior or fake judge.
- [ ] Run targeted and package offline tests; document source baseline defects separately.

### Task 4: Thin CLI and pinned asset configuration
**Files:** src/agent_eval_suite/**, tests/integration/test_cli*.py, configs/**, data/bundle-index.json.
**Consumes:** independent package CLIs and contracts validation command. **Produces:** root eval-suite CLI, source resolution, immutable bundle registration/diff, existing builder/evaluator command dispatch preserving review/freeze boundaries.
- [ ] Write tests for invalid asset paths/versions, overwrite, changed Hash, missing environments, baseline argument forwarding and credential-free help.
- [ ] Implement stdlib orchestration and subprocess calls; pin Git refs on explicit source sync and record identity.
- [ ] Implement atomic registry outside bundle; preserve agent.json layout; dispatcher delegates formal validation to contracts package environment.
- [ ] Expose useful existing build/review/freeze and eval run/compare/gate commands with truthful help. If any designed shorthand isn't supported, provide equivalent documented explicit arguments rather than a fake success.
- [ ] Run CLI tests and hand over exact environment-path/command contract.

### Task 5: Setup, integration, clean clone and publication docs
**Files:** root pyproject.toml, Makefile, scripts/setup.py, scripts/test_all.py, environments/**, README.md, docs/migration/**, AGENTS.md.
- [ ] Create isolated Python environments with declared dependencies; produce per-environment locks after resolving conflicts.
- [ ] Run baseline and migrated package suites; resolve migration-caused failures.
- [ ] Register example artifacts, verify migrated frozen sources and new registry.
- [ ] Test clean clone/setup/demo outside original projects, optional Agent isolation and no source absolute paths in production entrypoints.
- [ ] Request independent final review, address actionable findings, record evidence and commit local repository.

