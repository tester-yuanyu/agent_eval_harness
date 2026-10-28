# Capability Snapshot Protocol v3 — Final Implementation TODO

## 1. Goal

Capability Snapshot v3 makes the Agent's configured capabilities complete,
truthful, composable, and machine-readable without moving dataset generation,
coverage planning, fixtures, scoring, or judging into `mini_agent`.

The canonical Builder flow is:

```text
Scope / Chain requirements
+ Intent capability
+ optional registered Tool capability
+ Suite coverage requirement
→ recursively resolve the one-way capability DAG
→ compute Resolved Capability Graph status
→ build Source Pack
→ expand Coverage Slots
→ generate EvalCaseV2
```

The Agent exports capability facts. Suite declares what to evaluate and how
much coverage is required. Builder resolves and combines facts but never
invents business rules.

## 2. Binding principles

- Scope and Chain describe requirements, boundaries, completion conditions,
  and Evidence. They do not declare the final support status of a future
  combination.
- Builder computes `supported`, `unsupported`, or `unknown` only after resolving
  Scope/Chain, Intent, optional Tool, and Module capabilities.
- An absent fact is `unknown`; it must never be inferred as supported.
- `required_tool_name` states an Intent requirement. `tool_refs` states which
  matching Tools are actually registered in this bundle. They are not
  interchangeable.
- Tool snapshots exist only for registered Tools. Export must not manufacture a
  Tool snapshot from an Intent requirement.
- Evaluation adapters are real members of the exported runtime configuration,
  explicitly identified as evaluation implementations. They do not prove a
  production integration exists.
- Fixture rows, deterministic return values, and fault-trigger data remain in
  Evaluator fixtures, not capability snapshots.
- The graph is a one-way DAG. Builder may construct reverse indexes in memory,
  but reverse relationships are never written back into Tool snapshots.
- v2 remains immutable. v3 uses `snapshot_format_version: "3.0"` and has its own
  schemas, bundle root, hashes, validator, and Builder parser.
- One dataset binds exactly one capability bundle version and hash.
- Do not export Tool × Scope or Tool × Chain combination snapshots.

## 3. Canonical composition

| Evaluation target | Snapshot roots selected by Suite |
|---|---|
| QueryUser understanding | `scope.understanding` + `intent.query_user`; recursively load its registered Tool when required |
| QueryUser context | `scope.context` + `intent.query_user` + optional `tool.query_user_info` |
| QueryUser critical chain | selected critical Chain + `intent.query_user` + optional registered Tool |
| QueryUser end to end | generic end-to-end Chain + `intent.query_user` + optional registered Tool |
| Other Tool end to end | generic end-to-end Chain + corresponding Intent + registered Tool |

Tool is optional at the protocol level. A Scope/Chain resolution that requires
an unavailable Tool must resolve to `unsupported` or `unknown` according to the
declared requirement, never silently continue.

## 4. One-way reference graph

```text
Agent
├── Scope
│   ├── Module
│   ├── Evidence
│   └── Boundary
├── Chain
│   ├── Module
│   ├── Evidence
│   └── Boundary
├── Module
├── Intent
│   └── Tool (optional, registered configuration only)
└── Tool
```

Rules:

- Agent is the only root entry.
- Scope and Chain may declare Tool requirements or injectable Tool roles, but
  generic definitions do not bind to one concrete Tool.
- Tool has no reverse references to Intent, Module, Scope, or Chain.
- Every strong reference contains ID, type, relative POSIX path, format
  version, contract version, and SHA-256.
- Absolute paths, `..`, duplicate IDs, dangling references, and cycles are
  invalid.

## 5. Snapshot and contract types

### P0 — Preserve and correct existing types

- [ ] Preserve Agent, Module, Intent, and Tool snapshot concepts in v3.
- [ ] Generate every Intent from the configured `IntentRegistry`.
- [ ] Generate every Tool from the configured `ToolRegistry` only.
- [ ] Replace generic placeholder Module claims with versioned runtime facts.
- [ ] Describe real Module inputs, outputs, dependencies, state access, stop
      nodes, failure modes, recovery, operations, and trace events.
- [ ] Aggregate Agent support using required dependency closure, not “any child
      says supported”.
- [ ] Reject a supported parent when any required child is unsupported or
      unresolved.
- [ ] Preserve unsupported and unknown facts with explicit reasons.

### P0 — Add Scope snapshots

- [ ] Add `scope` snapshot type and strict JSON Schema.
- [ ] Export the five generic scopes: `understanding`, `context`,
      `planning_execution`, `safety_recovery`, and `result`.
- [ ] Each Scope declares required nodes/capabilities, inputs, outputs,
      entrypoint, stop boundary, permitted modules, prohibited modules,
      required Evidence, completion condition, and unresolved behavior.
- [ ] Scope does not contain a resolved final support status.
- [ ] Context requirements cover inheritance, override/correction,
      cancellation, session isolation, residual-state handling, and cleanup;
      each behavior absent from runtime is declared as an unmet or unknown
      requirement, not supported.

### P0 — Add Chain snapshots

- [ ] Add `chain` snapshot type and strict JSON Schema.
- [ ] Support critical chains containing two or three consecutive capability
      layers.
- [ ] Add one reusable generic end-to-end Chain spanning all applicable layers.
- [ ] Declare ordered nodes, dependencies, state transitions, normal branches,
      error branches, early stops, terminal conditions, and Evidence.
- [ ] Declare injectable Intent/Tool capability roles rather than binding the
      generic Chain to one Tool.
- [ ] Chain does not contain a resolved final support status.
- [ ] Do not enumerate every possible Scope/Tool or Chain/Tool combination.

### P0 — Add Evidence contracts

- [ ] Add a reusable, hash-addressed Evidence artifact type and JSON Schema.
- [ ] Define Evidence ID, producer, consumer, production timing, payload
      schema, observation interface, required/optional status, and applicable
      result paths.
- [ ] Cover at least intent output, Tool request/result/error/timeout Trace,
      confirmation/permission/recovery events, state observation, and final
      response where the runtime genuinely emits them.
- [ ] Do not list event types that the runtime cannot emit.

### P0 — Add Boundary contracts

- [ ] Add a reusable, hash-addressed Boundary artifact type and JSON Schema.
- [ ] Define entry node, stop node, allowed modules, prohibited modules,
      terminal condition, required Evidence, and no-overrun rule.
- [ ] Represent intent-only, single-layer, critical-chain, Tool-chain, and
      end-to-end boundaries without embedding scoring logic.

## 6. Intent snapshots

- [ ] Export parameter JSON Schema, aliases, semantics, completeness rules,
      ambiguity/conflict/invalid-input decisions, formal statuses, and next
      actions for every registered Intent.
- [ ] Explicitly declare unsupported batch, multi-condition, modification,
      cancellation, and Context behavior where applicable.
- [ ] Keep `required_tool_name` even when no matching Tool is registered.
- [ ] Set `tool_refs=[]` in the default zero-Tool bundle.
- [ ] Add `tool.xxx` only when that exact Tool is registered in the supplied
      ToolRegistry.
- [ ] Never create Tool files or references from `required_tool_name` alone.
- [ ] Validate that every non-empty Tool reference resolves within the same v3
      bundle.

## 7. Tool snapshots

- [ ] Export name, version, description, implementation profile, registration
      fact, function Schema, parameter semantics, combination rules, batch
      behavior, and preconditions.
- [ ] Export structured success, empty, business-failure, validation-error,
      timeout, rate-limit, execution-failure, partial-success, and async
      protocols. Missing protocols are unknown or unsupported, not invented.
- [ ] Export permission, confirmation, risk, side effects, idempotency, retry
      eligibility/limits/stops, and observable Evidence.
- [ ] Evaluation Tools declare `implementation_profile:
      evaluation_adapter`, simulator protocol/version, supported simulated
      result categories, and observation interface.
- [ ] Do not include fixture users, fixture gifts, concrete responses, or
      fault-trigger inputs.
- [ ] Do not write reverse references into Tool snapshots.

## 8. Evaluation adapter configuration

- [ ] Keep the default ToolRegistry and default bundle empty unless the running
      application explicitly registers Tools.
- [ ] For QueryUser Tool-chain or end-to-end evaluation, explicitly register a
      versioned `query_user_info` evaluation adapter.
- [ ] Export that configured runtime to a separate v3 bundle; only this bundle
      may contain `tool.query_user_info` and the corresponding Intent reference.
- [ ] Reuse the same IntentRegistry and ToolRegistry for execution and export.
- [ ] Keep deterministic data and fault selection in an Evaluator-owned,
      case-isolated fixture.
- [ ] Bind Builder/Evaluator to the configured bundle hash and reject fallback
      to the default bundle.

## 9. Resolved Capability Graph

Builder, not the Agent exporter, computes the resolved graph:

```text
Scope/Chain requirements
+ resolved Intent facts
+ optional resolved Tool facts
+ required Module facts
→ supported | unsupported | unknown
```

- [ ] Define structured requirement predicates and dependency roles in v3.
- [ ] Define deterministic three-state resolution rules.
- [ ] `unsupported` wins when a required capability is explicitly unsupported.
- [ ] Otherwise unresolved/missing required facts produce `unknown`.
- [ ] `supported` requires every mandatory dependency and Evidence contract to
      resolve as supported and compatible.
- [ ] Return structured diagnostics containing requirement ID, source snapshot,
      missing/incompatible dependency, and resolution path.
- [ ] Suite consumes this result but cannot override it with business rules.

## 10. Exporter

- [ ] Add a v3 exporter driven by the supplied runtime registries and a
      versioned Module/Scope/Chain catalog tied to real entrypoints.
- [ ] Produce deterministic ordering and canonical JSON.
- [ ] Generate one SHA-256 per artifact and one root bundle hash.
- [ ] Remove stale artifacts during a complete export; never retain removed
      runtime capabilities silently.
- [ ] Support an explicit diff report for added, removed, and changed IDs.
- [ ] Keep v2 export behavior unchanged.
- [ ] During migration, write v3 to a separate root such as
      `capabilities-v3/`; do not place v3 artifacts inside the v2 bundle.

## 11. Validator

- [ ] Validate every v3 Schema, artifact Hash, and root bundle Hash.
- [ ] Validate ID/type/path/version consistency and root containment.
- [ ] Validate duplicate IDs, dangling references, cycles, and illegal reverse
      Tool references.
- [ ] Validate Evidence and Boundary references and payload contracts.
- [ ] Validate Scope/Chain requirements without pre-resolving them as
      universally supported.
- [ ] Validate dependency-aware Agent/Module support aggregation.
- [ ] Validate Intent requirements separately from registered Tool references.
- [ ] Validate evaluation adapter metadata without treating it as production.
- [ ] Reject mixed v2/v3 strong references unless a future explicit
      compatibility rule authorizes the exact pair.

## 12. v2/v3 isolation and compatibility

- [ ] Freeze all existing v2 Schemas and semantics.
- [ ] Use new v3 model classes and Schema files; do not broaden v2 unions.
- [ ] Require every v3 root and child to use format version `3.0`.
- [ ] Select Builder parser from the root snapshot version.
- [ ] Never interpret a v2 artifact using the v3 parser or vice versa.
- [ ] Permit v2 and v3 bundles to coexist as separate directories during
      migration.
- [ ] Require each Suite/dataset manifest to bind exactly one format version,
      root snapshot Hash, and bundle Hash.
- [ ] Define compatibility metadata only for contract evolution within v3;
      cross-major compatibility is unsupported until explicitly specified.

## 13. Builder/Suite boundary

Suite may declare only:

- Scope or Chain snapshot ID;
- target Intent and optional Tool snapshot IDs;
- coverage dimensions, minimum counts, and dataset scale;
- fixture/profile selection owned by the evaluation project.

Builder owns recursive resolution, compatibility checks, Source Pack assembly,
Coverage Slot expansion, EvalCaseV2 generation, and reverse indexes.

Builder must not:

- read Agent source, prompts, or live runtime objects;
- manufacture Tool or Intent semantics;
- convert unknown facts into supported facts;
- write reverse relationships back into snapshots;
- silently substitute another bundle.

## 14. Implementation order

### Phase A — Truthful v3 foundation

- [ ] Freeze v2 behavior with regression tests.
- [ ] Add v3 envelopes, reference types, Schemas, and separate output root.
- [ ] Replace placeholder Module facts and dependency-blind Agent aggregation.
- [ ] Add validation tests proving false support claims are rejected.

### Phase B — Reusable evaluation topology

- [ ] Add Evidence and Boundary artifacts.
- [ ] Add five Scope requirement snapshots.
- [ ] Add critical and generic end-to-end Chain requirement snapshots.
- [ ] Add DAG, cycle, and reference-closure validation.

### Phase C — Composition and configured Tools

- [ ] Add Resolved Capability Graph rules and structured diagnostics.
- [ ] Preserve optional Intent→Tool references.
- [ ] Add one explicitly registered QueryUser evaluation adapter if QueryUser
      Tool-chain/E2E evaluation is required.
- [ ] Prove default and configured bundles cannot be confused.

### Phase D — Builder contract and migration

- [ ] Publish the v3 consumption contract and composition examples.
- [ ] Add cross-project fixtures/contract tests with Builder.
- [ ] Bind Suite and dataset manifests to one bundle version and Hash.
- [ ] Add bundle diff and affected-combination reporting.

## 15. Acceptance criteria

- [ ] v2 files and validation outputs remain unchanged.
- [ ] v3 has strict schemas for Agent, Module, Intent, Tool, Scope, Chain,
      Evidence, Boundary, and references.
- [ ] `agent.json` is the sole v3 root.
- [ ] Every configured Module, Intent, and registered Tool has one truthful
      snapshot.
- [ ] The default v3 bundle contains zero Tools and empty Intent Tool refs.
- [ ] A configured QueryUser bundle contains `tool.query_user_info` only after
      explicit adapter registration.
- [ ] Scope/Chain contain requirements but no precomputed universal support
      verdict.
- [ ] Resolver produces deterministic supported/unsupported/unknown outcomes
      with diagnostics.
- [ ] Generic end-to-end Chain composes with multiple Intent/Tool pairs without
      generating combination snapshots.
- [ ] Evaluation adapter snapshots contain no fixture data.
- [ ] All references form a valid one-way DAG with reproducible hashes.
- [ ] Builder can construct Source Pack without reading Agent source or adding
      business rules.
- [ ] Full offline tests, Ruff, v2 validation, v3 default validation, and v3
      configured-bundle validation pass.

## 16. Explicit non-goals

- Dataset generation, expected answers, Judge, scoring, and reports inside the
  Agent repository.
- Production business integrations disguised as evaluation adapters.
- Concrete Mock data or deterministic case responses in capability snapshots.
- Tool × Scope or Tool × Chain materialized combination snapshots.
- Silent v2-to-v3 reinterpretation or cross-major references.
- Declaring currently absent Context, async, partial-success, retry, permission,
  or recovery behavior as supported merely to make a Suite resolvable.
