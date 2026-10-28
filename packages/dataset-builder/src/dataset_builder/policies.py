"""Strict executable policy protocol for dataset authoring stages."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import Field

from .suite_config import (
    CandidateProtocolConfig,
    CompilationConfig,
    ConfigModel,
    CoverageConfig,
    PathReference,
    PolicyReferences,
    QualityPolicy,
    ValidationConfig,
)

PolicyKind: TypeAlias = Literal[
    "source", "coverage", "generation", "validation", "review", "freeze"
]


class SourcePolicyConfig(ConfigModel):
    allowed_source_bases: list[
        Literal["builder_root", "projects_root", "suite_dir"]
    ] = Field(min_length=1)
    unknown_capability_behavior: Literal["preserve", "reject"]
    require_hash_binding: bool


class GenerationPolicyConfig(ConfigModel):
    candidate_protocol: CandidateProtocolConfig
    compilation: CompilationConfig


class ValidationPolicyConfig(ConfigModel):
    validation: ValidationConfig
    quality: QualityPolicy
    enabled_gates: list[
        Literal[
            "evaluator",
            "capability_snapshot",
            "contract",
            "coverage",
            "duplicate",
            "leakage",
            "quality",
        ]
    ] = Field(min_length=1)


class ReviewPolicyConfig(ConfigModel):
    locale: str = Field(min_length=1)
    require_all_cases: bool
    required_fields: list[str] = Field(min_length=1)


class FreezePolicyConfig(ConfigModel):
    non_overwrite: bool
    require_frozen_bundle: bool
    versioning: Literal["explicit_new_version"]


class SourcePolicy(ConfigModel):
    policy_kind: Literal["source"]
    policy_version: Literal["1.0"]
    schema_version: Literal["1.0"]
    config: SourcePolicyConfig


class CoveragePolicy(ConfigModel):
    policy_kind: Literal["coverage"]
    policy_version: Literal["1.0"]
    schema_version: Literal["1.0"]
    config: CoverageConfig


class GenerationPolicy(ConfigModel):
    policy_kind: Literal["generation"]
    policy_version: Literal["1.0"]
    schema_version: Literal["1.0"]
    config: GenerationPolicyConfig


class ValidationPolicy(ConfigModel):
    policy_kind: Literal["validation"]
    policy_version: Literal["1.0"]
    schema_version: Literal["1.0"]
    config: ValidationPolicyConfig


class ReviewPolicy(ConfigModel):
    policy_kind: Literal["review"]
    policy_version: Literal["1.0"]
    schema_version: Literal["1.0"]
    config: ReviewPolicyConfig


class FreezePolicy(ConfigModel):
    policy_kind: Literal["freeze"]
    policy_version: Literal["1.0"]
    schema_version: Literal["1.0"]
    config: FreezePolicyConfig


PolicyEnvelope: TypeAlias = (
    SourcePolicy
    | CoveragePolicy
    | GenerationPolicy
    | ValidationPolicy
    | ReviewPolicy
    | FreezePolicy
)

POLICY_MODELS = {
    "source": SourcePolicy,
    "coverage": CoveragePolicy,
    "generation": GenerationPolicy,
    "validation": ValidationPolicy,
    "review": ReviewPolicy,
    "freeze": FreezePolicy,
}


class PolicySet(ConfigModel):
    source: SourcePolicy
    coverage: CoveragePolicy
    generation: GenerationPolicy
    validation: ValidationPolicy
    review: ReviewPolicy
    freeze: FreezePolicy


def _resolve(reference: PathReference, suite_dir: Path) -> Path:
    builder_root = Path(__file__).resolve().parents[2]
    bases = {
        "builder_root": builder_root,
        "projects_root": builder_root.parent,
        "suite_dir": suite_dir,
    }
    base = bases[reference.base].resolve()
    resolved = (base / reference.path).resolve()
    if not resolved.is_relative_to(base):
        raise ValueError("policy path escapes its declared base")
    return resolved


def load_policy(
    reference: PathReference,
    *,
    suite_dir: Path,
    expected_kind: PolicyKind,
) -> PolicyEnvelope:
    path = _resolve(reference, suite_dir)
    if not path.is_file():
        raise FileNotFoundError(f"policy file missing: {path}")
    payload = json.loads(path.read_text())
    actual_kind = payload.get("policy_kind") if isinstance(payload, dict) else None
    if actual_kind != expected_kind:
        raise ValueError(
            f"expected policy_kind {expected_kind!r}, found {actual_kind!r}: {path}"
        )
    return POLICY_MODELS[expected_kind].model_validate(payload)


def load_policy_set(config: PolicyReferences, *, suite_dir: Path) -> PolicySet:
    return PolicySet(
        **{
            kind: load_policy(
                getattr(config, kind), suite_dir=suite_dir, expected_kind=kind
            )
            for kind in POLICY_MODELS
        }
    )


def validate_kernel_policy_compatibility(
    policies: PolicySet,
    *,
    source_references: Iterable[PathReference],
) -> None:
    """Reject policy choices the built-in stable kernel cannot honor safely."""

    allowed_bases = set(policies.source.config.allowed_source_bases)
    unavailable = sorted(
        {reference.base for reference in source_references} - allowed_bases
    )
    if unavailable:
        raise ValueError(f"source base is not allowed by policy: {unavailable}")
    if policies.source.config.unknown_capability_behavior != "preserve":
        raise ValueError("unknown capability status must be preserved")
    if not policies.source.config.require_hash_binding:
        raise ValueError("source hash binding is a kernel requirement")

    review = policies.review.config
    if review.locale != "zh-CN":
        raise ValueError("built-in review renderer supports locale 'zh-CN'")
    if not review.require_all_cases:
        raise ValueError("review every case is a kernel requirement")
    rendered_fields = {
        "case_id",
        "scenario_type",
        "expected_module_output",
        "user_input",
    }
    unknown_fields = sorted(set(review.required_fields) - rendered_fields)
    if unknown_fields:
        raise ValueError(
            f"built-in review renderer cannot render fields: {unknown_fields}"
        )

    freeze = policies.freeze.config
    if not freeze.non_overwrite:
        raise ValueError("freeze non-overwrite is a kernel requirement")
    if not freeze.require_frozen_bundle:
        raise ValueError("frozen capability bundle is a kernel requirement")


def write_policy_schemas(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for kind, model in POLICY_MODELS.items():
        path = root / f"{kind}_policy.schema.json"
        path.write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
        )
