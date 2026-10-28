"""Machine-configured suite discovery and runtime definition."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .builtin_plugins import register_capability_adapter
from .candidate_protocol import build_candidate_protocol
from .capability_bundle import load_validated_bundle
from .capability_ir import CapabilityIR, CapabilitySelection
from .capability_profiles import load_trusted_profile
from .plugins import PluginKey
from .policies import (
    PolicySet,
    load_policy_set,
    validate_kernel_policy_compatibility,
)
from .resources import resource_root
from .suite_config import PathReference, SuiteConfig, load_suite_config_file

ROOT = resource_root()
SUITES_ROOT = ROOT / "suites"


def resolve_path_reference(
    reference: PathReference,
    *,
    builder_root: Path = ROOT,
    suite_dir: Path,
) -> Path:
    bases = {
        "builder_root": builder_root,
        "projects_root": builder_root.parent,
        "suite_dir": suite_dir,
    }
    if reference.base == "projects_root":
        # Historical suite JSON is hash-bound. Translate its project anchor at
        # the filesystem boundary without rewriting those source documents.
        monorepo = builder_root.parent.parent
        projects = {
            "mini_agent": monorepo / "examples/mini_agent",
            "agent_evaluator": monorepo / "packages/evaluator",
            "agent_dataset_builder": builder_root,
        }
        parts = Path(reference.path).parts
        if (
            builder_root.parent.name == "packages"
            and (monorepo / "examples").is_dir()
            and parts
            and parts[0] in projects
        ):
            return projects[parts[0]].joinpath(*parts[1:]).resolve()
    return (bases[reference.base] / reference.path).resolve()


def discover_suite_configs(suites_root: Path = SUITES_ROOT) -> dict[str, Path]:
    discovered: dict[str, Path] = {}
    if not suites_root.is_dir():
        raise FileNotFoundError(f"suites directory missing: {suites_root}")
    suite_dirs = sorted(path for path in suites_root.iterdir() if path.is_dir())
    for suite_dir in suite_dirs:
        config_path = suite_dir / "suite.json"
        if not config_path.is_file():
            raise FileNotFoundError(f"suite config missing: {config_path}")
        config = load_suite_config_file(config_path)
        suite_id = config.metadata.suite_id
        if suite_id in discovered:
            raise ValueError(
                f"duplicate suite_id {suite_id!r}: "
                f"{discovered[suite_id]} and {config_path}"
            )
        discovered[suite_id] = config_path
    return discovered


@dataclass(frozen=True)
class SuiteDefinition:
    config: SuiteConfig
    suite_dir: Path
    coverage_plan_path: Path
    seed_catalog_path: Path
    source_files_resolved: tuple[Path, ...]
    suggested_freeze_path: Path
    eval_case_schema_path: Path
    candidate_type: type[BaseModel]
    batch_type: type[BaseModel]
    capability_bundle_path: Path
    authoritative_source_files: tuple[Path, ...] = ()
    policy_set: PolicySet | None = None

    @property
    def candidate_protocol_config(self):
        assert self.policy_set is not None
        return self.policy_set.generation.config.candidate_protocol

    @property
    def compilation_config(self):
        assert self.policy_set is not None
        return self.policy_set.generation.config.compilation

    @property
    def validation_config(self):
        assert self.policy_set is not None
        return self.policy_set.validation.config.validation

    @property
    def coverage_config(self):
        assert self.policy_set is not None
        return self.policy_set.coverage.config

    @property
    def quality_policy(self):
        assert self.policy_set is not None
        return self.policy_set.validation.config.quality

    @property
    def policy_bindings(self) -> tuple[dict[str, str], ...]:
        assert self.policy_set is not None
        output = []
        for kind in (
            "source",
            "coverage",
            "generation",
            "validation",
            "review",
            "freeze",
        ):
            reference = getattr(self.config.policies, kind)
            policy = getattr(self.policy_set, kind)
            policy_path = resolve_path_reference(
                reference, suite_dir=self.suite_dir
            )
            schema_path = ROOT / "schemas" / "policies" / f"{kind}_policy.schema.json"
            output.append(
                {
                    "kind": kind,
                    "version": policy.policy_version,
                    "path": f"{reference.base}:{reference.path}",
                    "sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
                    "schema_sha256": hashlib.sha256(
                        schema_path.read_bytes()
                    ).hexdigest(),
                }
            )
        return tuple(output)

    @property
    def suite_id(self) -> str:
        return self.config.metadata.suite_id

    @property
    def dataset_version(self) -> str:
        return self.config.metadata.dataset_version

    @property
    def target_agent(self) -> str:
        return self.config.metadata.target_agent

    @property
    def test_scope(self) -> str:
        return self.config.metadata.test_scope

    @property
    def target(self) -> str:
        return self.config.metadata.target

    @property
    def prompt_version(self) -> str:
        return self.config.metadata.prompt_version

    @property
    def source_file_names(self) -> tuple[str, ...]:
        return tuple(path.name for path in self.source_files_resolved)

    @property
    def source_files(self) -> tuple[Path, ...]:
        return self.authoritative_source_files + self.source_files_resolved

    @property
    def coverage_plan(self) -> dict[str, Any]:
        return json.loads(self.coverage_plan_path.read_text())

    @cached_property
    def capability_profile(self):
        return load_trusted_profile(
            "capability-snapshot",
            "3.0",
            ROOT / "protocol_profiles" / "trust_store.json",
        )

    @cached_property
    def validated_capability_bundle(self):
        bundle = load_validated_bundle(
            self.capability_bundle_path, self.capability_profile
        )
        expected = self.config.capability_input.bundle_hash
        if bundle.capability_bundle_sha256 != expected:
            raise ValueError(
                "Suite capability bundle hash mismatch: "
                f"expected {expected}, found {bundle.capability_bundle_sha256}"
            )
        return bundle

    @cached_property
    def capability_adapter_registration(self):
        profile_adapter = self.capability_profile.profile.adapter
        registry = register_capability_adapter()
        return registry.resolve_registration(
            PluginKey(
                "capability_adapter",
                profile_adapter.protocol,
                profile_adapter.version,
            )
        )

    @cached_property
    def capability_ir(self) -> CapabilityIR:
        capability = self.config.capability_input
        selection = CapabilitySelection(
            scope_or_chain_id=capability.scope_or_chain_id,
            intent_id=capability.intent_id,
            tool_id=capability.tool_id,
        )
        adapter = self.capability_adapter_registration.plugin
        return adapter.convert(
            self.validated_capability_bundle,
            selection,
            self.capability_profile,
        )

    @property
    def compiler(self):
        from .intent_compiler import compile_intent_candidates

        return compile_intent_candidates

    @property
    def validators(self):
        from .intent_validation import validate_module_intent_contract

        return (validate_module_intent_contract,)


def _require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def _assemble_suite(config_path: Path) -> SuiteDefinition:
    config = load_suite_config_file(config_path)
    suite_dir = config_path.parent

    def resolve(reference: PathReference) -> Path:
        return resolve_path_reference(reference, suite_dir=suite_dir)

    source_files = tuple(
        _require_file(resolve(reference), "source-pack file")
        for reference in config.paths.source_files
    )
    coverage_plan_path = _require_file(
        resolve(config.paths.coverage_plan), "coverage plan"
    )
    seed_catalog_path = _require_file(
        resolve(config.paths.seed_catalog), "seed catalog"
    )
    freeze_output = resolve(config.paths.freeze_output)
    if not freeze_output.parent.is_dir():
        raise FileNotFoundError(f"freeze output parent missing: {freeze_output.parent}")
    eval_case_schema_path = _require_file(
        resolve(config.paths.eval_case_schema), "EvalCase schema"
    )

    capability_bundle_path = resolve(config.capability_input.bundle)
    if not capability_bundle_path.is_dir():
        raise FileNotFoundError(
            f"capability bundle root missing: {capability_bundle_path}"
        )

    policy_set = load_policy_set(config.policies, suite_dir=suite_dir)
    validate_kernel_policy_compatibility(
        policy_set,
        source_references=config.paths.source_files,
    )
    candidate_config = policy_set.generation.config.candidate_protocol
    compilation = policy_set.generation.config.compilation
    if compilation.execution.tool_profile not in config.execution_profiles:
        raise ValueError(
            "policy compilation tool_profile is not declared by the Suite"
        )
    protocol = build_candidate_protocol(config, candidate_config)

    return SuiteDefinition(
        config=config,
        suite_dir=suite_dir,
        coverage_plan_path=coverage_plan_path,
        seed_catalog_path=seed_catalog_path,
        source_files_resolved=source_files,
        suggested_freeze_path=freeze_output,
        eval_case_schema_path=eval_case_schema_path,
        candidate_type=protocol.candidate_type,
        batch_type=protocol.batch_type,
        capability_bundle_path=capability_bundle_path,
        policy_set=policy_set,
    )


def load_suite(suite_id: str) -> SuiteDefinition:
    discovered = discover_suite_configs()
    try:
        config_path = discovered[suite_id]
    except KeyError as exc:
        raise ValueError(f"unknown suite {suite_id!r}") from exc
    return _assemble_suite(config_path)


def load_suite_from_path(config_path: Path) -> SuiteDefinition:
    """Load a portable Suite without registering it in the built-in catalog."""

    return _assemble_suite(config_path.resolve())
