"""Immutable, approved dataset freezing."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from eval_framework import load_dataset

from .capability_bundle import ValidatedCapabilityBundle, load_validated_bundle
from .schemas import Approval, ValidationSummary
from .source_pack import sha256_bytes, sha256_file
from .suite_definition import SuiteDefinition


@dataclass(frozen=True)
class FrozenCapabilityBundleBinding:
    provider_id: str
    bundle_format_version: str
    sha256: str
    path: str
    files: list[dict[str, str]]

    def model_dump(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "bundle_format_version": self.bundle_format_version,
            "sha256": self.sha256,
            "path": self.path,
            "files": self.files,
        }


def freeze_capability_bundle(
    bundle: ValidatedCapabilityBundle,
    dataset_output: Path,
    provider_id: str,
) -> FrozenCapabilityBundleBinding:
    """Copy source-owned snapshots into a verified, portable immutable bundle."""

    file_sources = [
        (Path(relative_path), source)
        for relative_path, source in bundle.validated_files
    ]
    files = [
        {"path": relative.as_posix(), "sha256": sha256_file(source)}
        for relative, source in file_sources
    ]
    format_version = "3.0"
    portable_sha256 = bundle.capability_bundle_sha256
    relative_directory = Path("capability_bundles") / portable_sha256
    final_directory = dataset_output.parent / relative_directory
    binding = FrozenCapabilityBundleBinding(
        provider_id=provider_id,
        bundle_format_version=format_version,
        sha256=portable_sha256,
        path=relative_directory.as_posix(),
        files=files,
    )

    if final_directory.exists():
        try:
            existing = load_validated_bundle(final_directory, bundle.profile)
        except (OSError, ValueError) as exc:
            raise FileExistsError(
                "capability bundle target exists but fails integrity checks"
            ) from exc
        if existing.capability_bundle_sha256 != portable_sha256:
            raise FileExistsError(
                "capability bundle target exists with different content"
            )
        return binding

    bundle_root = final_directory.parent
    bundle_root.mkdir(parents=True, exist_ok=True)
    temporary = bundle_root / f".tmp-{portable_sha256}-{uuid4().hex}"
    temporary.mkdir()
    try:
        for relative, source in file_sources:
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        load_validated_bundle(temporary, bundle.profile)
        try:
            temporary.rename(final_directory)
        except FileExistsError:
            try:
                existing = load_validated_bundle(final_directory, bundle.profile)
            except (OSError, ValueError) as exc:
                raise FileExistsError(
                    "capability bundle target appeared with invalid content"
                ) from exc
            if existing.capability_bundle_sha256 != portable_sha256:
                raise FileExistsError(
                    "capability bundle target appeared with different content"
                ) from None
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return binding


def freeze(
    suite: SuiteDefinition,
    draft: Path,
    approval: Approval,
    output: Path,
    validation: ValidationSummary,
    generation_metadata: dict[str, object] | None = None,
) -> tuple[Path, Path, Path]:
    if not validation.valid or validation.state != "VALIDATED":
        raise ValueError("draft must pass every gate before approval")
    if approval.draft_sha256 != validation.draft_sha256:
        raise ValueError("approval hash does not match validated draft")
    draft_bundle = load_dataset(draft)
    expected_case_ids = [case.case_id for case in draft_bundle.cases]
    if set(approval.reviewed_case_ids) != set(expected_case_ids):
        raise ValueError("approval must review every case exactly once")
    targets = (
        output,
        output.with_suffix(".manifest.json"),
        output.with_suffix(".coverage.json"),
    )
    if any(path.exists() for path in targets):
        raise FileExistsError("frozen output or companion file already exists")
    execution_profiles = {
        name: profile.model_dump(mode="json")
        for name, profile in suite.config.execution_profiles.items()
    }
    if generation_metadata is None or generation_metadata.get(
        "execution_profiles"
    ) != execution_profiles:
        raise ValueError("generation execution profiles differ from suite")
    output.parent.mkdir(parents=True, exist_ok=True)
    generated_root = draft.parent / "capability_bundle"
    if not generated_root.is_dir():
        raise ValueError("generation capability bundle is missing")
    capability_bundle = load_validated_bundle(
        generated_root, suite.capability_profile
    )
    if generation_metadata is None:
        raise ValueError("generation metadata is required for capability binding")
    if (
        generation_metadata.get("capability_bundle_sha256")
        != capability_bundle.capability_bundle_sha256
    ):
        raise ValueError("generation capability bundle hash mismatch")
    if (
        generation_metadata.get("agent_snapshot_sha256")
        != capability_bundle.root.snapshot_sha256
    ):
        raise ValueError("generation agent snapshot hash mismatch")
    current_bundle = suite.validated_capability_bundle
    if (
        current_bundle.capability_bundle_sha256
        != capability_bundle.capability_bundle_sha256
    ):
        raise ValueError("current capability bundle differs from generation bundle")
    ir_binding = generation_metadata.get("capability_ir_binding")
    if not isinstance(ir_binding, dict) or ir_binding.get(
        "sha256"
    ) != suite.capability_ir.canonical_sha256:
        raise ValueError("generation Capability IR differs from current IR")
    selected_tools = (
        {suite.capability_ir.tool.tool_name}
        if suite.capability_ir.tool is not None
        else set()
    )
    profile_tools = {
        tool
        for profile in suite.config.execution_profiles.values()
        for tool in profile.allowed_tools
    }
    unknown_tools = sorted(profile_tools - selected_tools)
    if unknown_tools:
        raise ValueError(f"execution profile tools are not selected: {unknown_tools}")
    frozen_capability_bundle = freeze_capability_bundle(
        capability_bundle, output, suite.target_agent
    )
    shutil.copyfile(draft, output)
    bundle = load_dataset(output)
    coverage = next(gate for gate in validation.gates if gate.name == "coverage")
    coverage_path = targets[2]
    coverage_path.write_text(json.dumps(coverage.model_dump(mode="json"), indent=2))
    source_manifest = list((generation_metadata or {}).get("source_manifest", []))
    if not source_manifest:
        for path in suite.source_files:
            source_manifest.append({"path": str(path), "sha256": sha256_file(path)})
    source_pack_sha256 = sha256_bytes(
        "".join(item["sha256"] for item in source_manifest).encode()
    )
    manifest = {
        **(generation_metadata or {}),
        "suite_id": suite.suite_id,
        "dataset_version": suite.dataset_version,
        "state": "FROZEN",
        "dataset_path": str(output),
        "dataset_sha256": bundle.sha256,
        "case_count": bundle.total_count,
        "source_manifest": source_manifest,
        "execution_profiles": execution_profiles,
        "source_pack_sha256": source_pack_sha256,
        "capability_bundle": frozen_capability_bundle.model_dump(),
        "coverage_plan_sha256": sha256_file(suite.suite_dir / "coverage_plan.json"),
        "eval_case_schema_sha256": sha256_file(suite.eval_case_schema_path),
        "evaluator_version": "0.1.0",
        "validation": validation.model_dump(mode="json"),
        "reviewer": approval.reviewer,
        "approved_at": approval.approved_at.isoformat(),
        "approval": {
            "review_artifact_sha256": approval.review_artifact_sha256,
            "reviewed_case_count": len(approval.reviewed_case_ids),
            "reviewed_case_ids": approval.reviewed_case_ids,
        },
        "frozen_at": datetime.now(UTC).isoformat(),
    }
    manifest_path = targets[1]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return targets
