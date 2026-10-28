# Contract-Driven Plugin Foundation — Phase End Report

## Outcome

The first architecture milestone is implemented. An evaluation can now be
declared by a strict Suite document, compiled deterministically before runtime
creation, executed through explicitly registered Loader and Provider plugins,
and persisted with complete Suite/plugin/contract provenance.

## Delivered

- strict `PluginDescriptor`, `PluginReference`, `SuiteDefinition`, and
  immutable `CompiledSuite` protocols;
- exact `(kind, id, version)` `PluginCatalog` resolution with Draft 2020-12
  config validation and stable preflight errors;
- root-bounded `ContractStore`, symlink escape prevention, canonical JSON, and
  SHA-256 verification;
- JSONL and JSON-document Loader plugins that both produce `DatasetBundle`;
- two-phase Suite compilation with aggregated issues and zero Runtime creation
  on preflight failure;
- built-in mini-agent Provider registration and a compiled execution bridge;
- result and report provenance for compiled Suite, plugins, contracts, Loader,
  Provider, and dataset sources;
- preferred `validate/run --suite` CLI plus deprecated legacy-flag translation;
- a self-contained `suites/mini_agent_module_v1` example;
- AST architecture guards and offline compatibility/equivalence tests.
- explicit fingerprinting of JSONL Manifests, Capability Bundle manifests and
  their dependency closure before Loader or Provider execution;
- Provider-owned semantic preflight, path-free runtime override identity, and
  tamper detection for nested compiled-Suite state.

## Compatibility and Security

Historical JSONL/Manifest inputs, saved results, public Python APIs, and legacy
CLI arguments remain supported. Suite documents cannot import executable code;
only explicitly registered trusted implementations run. Unknown versions,
invalid config, path escape, hash mismatch, and Catalog drift fail before Agent
Runtime creation.

## Deferred Work

Milestone 2 will move Provider/Judge/Trace execution fully behind profiles and
Pipeline stages, remove the remaining direct DeepSeek CLI bridge and deprecated
Runner mini-agent adapter, and add a second fixture Agent. Milestone 3 will move
assertion selection, Trace vocabulary, report labels, and Gate checks out of
global business constants into versioned profiles and registered rules.

CI remains intentionally out of scope and no workflow was added.
