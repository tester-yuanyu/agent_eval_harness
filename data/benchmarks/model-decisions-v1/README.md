# Isolated model decisions v1

This separate module suite contains **24 instances in eight families**, with three
parameter variants per family. The split is family-disjoint: 18 operation-selection
instances in dev, six abstention instances in holdout. It does not replace or alter
the frozen 420-instance file-tools-v2 dataset.

| Family | Decision being measured | Instances |
| --- | --- | ---: |
| read_named | Select read_file and the requested relative path | 3 |
| read_range | Select read_file with exact offset and limit | 3 |
| list_recursive | Select list_dir and enable recursive listing | 3 |
| write_exact | Select whole-file writing and preserve exact content/newlines | 3 |
| edit_unique | Select narrow text editing with correct old/new values | 3 |
| edit_occurrence | Select one occurrence and provide replacement-count guard | 3 |
| abstain_ambiguous | Ask for missing target/content without guessing or file access | 3 |
| abstain_noop | Follow an explicit instruction to avoid all tools | 3 |

## Actual execution boundary

The subprocess uses the configured nanobot source/interpreter and its real
`OpenAICompatProvider.chat(messages, tools)` method. Tool definitions come from
nanobot's actual ToolRegistry/file-tool classes. Each task makes one provider
`chat` invocation and stops after the model returns; **no AgentLoop runs and no
returned tool call is executed**. Provider transport may internally retry, so a
single decision does not guarantee exactly one HTTP attempt.

`decision_context` is fixed user-provided text. Where content is supplied to make
an edit decision possible, it is explicitly described as user-provided content;
it is not represented as a previously observed tool execution. The Harness sends
only public task fields and tool schemas. Private `oracle.decision` remains in
the scoring process and checks tool selection, argument subsets, and abstention.
Abstention uses an empty acceptable-tool list and `max_calls=0`. Normal cases
permit exactly one appropriate call; extra arguments are not treated as wrong
unless another explicit contract forbids them. Whole-file vs edit and occurrence
vs line-hint ambiguities are resolved by explicit user constraints in the task.

Generation events preserve the actual model content, returned tool call arguments,
usage, timings, and response model when available. The top-level `decision` is a
copy for convenience, not separate evidence. Initial/final file snapshots should
remain identical. Tests use an explicitly labeled `offline_decision_test` injected
transport; those records are not real model evaluation results.

## Interpretation and limitations

Report this population separately from program-module tests and full-Agent tasks.
It evaluates local tool selection, argument generation, and tool abstention under
controlled public context. It does not establish long-horizon planning, recovery
execution, session isolation, memory, MCP, or dynamic user-interaction quality.
The holdout contains different families from dev rather than a balanced repeat
of the same operation classes. Counts are parameterized instances, not 24
independent problem families. Authoring is AI-assisted; independent human review
has not been completed.

Run `python data/benchmarks/model-decisions-v1/build_dataset.py` to regenerate the
same bytes. Generation refuses to overwrite different frozen task/manifest bytes.
Model results must be recorded separately by the Harness; this dataset card is
not evidence of completed paid evaluation.
