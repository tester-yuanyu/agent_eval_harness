# Three-layer evaluation and trace scoring

Approved direction: the user's 2026-11-01 request accepts module → critical-chain → end-to-end coverage, observation-level scores, quantified GEval diagnostics, new results, then a τ-family integration. Continue in this existing dedicated repository and branch; original repositories remain read-only.

## Architecture and boundaries

Keep Inspect orchestration, DeepEval as the scoring owner, and Langfuse as saved-evidence presentation. Preserve file-tools-v1 and its results. Publish file-tools-v2 with explicit `evaluation_level` (`module`, `chain`, `e2e`) and `execution_mode` (`module`, `agent`). Module executions call real nanobot module boundaries in its interpreter; they are not LLM success trials. Chain and E2E execute the real Agent. Report these populations separately.

New private `checkpoints` describe step/turn expectations; they never enter Agent inputs. Each metric has `scope`, optional `event_id`, `score`, `reason`, `formal`, `status`, and metric version. A missing required evidence item is unscored/inconclusive, not a pass. Hard deterministic checkpoints can fail the task; diagnostic scores never rescue failed constraints. Support legitimate alternative paths, and do not grade private reasoning.

GEval operates after execution on saved evidence. Its three dimensions are action appropriateness, recovery appropriateness (only where applicable), and response groundedness. Scores are diagnostic until human calibration; freeze rubrics, record evidence IDs/model/config/calls, expose coverage and repeated-score variation. A calibration worksheet without completed independent human labels is not calibration evidence.

## Interfaces

- Task v2: retain v1 fixture/oracle fields. Add `evaluation_level`, `execution_mode`, private `checkpoints`; module tasks add public `module_calls` (name/arguments). `execution_task` strips checkpoints and all private expected results.
- Checkpoint kinds: `turn_files` (`turn`, `expected_files`), `tool_args` (`tool`, `arguments` subset, optional `turn`), `tool_order` (`before`, `after`, optional `turn`). Every checkpoint has unique `id`, `required` boolean. Extend only with explicit validation.
- `trajectory.score_trajectory(task, observation) -> list[dict]`: DeepEval-backed deterministic per-event scores plus checkpoint scores. Event links must resolve to recorded events; root-only aggregate scores use `scope=task`.
- `module_runtime.execute_module_task(task, *, config, workspace) -> observation`: asynchronous real-module subprocess execution, same observation shape as the existing runtime, `execution_kind=real_module`.
- `judging.judge_observation(task, observation, model_config) -> list[dict]`: GEval diagnostics with `scope/event_id`, model-call evidence and errors. `judging.summarize_judgments(records)` and calibration helpers quantify coverage/agreement only over available evidence.

## Delivery

1. Freeze and validate 300 E2E instances plus new module/chain tasks, identifying families and parameter variants honestly.
2. Execute actual module suite; execute representative then full chain/E2E suites with real model calls.
3. Export scoped scores and verify Langfuse readback at their actual observation IDs.
4. Run real GEval diagnostics, preserve model-call evidence, prepare independent calibration input and report pending human calibration explicitly.
5. Add a pinned τ-family adapter with public task/tool/state/reward semantics preserved; run a bounded real pilot when environment/model compatibility permits. Do not call a custom subset an official leaderboard result.
6. Report the seven user questions as resolved/partial/unresolved with inspectable artifacts.
