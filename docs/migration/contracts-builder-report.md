# Shared contracts and Builder migration

Task 2 is implemented. Originals were read only; no live model/API calls or `.env` reads were used. No commits or staging were performed by this worker.

## Package and API boundaries

- Distribution: `agent-eval-contracts==0.1.0`; dependencies: Pydantic 2, jsonschema 4, referencing, PyYAML 6. No OpenAI, Inspect, Builder, evaluator, Agent runtime, or trace SDK dependency.
- Namespace `capability_snapshot_kit` moved byte-for-byte from the imported mini_agent source into `packages/contracts/src`. Existing v3 compiler, loader, validator, hashing, resolution, diff, ingestion and `python -m capability_snapshot_kit` APIs are preserved. The distribution also exposes the `capability-snapshot` console script. Markdown extraction/profile resources are packaged.
- Namespace `eval_contracts` exports `DatasetLoadError`, `load_dataset`, `load_jsonl_dataset`, `validate_dataset`. Public shared modules: `schemas`, `schema_base`, `capabilities`, `capability_loader`, `tool_catalog`, `dataset_loader`, `dataset_validator`, `phase2_schemas`, `errors`, `evidence_requirements`.
- Only data definitions are shared from execution-adjacent modules: `assertions.ASSERTION_SCOPES`; `diagnostic_metrics.{ConversationMetricConfig,DiagnosticMetricResult,DiagnosticMetricSummary}`; `observation_assertions.{ObservationPredicate,ObservationCheckConfig,validate_schema_references}` and its local schema traversal; `turn_assertions.{TurnToolExpectation,TurnExpectation,TurnCheckConfig}`; `sources.ResolvedSource`.
- Evaluator historical modules alias the shared modules; execution-adjacent files re-export the same class objects. Existing evaluator APIs retain model identity, error identity and private helper access. Actual scoring/execution functions remain in evaluator.
- Builder now imports only `eval_contracts` for shared data validation. Its `CapabilityIR` and generation models stay internal. Builder keeps OpenAI `<3`; evaluator keeps its separate bounds. Direct comparison generation no longer imports optional DeepEval eagerly. Explicit DeepEval generation still imports its real SDK.
- Mini_agent packaging dependency was coordinated with evaluator worker. Its legacy `scripts/build_snapshot_kit.py` stages the shared canonical source, preserving the standalone build helper.

## Resources and frozen inputs

Historical suite JSON remains unchanged. `projects_root` legacy anchors resolve `mini_agent/...` to `examples/mini_agent/...` and `agent_evaluator/...` to `packages/evaluator/...` in the monorepo. Generic declared-base path behavior remains unchanged outside that layout.

Builder wheel builds copy `schemas`, `suites`, `policies`, and `protocol_profiles` into package resources. Runtime resource lookup supports both editable source and an installed wheel. A custom Suite works outside the checkout. Built-in mini_agent suites also need the repository's example capability/data files; this is documented in the Builder README. The development instructions now use root `make setup` and the independent Builder environment.

The imported snapshot kit plus Builder suite/policy/profile/schema files were compared against `.migration/baseline`: **115 files byte-identical**. An additional **756 manifest-bound fixture files** were copied into `packages/dataset-builder/tests/fixtures`, preserving every SHA256. Exact origin, destination and digest are in `builder-fixture-provenance.json`:

- `full_tools_fixture_v1_full_eval_20261020`: 253 files.
- `nanobot_full_eval_20261023`: 263 files.
- `nanobot_snapshot_v3`: 128 files.
- `nanobot_snapshot_handoff_v2`: 112 files.

These are the minimum manifest-bound sets: existing loaders verify every listed file, so pruning files or editing manifests would break the historical contract. No unrelated workspace runs were copied. Tests no longer read the original projects or the original Desktop/nanobot paths. Frozen fixture contents may contain historical provenance strings; these are data and are not executed as paths.

Builder additionally requires tracked example assets `examples/mini_agent/exports/trace_v1/**`, `exports/full_tools_fixture_v1/**`, and `exports/customer_service_v1/**`, already communicated to the coordinator.

## Verification

- Tests first: contracts isolation test initially failed because `eval_contracts` did not exist, then failed on old suite roots, then passed. It blocks imports of `eval_framework`, `minimal_agent`, and `inspect_ai`, generates a scripted draft, validates it, and confirms an unsupported evidence requirement is rejected by Builder's evaluator gate.
- Final default Builder suite: **353 passed, 5 skipped**, 82.76 seconds (`.migration/builder-final.log`). The 5 skips are optional DeepEval SDK tests. The original complete baseline had 357 tests with that optional dependency present; migration adds one resource distribution regression. No business-required tests are skipped.
- Contracts suite: **1 passed** in the clean Builder environment.
- Resource build regression builds package files into a temporary directory, imports outside the source checkout and verifies suite discovery and trusted profile/schema loading.
- A real `agent_dataset_builder-0.1.0-py3-none-any.whl` was built with declared build dependencies, unpacked outside the repository, and successfully loaded a custom Suite, validated pinned `trace_v1` bundle Hash `61ff546b81d3969f24cde3d216f17e37b13cb87663bdcc7a6b7b80183a776544`, and constructed Builder IR (`.migration/builder-wheel.log`). `--no-deps` here is a wheel-build flag only; dependency installation was handled normally in isolated environments by the coordinator.
- Evaluator environment smoke check confirms historical/shared schema modules and ResolvedSource/diagnostic model classes are identical objects.
- Mini standalone build helper regression: **1 passed** from mini_agent package working directory.
- Builder production source, setup script, new resource test, and shared extraction files pass focused Ruff checks. Evaluator compatibility-wrapper Ruff checks pass.

Early full-suite failures were migration resource locations, missing manifest-bound fixtures, and optional SDK imports; these were repaired before the final successful run. Intermediate logs are retained privately under `.migration`.
