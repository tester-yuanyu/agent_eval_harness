# Official τ-bench pilot with nanobot

This is a separate English retail suite. It uses the official tasks, domain policy,
database, tools, dynamic user simulator, orchestrator and `EvaluationType.ALL`
reward calculation. The participant is the actual nanobot `AgentLoop`, with its
session and tool loop; it is not a model-only reference renamed as nanobot.

The delivered pilot completed **retail task `0`, one trial, official reward
`1.0` (PASS)** using the pinned v1.0.1 release. The Agent model was
`deepseek-flash`; the official user simulator used `openai/deepseek-flash`.
Termination was `user_stop`, and evidence verification was complete: 13 generation,
5 tool and 4 turn events. This is a bounded integration result, reported separately
from the file/decision suite's 444 instances and 612 execution trials; it is not a
full-domain reproduction or an official leaderboard result. The
[portfolio report](../../reports/file-tools-v2/index.html) includes the saved
official summary and its source hash.

## Version and attribution

- Source: <https://github.com/sierra-research/tau2-bench>
- Release: `v1.0.1`; resolved commit `fc0055dc4e0a316c3f83133267fbd6faaa770992`.
- License: upstream MIT, retained in the downloaded checkout's `LICENSE`.
- Current upstream 2.0 changes English tasks, prompts and grading. The upstream
  README explicitly retains v1.0.1 as the reproducible 1.x comparison release.
  This adapter deliberately pins that release and does not imply a 2.0 result.
- Upstream code/data are downloaded to ignored `.sources/tau2-bench`; large task
  contents are not copied into this repository or modified.

## Execution boundary

Nanobot receives only the public domain policy, tool schemas and conversational
messages. It does not receive the private τ Task, expected actions, evaluator
criteria or simulated user's private scenario. The official user simulator alone
receives the user scenario.

Each nanobot tool proxy yields a tool call to the official orchestrator. The
official environment executes it, records a `ToolMessage`, and that result
resumes the original pending nanobot call. Both official conversation JSON and
nanobot generation/tool JSONL evidence are retained. Nanobot's default shell,
filesystem, MCP, plugin discovery and messaging tools are disabled for this
domain; only the official retail tool definitions are registered.

Inspect orchestrates the outer selected batch; the official orchestrator still
owns its inner simulation and reward calculation. DeepEval's
`OfficialTauRewardMetric` exposes the saved official reward unchanged through the
shared result format. The pilot reports that reward separately from the
file-tools metrics. It does not replace official reward with GEval, reinterpret
database success, or present a small subset as an official leaderboard result.

## Setup and run

Copy `configs/benchmark/tau.example.json` to a local ignored configuration and
set `nanobot_root`. Use Python 3.12 or 3.13 for the separate τ environment.

```bash
.venvs/evaluator/bin/python -m eval_framework.benchmark.tau_adapter prepare \
  --config /path/to/local-tau.json --base-python /path/to/python3.12

.venvs/evaluator/bin/python -m eval_framework.benchmark.tau_adapter validate \
  --config /path/to/local-tau.json --output artifacts/tau-validation

.venvs/evaluator/bin/python -m eval_framework.benchmark.tau_harness \
  --config /path/to/local-tau.json --env-file /path/to/local.env \
  --output artifacts/my-tau-retail-pilot
```

`prepare` downloads/installs dependencies in `.venvs/tau`, leaving the evaluator
environment unchanged. `validate` checks the pinned source and selected official
tasks without model calls. `tau_harness` makes live Agent and user-simulator calls
using credentials from the specified environment names; `--env-file` loads a
local environment file without writing its values into configuration. Existing
nonempty result directories are rejected to preserve run evidence. The lower-level
`tau_adapter run` remains available when only official adapter outputs are needed.

The default explicit one-task subset uses retail task `0`, whose pinned task has
no nonempty natural-language assertions. Other tasks can require the upstream
NL-assertion model when their official `reward_basis` includes `NL_ASSERTION`.
They fail validation unless `allow_official_judge` is enabled;
the adapter does not silently skip those assertions or substitute another judge.
When enabled, the pinned upstream judge uses `gpt-4.1-2025-04-14` and its selected
`official_judge_api_key_env` (default `OPENAI_API_KEY`). The worker inherits only
explicitly selected provider credentials and basic platform variables.

## Outputs and limits

Under the Harness output, `official/summary.json` records source and task hashes, public policy hash, runtime package
versions, actual τ import path, nanobot working-tree identity, models, trial
rewards and experiment limits. Each task/trial retains `official-result.json`,
`nanobot-events.jsonl`, `user-simulator-events.jsonl`, a normalized
`benchmark-observation.json` and an isolated session directory. The adapter
validates source commit, tracked-file cleanliness and actual imported source.

The delivered run is `artifacts/benchmark-v2/tau-retail-pilot`; its root
`results.json` contains the normalized Inspect/DeepEval result. For the public
report generator, pass
`--tau-run artifacts/benchmark-v2/tau-retail-pilot/official/summary.json`.
Langfuse accepted its upload, and full service-side readback verified the trial,
23 observations and 2 scores, including their content and node associations.
The source-bound verification receipt remains in the local run directory.

`COMPLETED` means every planned trial has an official numeric reward, including
zero; it does not mean the Agent passed. `PARTIAL` and `FAILED` retain missing
rewards as null. Each recorded result separately reports `evidence_complete`;
empty journals, missing participants and unfinished calls cannot pass evidence
verification. Premature official termination is recorded explicitly while its
official reward remains unchanged. A tool result received exactly at a step
limit is retained before nanobot is cancelled.

Current coverage is a bounded English retail text integration. Full-domain
repeated trials, τ 2.0 multilingual/voice domains, independently calibrated
judges are additional work; none is claimed by this adapter. The
`eval_framework.benchmark.tau_harness` provides Inspect orchestration and a
DeepEval wrapper of the unchanged official reward, producing the shared trace
export format. A successful local run is separate from verified Langfuse upload.
User model, custom nanobot scaffolding and runtime
dependencies are experimental controls and must be disclosed with any results.
