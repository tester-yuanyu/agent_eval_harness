# Contract-Driven Plugin Architecture Design

## Status

Approved conversational design. This document defines the next architectural
phase for `agent_evaluator`; implementation requires a separately reviewed plan.

## Objective

Keep the evaluation kernel stable while allowing different Agents, runtime
models, evaluation dataset formats, semantic Judges, Trace conventions,
assertion sets, reports, and release policies to be integrated primarily through
versioned constraint documents plus explicitly trusted plugin code.

The target integration experience is:

- a new Agent adds a Provider plugin, contracts, Suite definitions, and tests;
- a new dataset format adds a Loader plugin and Suite definition;
- a new rule adds a registered rule ID and configuration Schema;
- core Runner, CLI, Reporting, and protocol code normally remain unchanged.

“Normally” is deliberate: core changes remain possible for genuinely new
cross-cutting semantics, but must not be required merely to name another Agent,
dataset format, Judge backend, event vocabulary, assertion, or report label.

## Design Principles

1. **One canonical internal protocol.** External formats are converted before
   execution; the Runner never branches on dataset format.
2. **Documents declare; trusted plugins execute.** Data files cannot import or
   execute arbitrary Python.
3. **Explicit registration.** A document may reference only an installed,
   explicitly registered plugin ID and compatible version.
4. **Compile before execution.** All references, Schemas, versions, and hashes
   are resolved into an immutable `CompiledSuite` before any Agent Runtime is
   created.
5. **No silent fallback.** Unknown IDs, incompatible versions, and invalid
   configurations fail preflight with stable error codes.
6. **Immutable evidence.** Derived analysis, comparison, gates, and reports do
   not rewrite original run results.
7. **Frozen reproducibility.** Formal runs persist expanded contracts and
   fingerprints rather than relying only on mutable paths.
8. **Incremental migration.** Existing JSONL datasets, mini_agent integration,
   DeepSeek Judge, CLI flags, and historical artifacts remain compatible while
   the new path proves equivalence.

## Architecture

### 1. Contract Document Layer

The top-level document is a `SuiteDefinition`. It references all contracts that
define an evaluation run:

```text
SuiteDefinition
  ├─ dataset_loader
  ├─ dataset_sources
  ├─ provider
  ├─ capability_bundle
  ├─ assertion_profile
  ├─ trace_profile
  ├─ judge_profile (optional)
  ├─ report_profile
  └─ gate_policy (optional)
```

Each reference contains a stable plugin or contract ID, a compatible version
constraint, and configuration validated against the selected plugin's Schema.

Documents are pure data. JSON is the canonical frozen serialization. YAML may
be accepted as an authoring format by a Loader, but compilation emits canonical
JSON with deterministic key ordering and SHA-256 identity.

Contract composition and inheritance may be supported for authoring. A frozen
Suite must store the fully expanded result so later changes to a parent document
cannot alter a historical run.

### 2. Trusted Plugin Layer

Every plugin exposes a common descriptor:

```text
PluginDescriptor
  id
  kind
  version
  config_schema
  supported_contract_versions
  implementation_fingerprint
```

Supported plugin kinds initially are:

- `provider`
- `dataset_loader`
- `assertion_rule`
- `trace_rule`
- `judge_backend`
- `pipeline_stage`
- `report_renderer`
- `gate_check`

Registration keys are the exact tuple `(kind, id, version)`. Duplicate keys are
rejected. Resolution never selects a “nearest” plugin or silently changes major
versions.

Plugins are trusted executable code installed with the application or
explicitly registered at the composition root. Suite and dataset files cannot
specify Python module paths, entry points, shell commands, or inline code.

The first migration uses an explicit in-process `PluginCatalog`. A future Python
Entry Point discovery layer may populate the same Catalog, but automatic
discovery is outside this phase.

### 3. Evaluation Kernel

The kernel owns only general evaluation semantics:

- strict internal protocol models;
- contract resolution and preflight validation;
- canonical hashing and provenance;
- Trial isolation and lifecycle orchestration;
- Pipeline Stage scheduling;
- error boundaries and stable error codes;
- immutable result storage;
- deterministic aggregation primitives.

It does not import a concrete Agent Provider, dataset Loader, Judge backend,
assertion vocabulary, Trace event vocabulary, report language pack, or business
Gate Check.

### 4. Composition Root

The CLI is a thin composition root:

1. register explicitly enabled built-in and project plugins;
2. load a `SuiteDefinition`;
3. compile it with the Catalog and Contract Store;
4. pass the `CompiledSuite` to the kernel;
5. invoke downstream read-only commands against saved artifacts.

The preferred new invocation is:

```text
agent-evaluator run --suite path/to/suite.json --output-dir artifacts
```

Legacy flags such as `--dataset`, `--provider`, and `--judge-config` are
translated into an in-memory compatibility Suite and emit deprecation notices.

## Canonical Internal Data Flow

```text
External dataset
  → DatasetLoaderPlugin
  → EvaluationSuite / EvalCase
  → Suite compiler and preflight
  → CompiledSuite
  → ProviderPlugin isolated Runtime
  → canonical ExecutionResult
  → configured Pipeline Stages
  → EvaluationRunResult
  → read-only Stability / Analysis / Comparison / Gate / Report
```

The Runner receives only canonical internal models. It cannot inspect the source
format or use file names to infer behavior.

Provider plugins translate Agent-specific startup, tool injection, execution,
cleanup, exceptions, and raw outputs into canonical `ExecutionResult` evidence.
Constraint documents describe capabilities and mappings; Provider code handles
runtime interactions that cannot safely or clearly be declarative.

## Suite Compilation

`compile_suite(definition, catalog, contract_store) -> CompiledSuite` performs
all deterministic validation before runtime creation.

The compiler:

1. validates the Suite document Schema;
2. resolves every plugin and contract reference;
3. validates each plugin configuration against its descriptor Schema;
4. loads external datasets through the selected Loader;
5. converts cases to the canonical internal protocol;
6. validates capability, scope, assertion, Trace, Judge, and Gate compatibility;
7. expands document composition and inheritance;
8. records source and implementation fingerprints;
9. emits canonical JSON plus a SHA-256 identity.

`CompiledSuite` contains no unresolved paths, implicit defaults whose source is
unknown, or executable references from untrusted documents. Runtime execution
accepts a `CompiledSuite`, not a collection of loosely related paths.

## Pipeline Stages

Assertion evaluation, Trace analysis, semantic Judge execution, stability
aggregation, and future processing use a common Stage abstraction where useful.
A Stage descriptor declares:

- required input artifact types;
- produced artifact types;
- execution scope (`trial`, `case`, or `run`);
- ordering dependencies;
- failure policy;
- whether it may affect the quality conclusion;
- configuration Schema and version.

Not every helper function needs to become a plugin. Canonical hashing, schema
validation, Trial isolation, result serialization, and fixed conclusion
precedence remain kernel responsibilities. This avoids turning the architecture
into an untyped event bus.

The initial fixed lifecycle is:

```text
execute Trial
→ deterministic assertions
→ initial Trace analysis
→ optional semantic Judge
→ quality conclusion
→ Case/Run stability aggregation
→ immutable persistence
```

Configured extensions may participate only at declared extension points.

## Contract Profiles

### Assertion Profile

Moves assertion availability and scope declarations out of global constants.
Each entry references a registered rule ID and includes rule configuration,
weight, criticality, and applicable scopes. The rule plugin owns its config
Schema and evaluator implementation.

### Trace Profile

Defines event field mappings, generic lifecycle pairs, evidence reference
namespaces, and referenced Provider-specific Trace rules. Core retains only
format-independent checks such as duplicate normalized IDs and resolvable
evidence references.

### Judge Profile

Defines Judge backend ID, model configuration names, Rubric, Prompt version,
output Schema, retry and timeout behavior, and required/optional semantics.
Secrets remain environment or secret-store inputs and are never embedded in the
Profile or result.

### Report Profile

Defines assertion labels, scenario labels, investigation-area labels, language,
and enabled sections. Complex rendering remains trusted renderer code. A Profile
cannot execute templates containing arbitrary Python.

### Gate Policy

References registered metric or Gate Check IDs. The Gate engine retains the
fixed conclusion precedence:

1. invalid required comparison;
2. review required due to missing or insufficient evidence;
3. explicit threshold or zero-tolerance failure;
4. pass.

## Migration of Current Hard Coding

### Assertions

Split `assertions.py` into an engine, registry contracts, and built-in rule
plugins. Move `ASSERTION_SCOPES` to descriptors or Assertion Profiles. Preserve
existing rule IDs and results during migration.

### Reporting

Keep structured rendering logic in a renderer plugin. Move assertion labels,
scenario labels, execution labels, and investigation-area labels into versioned
Report Profiles. Machine JSON remains the stable interface.

### Gates

Keep precedence, audit records, and result composition in the Gate engine. Move
individual metric checks into registered Gate Check implementations referenced
by Policy.

### Trace

Keep normalized structural validation in core. Move lifecycle vocabularies and
Agent-specific sequencing into Trace Profiles and Trace Rule plugins.

### CLI and Composition

Remove direct construction of `DeepSeekJudgeClient` and hard-coded default
Provider imports from CLI execution paths. Built-ins register through the same
Catalog used by project plugins.

### Runner

Remove concrete Judge and Provider branches after the Pipeline path reaches
behavioral equivalence. The deprecated model-client-factory wrapper may remain
only as a compatibility adapter outside the kernel.

## Initial Built-In Plugins

Existing behavior is first wrapped as:

- `legacy_jsonl_eval_case_v1`
- `mini_agent_provider_v1`
- `builtin_assertions_v1`
- `generic_trace_v1`
- `deepseek_judge_v1`
- `markdown_report_v1`
- `release_gate_v1`

These identifiers are stable compatibility names, not special cases in the
kernel.

## Failure Model

### Preflight

Compilation returns all independently detectable issues in one report. Stable
codes cover at least:

- missing or incompatible plugin;
- invalid plugin configuration;
- invalid Loader output;
- unknown assertion, Trace, Judge, renderer, or Gate rule ID;
- Provider and Capability Bundle incompatibility;
- invalid document composition;
- source, descriptor, or compiled fingerprint mismatch.

No Agent Runtime is created when compilation fails.

### Runtime

- Provider or Agent failure is isolated to the current Trial.
- Assertion or Trace plugin exceptions are Evaluator Errors.
- Judge failure follows the compiled required/optional policy.
- Cleanup failure remains explicit evidence.
- Reporting, analysis, comparison, and gates operate on saved immutable input.
- No downstream command rewrites `results.json`.

## Provenance and Reproducibility

Every formal run records:

- `compiled_suite_sha256`;
- expanded Suite snapshot;
- every source contract ID, version, and SHA-256;
- every Plugin Descriptor ID, version, and implementation fingerprint;
- Provider, Agent, model, Judge, assertion, Trace, report, and gate identities;
- dataset Loader identity and source dataset hashes.

Comparability checks use these identities rather than assuming two matching
paths mean the same contract.

## Security Boundary

- Constraint documents are untrusted data and never execute code.
- Only trusted, explicitly registered plugins execute.
- Config Schemas reject extra fields.
- File references are resolved inside declared roots and cannot escape them.
- Environment secrets never appear in compiled Suite snapshots or reports.
- Plugin identity and implementation fingerprints are visible in artifacts.
- Dynamic Entry Point discovery is not enabled in this phase.

## Compatibility

- Existing JSONL and Manifest formats continue through the legacy Loader.
- Existing CLI flags compile an in-memory compatibility Suite.
- Historical `results.json`, legacy Case paths, and adjudication records remain
  readable.
- Existing public Python APIs remain during a deprecation window.
- New and compatibility execution paths must produce equivalent canonical
  results for the same fixture before a legacy branch is removed.

## Testing Strategy

### Contract tests

- strict Plugin Descriptor, Suite, Profile, and Compiled Suite Schemas;
- canonical expansion and deterministic fingerprints;
- invalid IDs, versions, configs, paths, and hashes fail preflight;
- documents cannot reference arbitrary executable modules.

### Plugin conformance tests

Reusable suites validate every Provider, Loader, Judge, Assertion, Trace,
Renderer, and Gate Check implementation against its protocol.

### Architecture guard tests

- kernel modules cannot import concrete Provider or Judge packages;
- Runner cannot branch on Provider ID, dataset format, assertion ID, or Judge ID;
- CLI cannot directly instantiate a concrete backend;
- dataset files cannot specify module paths or executable commands.

### Compatibility tests

- legacy and compiled Suite paths produce equivalent fixture results;
- historical result and adjudication loading remains supported;
- existing default offline suite stays green.

### Extension acceptance tests

- add a fixture Agent plugin without modifying kernel source;
- add a YAML or third-party dataset Loader without modifying Runner;
- replace Judge backend only through Judge Profile and Catalog registration;
- add assertion and Gate Check IDs without editing their engines;
- remove a referenced plugin and receive a stable preflight error.

## Acceptance Criteria

The architecture is complete when:

1. `run --suite` compiles and runs a frozen Suite.
2. Current mini_agent/JSONL/DeepSeek behavior runs through plugins.
3. A second fixture Agent and a second dataset format integrate with zero kernel
   changes.
4. Assertion, Trace, Judge, report, and gate selection is document-driven.
5. Core modules contain no concrete Agent or Judge imports and no business rule
   ID branches.
6. Compiled Suite fingerprints are deterministic and persisted.
7. Unknown or incompatible references fail before Runtime creation.
8. Existing CLI and saved-result compatibility tests pass.
9. All default tests remain offline; paid smoke tests stay opt-in.
10. No CI workflow is added in this phase.

## Explicit Non-Goals

- arbitrary Python or shell execution from Suite documents;
- a general-purpose expression language embedded in YAML or JSON;
- automatic plugin discovery from untrusted environments;
- distributed execution or a hosted control plane;
- HTML dashboards;
- CI workflow implementation.

## Expected Repository Shape

```text
src/eval_framework/
  kernel/
  contracts/
  plugins/
  compilation/
  compatibility/

plugins/<agent_or_extension>/
contracts/<agent_or_suite>/
suites/<suite_name>/
tests/plugins/<agent_or_extension>/
```

The exact module moves are chosen by the implementation plan. Migration should
prefer small compatibility-preserving extractions over a single large rewrite.
