# Agent Eval Suite migration design

## Intent and scope
Create a locally usable, publishable monorepo from the current mini_agent, agent_dataset_builder and agent_evaluator working trees. Preserve originals, current behavior, frozen artifacts and provenance. No GitHub publication or live paid evaluation is part of this task. User approved autonomous completion.

The selected approach is one repository with independently packaged modules and environments, external Agent integration plus an optional in-repository reference Agent. Keeping multiple repositories was considered but loses the simple installation/navigation experience; combining all code/dependencies into one package was rejected because ownership and existing version constraints differ.

## Components
- packages/contracts: existing capability_snapshot_kit and shared evaluation structures/validation under eval_contracts. Keep compatibility exports where needed. No Builder generation IR or execution engine here.
- packages/dataset-builder: candidate generation/import, coverage, compilation, seven gates, explicit review/freeze. Remove dependency on agent-evaluator; consume shared file contracts.
- packages/evaluator: independently installable Inspect business extension. Preserve eval_framework public namespace. mini_agent Provider is optional/lazily registered. Inspect 0.3.280 remains the sole engine. Langfuse is optional delivery, never default cloud upload.
- packages/agent-trace-sdk: imported SDK, unchanged engine dependency initially.
- examples/mini_agent: reference Agent, depends on shared snapshot package and trace SDK, not evaluator core. Keep existing minimal_agent namespace.
- root src/agent_eval_suite: lightweight CLI (stdlib preferred), version/asset resolution and subprocess orchestration; never imports package runtimes.

## Assets and runtime identity
New capability publications live under data/bundles/<agent>/<version>, maintaining exact v3 agent.json layout. An index outside bundles binds version to path, bundle hash and agent root hash. Validate before atomic registration; versions cannot be overwritten and path traversal is rejected. Validate supplied schema against trusted protocol validation. Development aliases must resolve to immutable identities before formal dataset generation/evaluation. Preserve all existing frozen fixtures and legacy suites for compatibility; register selected distributable examples in root data.

Reference bundle identity belongs to the frozen dataset. Runtime bundle identity belongs to the actual Agent/configuration. The runtime may change while reference stays fixed, subject to existing compatibility checks. Bundle/data tampering is rejected. Comparison accepts run IDs/result directories and rejects different reference datasets/contracts or uncontrolled configuration. Never compare a newly built dataset's score against an old dataset's score.

Agent configuration supports packaged/local bindings and explicit Git fetch/checkouts pinned to a commit. Executable bindings are trusted user configuration, not commands inferred from dataset content. No auto-pull while running. Existing endpoint integration uses existing provider transport; remote build identity may be unknown, which must be explicit and cannot claim strict reproducibility. Do not implement a new transport unless existing external Provider needs it for the agreed example.

Builder reads a pinned bundle, copies it into the workspace, builds IR, generates or ingests candidates, validates, creates review materials, then explicitly freezes after human review. Reviewer identity is never fabricated. Changed draft/bound inputs invalidate approval. Frozen output includes JSONL, manifest, coverage and a portable capability bundle. Historical files and hash algorithms are not rewritten as part of path migration.

## Environments and demo
Root orchestration invokes package environments. Builder and evaluator currently have incompatible OpenAI requirements and optional DeepEval pins; shared contract extraction removes their unnecessary dependency. Do not force one resolver environment. Lock independently and install declared dependencies honestly (no --no-deps workaround hiding conflicts).

make setup installs required local packages and public pinned dependencies. make demo runs offline through Inspect with scripted behavior and saved human-readable/machine-readable reports. Must demonstrate expected PASS, FAIL and evidence-insufficient behavior, preserve Oracle isolation, require neither model keys nor Langfuse services, and succeed only when expected conclusions are observed. make eval-live is explicitly opt-in. Package tests and top-level integration tests remain runnable.

## Migration and acceptance
1. Import actual source files (no nested .git, external source symlinks, virtualenvs or secrets); preserve private baseline and source hashes.
2. Extract shared contracts, make Provider optional, fix package roots/relative resources, set independent environments.
3. Add thin root CLI, pinned asset/source configuration, offline demo and docs.
4. Verify migrated fixtures preserve behavior; whole package offline regressions; source assets unchanged; packages install with dependencies; clean clone setup/demo; core can import/use external fixture without mini_agent.
5. Record results and limitations accurately, commit local changes. Original trees remain untouched, no remote push.

## Ownership
Coordinator owns root setup/environment scripts, documentation, integration and source provenance. Contracts implementer owns packages/contracts and packages/dataset-builder plus explicitly coordinated compatibility modules in evaluator/mini_agent. Evaluator implementer owns optional Provider work, evaluator packaging, SDK packaging and offline demo. CLI implementer owns src/agent_eval_suite, its tests/configuration, and root asset registry. Coordinate any overlapping files before editing.

