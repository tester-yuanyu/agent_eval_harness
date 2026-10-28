# Version-Neutral Capability Bridge Design

## Goal

Make the single supported Capability Snapshot implementation appear version-neutral
at every Agent-to-Builder and Agent-to-Evaluator integration boundary, while keeping
the wire-format discriminator required for safe validation.

Consumers should receive one canonical directory and one canonical set of public
entrypoints:

```text
capabilities/agent.json
minimal_agent.capabilities
```

They should not need to select a `v3` Provider, import a `.v3` module, or encode the
current protocol generation in Suite and runtime configuration.

## Current State

- Capability Protocol v2 has been removed.
- The only generated Bundle uses `snapshot_format_version: "3.0"`.
- The checked-in Bundle is currently named `capabilities-v3/`.
- The stable `minimal_agent.capabilities` facade already delegates to the current
  implementation, but active documentation still advertises explicit `.v3` modules.
- The portable Kit still exposes version-suffixed Python names.
- Builder and Evaluator consume the directory protocol independently; this repository
  does not implement their Provider, Compiler, Runner, assertions, scoring, or report
  pipeline.

## Design Decision

Separate product-facing names from wire-format identity.

### Product-facing boundary

Use unversioned names everywhere a Builder, Evaluator, Agent integrator, or another
Agent implementation interacts with the capability system:

```text
capabilities/
capabilities/agent.json
minimal_agent.capabilities
capability_snapshot_kit public aliases
```

The canonical Builder input is the complete `capabilities/` directory. Builder and
Evaluator configuration binds that directory and the root Bundle Hash; it does not
select a `v3` implementation by name.

### Wire-format boundary

Keep `snapshot_format_version: "3.0"` in every snapshot and keep the existing JSON
Schemas, contract versions, snapshot hashes, reference hashes, and Bundle Hash.

The version is data used to validate compatibility, not a product-routing label.
Removing it would make fail-closed parsing and future format evolution unsafe.

### Internal implementation boundary

Retain the existing version-suffixed implementation modules and concrete class names
internally. They remain implementation details and compatibility symbols. This avoids
a broad mechanical rewrite with no runtime value.

Add stable unversioned aliases at public package boundaries. Existing internal tests
may continue to exercise concrete versioned implementations, while consumer-facing
tests must use unversioned names.

## Canonical Artifact Layout

Rename the checked-in generated directory without changing its contents:

```text
capabilities-v3/  →  capabilities/
```

The canonical tree remains:

```text
capabilities/
├── agent.json
├── modules/
├── intents/
├── tools/
├── scopes/
├── chains/
├── evidence/
├── boundaries/
└── schemas/
```

All references inside the Bundle are relative to the Bundle root, so moving the root
directory must not change any snapshot bytes or hashes.

The old `capabilities-v3/` path is removed. No duplicate directory, symlink, fallback,
or path auto-detection is retained.

## Public Python and CLI Interfaces

The supported MiniAgent interfaces are:

```python
from minimal_agent.capabilities import (
    CapabilityBundle,
    CapabilityBundleValidationError,
    build_capability_bundle,
    build_capability_snapshot,
    export_capability_bundle,
    validate_capability_bundle,
)
```

The supported CLI is:

```bash
python -m minimal_agent.capabilities.cli export --output capabilities
python -m minimal_agent.capabilities.cli validate --input capabilities
python -m minimal_agent.capabilities.cli resolve --input capabilities --selection selection.json
python -m minimal_agent.capabilities.cli diff --old previous-capabilities --new capabilities
```

The portable Kit exposes equivalent unversioned aliases for its stable protocol
models, Adapter contract, loading, validation, resolution, diff, compilation, and
export operations. Version-suffixed symbols remain available as implementation-level
compatibility names but are not used in active consumer documentation.

## Builder Bridge

Builder receives only the complete `capabilities/` directory. Its Profile/Adapter:

1. Reads `agent.json`.
2. Uses the Bundle-provided Schemas to validate every artifact.
3. Checks `snapshot_format_version`, snapshot hashes, reference hashes, the one-way
   DAG, and `capability_bundle_sha256`.
4. Converts Agent, Scope, Chain, Module, Intent, optional Tool, Evidence, and Boundary
   snapshots into the Builder's neutral Capability IR.
5. Resolves `supported`, `unsupported`, or `unknown` without inferring undeclared
   capability facts.

Builder must not import `minimal_agent`, invoke its CLI, read `capability_specs/`, or
add `if mini_agent` branches to its Compiler.

## Evaluator Bridge

Evaluator binds the frozen dataset to the same Bundle Hash and runtime configuration
used during generation. It uses the stable Agent runtime interfaces:

- `run_intent_only` for intent-only evaluation;
- `MinimalAgent.run` for critical-chain and end-to-end evaluation;
- `IntentResult`, `AgentResult.intent_result`, `AgentResult.tool_calls`,
  `AgentResult.events`, and `AgentResult.final_response` as observable evidence.

For QueryUser tool-chain evaluation, Evaluator owns the fixture and deterministic
handler, registers `query_user_evaluation_definition(handler)`, exports a Bundle from
that same ToolRegistry, and runs the Agent with the same registry and allow-list.

The default checked-in Bundle still contains zero Tool snapshots. It cannot be used to
claim that a concrete Tool execution path is supported.

## Documentation

Rename the active protocol guide:

```text
docs/CAPABILITY_SNAPSHOT_V3.md  →  docs/CAPABILITY_SNAPSHOT.md
```

The guide describes the current protocol without advertising a selectable generation.
It may mention that the validated wire format is `3.0`, but active examples, paths,
Provider names, and imports use unversioned public interfaces.

Historical design and implementation records under `docs/superpowers/` remain
unchanged.

## Failure Rules

- Missing `agent.json`, invalid Schema, unsupported format version, invalid hashes,
  dangling references, cycles, or Bundle Hash mismatch fail closed.
- No legacy directory fallback or version inference is allowed.
- Missing declared capability semantics resolve to `unknown` only after structural
  validation succeeds.
- Builder/Evaluator runtime configuration that does not match the pinned Bundle is
  rejected before model execution.

## Verification

Tests must prove:

1. The canonical checked-in directory is `capabilities/`, and `capabilities-v3/` is
   absent.
2. Renaming the Bundle root does not change any snapshot bytes or hashes.
3. Unversioned MiniAgent API and CLI support export, validate, resolve, and diff.
4. Unversioned Kit aliases are the same concrete objects/functions as the retained
   implementation symbols.
5. Builder contract fixtures resolve Scope/Chain, Intent, optional Tool, Evidence, and
   Boundary through the canonical directory.
6. QueryUser evaluation-adapter tests still bind the same registry to execution and
   export.
7. The complete test suite and Ruff pass.

## Non-Goals

- Changing `snapshot_format_version` from `3.0`.
- Rewriting all internal classes and files to remove `V3` suffixes.
- Adding Builder or Evaluator business logic to MiniAgent.
- Adding dataset generation, fixtures, scoring, Judge, reports, or model credentials.
- Preserving the old `capabilities-v3/` directory as an alias.
