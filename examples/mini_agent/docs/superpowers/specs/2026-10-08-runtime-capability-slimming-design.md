# Runtime and Capability Slimming Design

## Status

Approved in conversation on 2026-10-08. This document defines the target
architecture; it does not authorize capability claims that are not backed by
the configured Agent runtime.

## Problem

`minimal_agent` currently combines three different concerns in one package:

1. the Agent runtime and its intent and tool-execution behavior;
2. capability contracts and the machine-readable capability bundle;
3. evaluation-support implementations, including fictional Shadow business
   tools, seeded Mock data, fault injection, and evaluator-oriented state.

The third concern makes the Agent look more capable than the real configured
runtime and increases the size and coupling of the package. Evaluation data,
failure scenarios, deterministic test tools, expected values, and scoring
belong to external Builder and Evaluator projects, not to the Agent.

## Goals

- Keep the Agent's intent-recognition and tool-planning runtime.
- Keep a generic, strict, observable tool-registration and execution path.
- Allow a configured Agent with registered real tools to execute the complete
  plan-call-result-answer loop.
- Let the Agent export and validate a capability bundle describing the exact
  configuration that produced it.
- Preserve public intent-only and end-to-end integration surfaces for Builder
  and Evaluator.
- Remove production code whose only purpose is to simulate evaluation
  scenarios or fictional business systems.
- Reduce top-level exports, file size, and cross-module coupling.

## Non-goals

- Building a plugin discovery system or scanning the network for tools.
- Owning evaluation cases, expected results, scoring, coverage planning,
  retries, reports, or release gates.
- Shipping fictional user, gift, pool, or backpack services.
- Keeping backward compatibility for explicitly Mock- or Shadow-named APIs.
- Replacing the external Builder or Evaluator.
- Rewriting the whole Agent when an extraction and deletion achieves the same
  boundary.

## Target Ownership

The production package has three domains:

```text
minimal_agent/
├── runtime/        # Agent loop, intent routing, model clients, tool execution, trace
├── contracts/      # Agent, Intent, Tool, result, and public error protocols
├── capabilities/   # snapshot models, construction, hashes, export, validation
├── cli.py           # composition entry point
└── __init__.py      # intentionally small stable public API
```

The final file split may follow existing import constraints, but every
production module must belong to exactly one of these responsibilities.
Compatibility re-export modules may exist only as temporary migration shims
and must not contain implementation logic.

### Runtime

Runtime owns:

- `MinimalAgent` and its bounded planning/execution loop;
- `IntentRouter` and `run_intent_only()`;
- the `ModelClient` protocol and provider adapters;
- `ToolRegistry`, `ToolDefinition`, strict argument validation, invocation,
  result handling, and generic permission checks;
- generic Trace events required to observe intent and tool execution;
- explicit errors for unavailable tools, invalid arguments, provider failure,
  execution failure, and maximum-step termination.

Runtime does not contain seeded business data, test scripts, artificial
failure modes, or tool implementations created solely to exercise a branch.

### Contracts

Contracts own the stable Pydantic protocols shared by runtime, capability
export, Builder, and Evaluator. The current seven Intent definitions remain
formal intent-recognition capabilities. Their business-specific planning
metadata can name a required tool, but naming a required tool does not prove
that the configured runtime can execute it.

Intent recognition and tool availability are separate facts:

- the Intent contract may produce `READY` and `CALL_TOOL` for a complete input;
- the execution layer may still report `TOOL_NOT_AVAILABLE` when the named
  Tool is not registered;
- only a registered Tool receives a Tool snapshot and contributes positive
  execution support to Module and Agent layers.

This preserves intent-only evaluation without fabricating end-to-end support.

### Capabilities

Capabilities own the v2 snapshot envelope, schemas, canonical hashes,
reference validation, bundle export, and bundle validation. Snapshot creation
must receive the actual `IntentRegistry` and `ToolRegistry` (or an immutable
configuration view derived from them). It must not import a hard-coded catalog
of fictional handlers.

The bundle follows these rules:

- `capabilities/agent.json` remains the only root.
- Intent snapshots are built from formal Intent contracts.
- Tool snapshots are built only from Tool definitions registered in the
  configuration being described.
- Intent `tool_refs` contains a reference only when the required Tool is in
  that same configured registry; a logical required-tool name remains Intent
  contract metadata and is not treated as an executable reference.
- Planning/execution Module layers aggregate support from the configured Tool
  set. With no registered tools, generic planning structure may be described,
  but tool execution support is `unsupported`, not `supported` or `unknown`.
- Agent summaries, parent references, and the bundle hash are recomputed from
  the same configuration in one export operation.
- Export fails if runtime configuration and emitted references disagree.

The checked-in bundle represents the repository's default composition. If the
default composition has no concrete tools, it contains no Tool snapshots and
must describe execution accordingly. A deployed composition with real tools
exports its own bound bundle.

## Runtime Data Flow

```text
input
→ IntentRouter
→ IntentResult
→ MinimalAgent planning loop
→ ModelClient selects a registered tool
→ ToolRegistry resolves and validates arguments
→ Tool handler executes
→ ToolResult returns to the model
→ final response
→ AgentResult and Trace
```

When no tools are registered, intent-only execution continues to work. A full
run must expose no tool schemas to the model and must return an explicit,
stable inability result if planning nevertheless requests an unavailable
tool. It must never substitute a Mock result.

Tool handlers may adapt HTTP APIs, MCP tools, databases, or local functions.
The Agent depends only on the Tool contract and does not special-case those
backends.

## Public Interfaces

The refactor preserves these concepts and keeps their signatures compatible
where doing so does not retain evaluation-only coupling:

- `MinimalAgent.run(...)`
- `run_intent_only(...)`
- `ToolRegistry.register(...)`
- `ToolRegistry.invoke(...)`
- `export_capability_bundle(...)`
- `validate_capability_bundle(...)`

Capability export gains an explicit configured-runtime input rather than
silently constructing fictional tools. The retained construction APIs become:

```python
def build_capability_bundle(
    intent_registry: IntentRegistry,
    tool_registry: ToolRegistry,
) -> CapabilityBundle: ...

def export_capability_bundle(
    output_root: str | Path,
    intent_registry: IntentRegistry,
    tool_registry: ToolRegistry,
) -> list[Path]: ...
```

`ToolRegistry` exposes its registered definitions as an immutable tuple for
snapshot construction. The capability layer reads Tool contract metadata but
never invokes a handler. The capability CLI explicitly constructs the default
Intent registry and an empty Tool registry before calling export; there is no
implicit Mock profile.

The top-level package exports only stable consumer interfaces. Concrete
provider adapters and internal snapshot-building helpers remain importable
from their owning modules but are not all re-exported from `minimal_agent`.

## Removed Production Responsibilities

The following are removed rather than renamed:

- `shadow_tools.py`, `shadow_write_tools.py`, and Shadow business schemas;
- `ShadowExecutionController` and Shadow confirmation/idempotency state;
- fictional users, gifts, pools, backpack grants, seed rows, and reset APIs;
- `ToolRegistry.with_mock_tools()`, `with_shadow_read_tools()`, and
  `with_shadow_tools()`;
- fault-injection modes and production branches that synthesize timeout,
  failure, or commit-then-timeout behavior;
- `ScriptedModelClient` from the production package; deterministic model
  doubles belong in test support;
- Mock/Shadow capability definitions and generated Tool snapshots;
- public exports that exist only for those responsibilities.

Generic confirmation or idempotency is retained only if the remaining Agent
runtime actually uses it independently of Shadow tools. Otherwise it is
removed and can be reintroduced with a real requirement.

## Composition

The default CLI composes an Agent with the configured model provider and no
built-in business tools. A real application registers Tool definitions before
constructing the Agent. Evaluator-controlled deterministic tools are supplied
from the Evaluator side through the same public registration interface; they
do not live in the production Agent package.

The capability bundle for an evaluation or deployment must be exported from
the same registry configuration used to run that Agent. Builder and Evaluator
must reject a bundle/configuration mismatch rather than falling back to the
checked-in bundle.

## Error Handling

- Unknown or unregistered tool: stable `TOOL_NOT_AVAILABLE` outcome.
- Invalid tool arguments: rejected before handler execution.
- Handler failure: normalized execution error plus a generic Trace event;
  internal exception details are not presented as successful tool output.
- Invalid model output or provider failure: existing typed model errors.
- Maximum planning steps reached: explicit terminal outcome.
- Snapshot reference, schema, or hash mismatch: export/validation failure with
  deterministic diagnostics.
- Intent names a required tool absent from the registry: valid intent-only
  result, unsupported execution link, and no dangling Tool reference.

No error path fabricates business data or silently converts `unsupported` or
`unknown` to `supported`.

## Migration Strategy

Migration proceeds in independently verifiable slices:

1. Pin the retained public behavior with contract tests.
2. Decouple `ToolRegistry` and `MinimalAgent` from Shadow execution types and
   fault-injection arguments.
3. Add configuration-bound capability construction and prove that zero-tool
   and one-tool bundles validate.
4. Move deterministic model and tool doubles into test support.
5. Remove Shadow/Mock production modules, schemas, SQLite structures, exports,
   generated snapshots, and their dedicated tests.
6. Split the remaining runtime, contracts, and capability responsibilities
   into focused modules and add narrow compatibility shims only where needed.
7. Regenerate the checked-in default bundle and update Builder/Evaluator
   integration documentation.
8. Run focused tests, the full suite, Ruff, and bundle validation.

Removal is complete only when no production import or generated capability
artifact depends on a deleted evaluation-support concept.

## Verification and Acceptance

The implementation is accepted when all of the following are true:

- an Agent with no registered tools completes intent-only requests;
- its bundle has no fabricated Tool snapshots or positive tool-execution
  support;
- an Agent configured with one real or test-owned Tool completes the full
  plan-call-result-answer loop;
- that configured bundle contains exactly that Tool and validates all parent
  references and hashes;
- an Intent whose logical Tool is unavailable has no dangling Tool reference;
- invalid arguments never call the handler;
- an unavailable tool never produces a Mock result;
- Builder can start at `agent.json` and consume the configured bundle;
- Evaluator can use public intent-only and end-to-end interfaces without
  importing Agent internals;
- production files, imports, exports, schemas, tests, and generated artifacts
  contain no remaining Shadow/Mock evaluation-support implementation;
- the full offline test suite and Ruff pass;
- checked-in bundle validation passes;
- production line count and top-level public exports materially decrease, with
  the before/after figures recorded in the completion report.

## Compatibility Policy

Intent-only behavior and the generic tool-registration path are retained.
Mock/Shadow constructors and data APIs are intentionally breaking removals.
Any other breaking public change must be listed in the migration notes with a
replacement import or an explicit statement that no replacement exists.
