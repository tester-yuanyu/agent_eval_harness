"""Frozen JSONL loading with precise source errors and stable hashing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from .contracts.models import ResolvedSource
from .errors import EvaluationPreflightError
from .schemas import (
    DatasetBundle,
    DatasetFilters,
    EvalCase,
    ExecutionProfile,
)


class DatasetLoadError(ValueError):
    """A JSONL row failed parsing or protocol validation."""


def _dataset_metadata(
    source: Path,
    digest: str,
    manifest_sources: Sequence[ResolvedSource] = (),
) -> dict[str, object]:
    candidates = [
        (item.filesystem_path, item.content) for item in manifest_sources
    ]
    for manifest_path, manifest_raw in candidates:
        try:
            manifest = json.loads(manifest_raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        hashes = {manifest.get("dataset_sha256"), manifest.get("draft_sha256")}
        if digest not in hashes:
            continue
        state = manifest.get("state")
        if state not in {"DRAFT", "VALIDATED", "APPROVED", "FROZEN"}:
            state = "UNKNOWN"
        provider_id = "unknown"
        bundle_path = None
        bundle_sha256 = None
        binding = manifest.get("capability_bundle")
        if isinstance(binding, dict):
            relative = binding.get("path")
            provider = binding.get("provider_id")
            digest_value = binding.get("sha256")
            if not isinstance(relative, str):
                raise DatasetLoadError("capability bundle path must be relative")
            candidate = PurePosixPath(relative)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise DatasetLoadError("capability bundle path must be relative")
            resolved = (manifest_path.parent / Path(*candidate.parts)).resolve()
            if not resolved.is_relative_to(manifest_path.parent.resolve()):
                raise DatasetLoadError(
                    "capability bundle path escapes dataset directory"
                )
            if not isinstance(provider, str) or not provider:
                raise DatasetLoadError("capability bundle provider_id is required")
            if not isinstance(digest_value, str) or not digest_value:
                raise DatasetLoadError("capability bundle sha256 is required")
            provider_id = provider
            bundle_path = str(resolved)
            bundle_sha256 = digest_value
        legacy_snapshots = manifest.get("capability_snapshots", [])
        if not isinstance(legacy_snapshots, list):
            legacy_snapshots = []
        if bundle_path is None and isinstance(
            manifest.get("capability_bundle_sha256"), str
        ):
            bundle_sha256 = manifest["capability_bundle_sha256"]
        return {
            "dataset_version": str(manifest.get("dataset_version") or "unknown"),
            "lifecycle_state": state,
            "suite_id": manifest.get("suite_id"),
            "manifest_path": str(manifest_path.resolve()),
            "provider_id": provider_id,
            "capability_bundle_path": bundle_path,
            "capability_bundle_sha256": bundle_sha256,
            "legacy_capability_snapshots": legacy_snapshots,
            "execution_profiles_raw": manifest.get("execution_profiles", ...),
        }
    return {
        "dataset_version": "unknown",
        "lifecycle_state": "UNKNOWN",
        "suite_id": None,
        "manifest_path": None,
        "provider_id": "unknown",
        "capability_bundle_path": None,
        "capability_bundle_sha256": None,
        "legacy_capability_snapshots": [],
        "execution_profiles_raw": ...,
    }


def _execution_profiles(
    raw: object,
    selected_cases: list[EvalCase],
    manifest_path: str | None,
) -> tuple[dict[str, ExecutionProfile], str]:
    if raw is ...:
        non_module = [case for case in selected_cases if case.test_scope != "module"]
        if non_module:
            raise EvaluationPreflightError(
                "EXECUTION_PROFILE_REQUIRED",
                "legacy link/end_to_end datasets require frozen execution_profiles",
                evidence_path=manifest_path,
            )
        names = dict.fromkeys(case.execution.tool_profile for case in selected_cases)
        return (
            {name: ExecutionProfile(allowed_tools=[]) for name in names},
            "legacy_module",
        )
    try:
        if not isinstance(raw, dict) or not raw:
            raise ValueError("execution_profiles must be a non-empty object")
        profiles: dict[str, ExecutionProfile] = {}
        for name, payload in raw.items():
            if not isinstance(name, str) or not name:
                raise ValueError("execution profile names must be non-empty strings")
            profiles[name] = ExecutionProfile.model_validate(payload)
        missing = sorted(
            {
                case.execution.tool_profile
                for case in selected_cases
                if case.execution.tool_profile not in profiles
            }
        )
        if missing:
            raise ValueError(f"cases reference undeclared profiles {missing}")
        return profiles, "manifest"
    except (ValidationError, ValueError, TypeError) as exc:
        raise EvaluationPreflightError(
            "EXECUTION_PROFILE_INVALID",
            str(exc),
            evidence_path=manifest_path,
        ) from exc


def _error(path: Path, line: int, case_id: object, field: str, message: str) -> str:
    return (
        f"dataset={path} line={line} case_id={case_id or '<unknown>'} "
        f"field={field or '<root>'}: {message}"
    )


def load_dataset(
    path: str | Path, filters: DatasetFilters | None = None
) -> DatasetBundle:
    source = Path(path).resolve()
    raw = source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    manifest_sources = []
    for manifest_path in (
        source.with_suffix(".manifest.json"),
        source.parent / "generation_manifest.json",
    ):
        if manifest_path.is_file():
            manifest_raw = manifest_path.read_bytes()
            manifest_sources.append(
                ResolvedSource(
                    logical_path=manifest_path.name,
                    filesystem_path=manifest_path.resolve(),
                    sha256=hashlib.sha256(manifest_raw).hexdigest(),
                    content=manifest_raw,
                )
            )
    return load_jsonl_dataset(
        ResolvedSource(
            logical_path=source.name,
            filesystem_path=source,
            sha256=digest,
            content=raw,
        ),
        filters,
        manifest_sources=manifest_sources,
    )


def load_jsonl_dataset(
    source: ResolvedSource,
    filters: DatasetFilters | None = None,
    *,
    manifest_sources: Sequence[ResolvedSource] = (),
) -> DatasetBundle:
    path = source.filesystem_path
    raw = source.content
    digest = source.sha256
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DatasetLoadError(
                _error(path, number, None, "<json>", str(exc))
            ) from exc
        case_id = candidate.get("case_id") if isinstance(candidate, dict) else None
        try:
            case = EvalCase.model_validate(candidate)
        except ValidationError as exc:
            detail = exc.errors(include_url=False)[0]
            field = "/".join(str(item) for item in detail["loc"])
            raise DatasetLoadError(
                _error(path, number, case_id, field, detail["msg"])
            ) from exc
        if case.case_id in seen:
            raise DatasetLoadError(
                _error(path, number, case.case_id, "case_id", "duplicate case_id")
            )
        seen.add(case.case_id)
        cases.append(case)
    selected = [case for case in cases if _matches(case, filters)]
    metadata = _dataset_metadata(path, digest, manifest_sources)
    if metadata["dataset_version"] == "unknown":
        metadata["dataset_version"] = ",".join(
            sorted({case.schema_version for case in cases})
        )
    raw_profiles = metadata.pop("execution_profiles_raw")
    profiles, profiles_source = _execution_profiles(
        raw_profiles,
        selected,
        metadata["manifest_path"],
    )
    return DatasetBundle(
        path=str(path),
        sha256=digest,
        schema_versions=sorted({case.schema_version for case in cases}),
        **metadata,
        execution_profiles=profiles,
        execution_profiles_source=profiles_source,
        total_count=len(cases),
        cases=selected,
    )


def _matches(case: EvalCase, filters: DatasetFilters | None) -> bool:
    if filters is None:
        return True
    if filters.scopes and case.test_scope not in filters.scopes:
        return False
    if filters.task_ids and case.task_id not in filters.task_ids:
        return False
    if filters.case_ids and case.case_id not in filters.case_ids:
        return False
    return not filters.labels or all(label in case.labels for label in filters.labels)
