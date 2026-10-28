# Automatic Agent evaluation intake

The user requested automatic compatibility, preparation and execution when a new Agent evaluation is delivered. Upstream Nanobot and Dataset Builder contract changes remain with their owners. This work implements the Evaluator side and validates it with the current Nanobot delivery.

## Approach

Use one intake layer above the existing Suite compiler and Provider system. It detects a Suite, existing EvalCase JSONL, or a versioned candidate delivery (directory or ZIP), validates and snapshots its inputs, selects a trusted execution binding, and produces ordinary Suites. All execution and scoring continue through the current Inspect integration. A separate scoring engine and changing upstream data to resemble mini_agent were considered and rejected because they violate ownership or lose source meaning.

The initial input assumption is an evaluation package plus an Agent project path or explicit runtime binding. Known adapters can be selected by declared Agent identity; a standard JSON-over-stdio binding supports additional Agents without changing the scoring pipeline. Arbitrary source code cannot be inferred from a data package and executed as a trusted integration. Missing bindings produce actionable case-level intake findings, without discarding runnable cases.

## Contracts

- Preserve the original delivery bytes, IDs, source hashes, readiness, support status and approval. Compatible candidate protocols are `nanobot_candidate` 1.0 and neutral `agent_candidate` 1.0; aliases do not imply an Agent identity.
- Candidate import is deterministic. Map source IDs to filesystem-safe stable EvalCase IDs and retain an explicit reverse mapping. Missing Oracle assertions remain blocked; never manufacture reference answers, capabilities, goal states or criticality.
- `ExecutionSpec.adapter_input` holds only operation inputs and fixture declarations. `AdapterOutput.observations` and `CaseResult.observations` preserve structured observations. A single `observations_match` business assertion resolves private Oracle predicates, reusing native Inspect value/text scorers. Unknown/missing observations are inconclusive; independently observed mismatches remain failures.
- `DatasetBundle.onboarding` and `EvaluationRunResult.onboarding` preserve intake provenance and coverage. Partial/draft/static intake results cannot pass release gates. Metrics remain owned by Inspect; reports copy the saved summaries.
- Extract the existing v3 snapshot loader into a neutral module, preserving exact snapshot payloads. Mini Agent keeps its compatibility wrapper and normalization. No synthetic Agent modules or tool capabilities.
- Static schema/declaration records run as `framework_self_test`; behavior runs separately as `agent_benchmark`. Draft candidate behavior is explicitly provisional. `blocked_obligation` records and non-runnable candidates are listed in the intake ledger, never fake failed Trials. A blocked case does not stop unrelated runnable cases.
- All dependency bytes must be declared and hash-bound in generated Suites. ZIP paths, links, duplicates, ambiguous roots and oversized entries are rejected. No remote schema resolution, dynamic imports or shell commands from candidate inputs.
- Runtime binding is an explicit Evaluator input, separate from the delivery. Bindings contain adapter ID, Agent ID/root/interpreter or argv plus environment variable names; never credential values. The trusted binding file shape stays unchanged. Intake snapshots the selected executable files with `snapshot_runtime_binding`; generated Suite Provider configuration carries `runtime_files` beside `binding`. Non-static Providers require the exact file set and hashes at preflight and before process launch. JSON-over-stdio accepts execution only and returns observations, not scores. Enforce timeout, output limits, process-group cleanup and strict response validation.
- Nanobot adapter uses its selected Python environment with fixed return-object operations and in-memory fixtures. The worker directly loads only the hash-bound `nanobot/runtime_context.py` and `nanobot/sdk/types.py` under evaluator-selected names, bypassing package initializers. It does not initialize a full Agent, model, tool runtime or real session. Delivered source hashes and separately captured runtime identities retain their distinct provenance; missing delivery declarations are never represented as source-provided hashes. Unsupported module/tool operations and unresolved conversation boundaries stay explicit.
- No Nanobot or Builder source changes, no hosted upload, no model calls for offline acceptance.

## Execution trust boundary

A stdio binding selects trusted host code. Temporary working directories, limited environment forwarding and process cleanup do not prevent arbitrary worker code from accessing the host filesystem or network. No operating-system or container sandbox is supplied by this adapter. Runtime hashes identify the selected executable files, not every transitive dependency or a fully hermetic environment. The fixed Nanobot worker narrows supported operations and avoids package initialization; its verified local modules are still executable code.

## User-facing behavior

`agent-evaluator run --input DELIVERY --agent-root AGENT_ROOT --output-dir OUTPUT` prepares and runs known adapters automatically. `--binding BINDING.json` selects the neutral stdio protocol for another Agent. Existing `--suite` and `--dataset` commands remain compatible. `validate --input` performs intake/compilation without creating Agent runtimes.

The output contains intake.json, source/ID mapping, generated Suites and standard run directories. Each partition links its authoritative results. Missing runtime adapters, unsupported operations, unsupported Oracle operators, unknown support status and upstream blocker reasons have different codes and owners.

## Verification

Use the extension's pyproject for all checks. Cover valid and invalid archives/hashes, a second Agent identity, Oracle separation, missing/null observations, partial evidence preserving failures, subprocess timeout/output/protocol failures, blocked-only packages, provisional gate rejection and legacy compatibility. Run actual Nanobot intake, static cases and supported SDK cases. Its source hashes must match the delivery. Report exact coverage and retain unresolved upstream findings.

## Workspace

The current branch contains an uncommitted Inspect migration; extension files are currently untracked in the nested upstream checkout. Work in the current authorized workspace with a baseline file-hash snapshot and bounded edits. Do not create a worktree from stale HEAD, commit unrelated migration changes or modify upstream repositories.

## Implementation status

Implemented: deterministic intake and split Suites, the existing EvalCase/Inspect scoring path, neutral capability loading, strict observation predicates with eager local schema-reference validation, CLI routing, authoritative report references, blocked ledgers, provisional release-gate exclusion, and explicit stdio/Nanobot bindings. Runtime executable identity snapshots and prelaunch revalidation are implemented and recorded in the implementation plan and progress ledger. Documentation describes the host-process trust boundary rather than claiming a sandbox.

Final integrated tests/lint, real Nanobot static/SDK execution, coverage reconciliation and source-integrity acceptance are performed by the root task. Intermediate component test counts are evidence for those components and are not final acceptance.
