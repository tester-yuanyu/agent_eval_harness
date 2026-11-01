# Tool benchmark implementation plan

Approved by YY on 2026-11-01. Target repository: agent-eval-suite. Target runtime: nanobot; original projects remain reference sources.

## Scope and acceptance

Deliver a frozen dataset of 300 executable filesystem tasks plus an Inspect execution Harness with DeepEval formal metrics. Every trial gets an isolated filesystem and session. Oracle data remains in the trusted evaluator process. Langfuse receives saved inputs, outputs, real model/tool spans, scores and evidence. The portfolio reports actual completed runs, failures, uncertainties and model/config/source identities. Historical mini_agent assets remain readable and are explicitly legacy; no public benchmark affiliation is claimed.

## Ordered work

1. P0: Freeze interfaces, validity semantics and source identities. Task fixtures are public; expected state/reference operations are private. Reference execution independently derives expected outcomes.
2. P0: Implement nanobot runtime, DeepEval metrics and Inspect bridge. Validate offline edge cases and run a 20-task real pilot.
3. P0: Export pilot to Langfuse and verify the remote stored observations, scoring and task associations. API ingestion alone is insufficient evidence of complete presentation.
4. P1: Execute 60 tasks, address Harness defects without changing frozen expectations to make the Agent pass. Freeze 300 tasks with 240 development / 60 held-out cases split by task family.
5. P1: Run the frozen benchmark and bounded repeated trials; compare two explicit configurations on identical tasks and controls. Preserve invalid/timeout/failed trials. Track planned versus completed counts and known versus unknown usage/cost.
6. P2: Make the benchmark the primary CLI/documentation path. Remove duplicate active entry points where safe, retain historical result compatibility, add a reproducible offline demo and evidence-backed portfolio.
7. Final: Independent review, focused and package regression checks, clean-install smoke, inspect credentials/untracked artifacts, commit the integrated work locally.

## Shared interfaces / ownership

- tasks.py + oracle.py + frozen data: dataset worker. JSON task schema has id/family/category/split/prompt/followups/fixtures/oracle/reference/required_tools/allowed_tools/max_steps. execution_task strips oracle, reference and required_tools.
- nanobot_runtime.py + nanobot_worker.py: runtime worker. async execute_task(execution_task, config=..., workspace=...) -> observation. status, turns, disk snapshots, events, usage, errors and runtime identity are returned. Public SDK and restricted filesystem tools; no claim of OS sandboxing.
- metrics.py: scoring worker. score_task(task, observation) -> verdict, validity, metrics, backend and errors. Real DeepEval BaseMetric implementations; critical violations cannot be averaged away. Optional GEval is diagnostic pending calibration.
- runner/CLI/Langfuse/docs/dependencies/integration: coordinator. Inspect Sample target remains empty; scorer bridge delegates to DeepEval. Results journal allows recovery without repeating completed Agent executions.

## Preflight rulings

- The user's explicit DeepEval decision supersedes legacy AGENTS.md scoring ownership. Inspect execution/logging is intentionally retained.
- No second scorer in Langfuse. Export derives exclusively from immutable saved results.
- Old mini_agent module cases, schema checks and repeated trials never count as new E2E tasks.
- Never label AI-assisted review as human review. No GEval calibration claim without actual labeled examples.
- Live model calls and Langfuse delivery are explicitly part of this task; tests/demo remain offline. Use bounded batches, a hard per-trial step/time limit and no automatic retries that hide failures.
- nanobot stays in a separate interpreter to avoid OpenAI dependency conflicts.
