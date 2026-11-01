# File Tools v2: modules, critical chains, end-to-end

This immutable dataset extends v1 without editing its bytes or historical results.
It has 420 instances in 104 families, with family-disjoint 340 dev / 80 holdout
splits. Instances within a family are parameterized variants, not independent
problem families. The authoring is AI-assisted and has not received independent
human review.

| Layer | Instances | Families | Dev | Holdout | Actual execution |
| --- | ---: | ---: | ---: | ---: | --- |
| Module | 60 | 12 | 50 | 10 | Real nanobot ToolRegistry and file tools, no LLM |
| Critical chain | 60 | 12 | 50 | 10 | Real Agent with private step/turn checkpoints |
| End-to-end | 300 | 80 | 240 | 60 | Real Agent, inherited v1 tasks and independent final-state checks |

Module results must be reported separately from Agent success rates. Modules do
not measure LLM tool selection, planning, session management, memory, or MCP.

## Module families

Read complete text, read a slice, missing-file error, create, overwrite, nested
write, exact edit, select one repeated occurrence, replacement-count guard,
missing required parameter, invalid integer parameter type, and recursive listing.

The subprocess invokes the upstream ToolRegistry and actual file implementations
in the configured nanobot interpreter. A workspace containment wrapper is retained.
There is no mocked provider, LLM request, or deterministic reference impersonating
an Agent. Negative cases assert actual ToolResult error status and message evidence;
correctly rejecting invalid inputs is a passing module outcome. Private
`oracle.module_results` checks each 1-based call and never crosses the process
boundary. The public `module_calls` is the fixed module input, not an expected answer.

## Critical-chain families

Read then report, read two sources then join, discover then copy, draft then
finalize, replace then append, copy then revise, staged JSON updates, staged CSV
report, missing-primary fallback, ask to resolve conflict, preserve source while
transforming, and revise while retaining previous constraints.

Three checkpoint kinds are versioned and validated:

- `turn_files`: exact selected file states after a declared 1-based conversation turn.
- `tool_args`: a specified tool call with an argument subset; unrelated arguments
  and alternative permitted actions remain allowed.
- `tool_order`: a necessary pairwise order only where the task explicitly requests
  those tools. This does not mandate one complete golden trajectory.

Every checkpoint has a unique ID and explicit `required` flag. None enters the
Agent execution projection. Missing required evidence is not a passing check.
The runner records actual tool inputs/outputs and before/after snapshots; scoring
is separate from execution. Fixed follow-ups are not a dynamic user simulator.

## v1 provenance and errata

The 300 E2E instances preserve v1 fixtures, oracles, reference recipes, family IDs,
and splits, with `source_task_id` linking each old record. Only the three
`read_search/markdown_heading` prompts clarify that the leading Markdown marker
and separator space should be removed while spaces within the title are retained.
The original expected answers are unchanged. Original v1 task bytes and results
remain untouched; v2 scores must not be silently substituted into v1 comparisons.

## Generation and evidence

Run `python data/benchmarks/file-tools-v2/build_dataset.py` from the repository.
Generation is deterministic and refuses to overwrite differing frozen task or
manifest bytes. `tasks_sha256` is validated by the loader. Module solvability is
checked using actual module execution, not `reference_observation`.

The dataset card describes capability and scope, not completed run results.
Execution and scoring records are stored independently under the versioned run
artifacts by the Harness. This suite remains UTF-8 filesystem-only; it does not
cover every nanobot subsystem or provide a τ-bench score.
