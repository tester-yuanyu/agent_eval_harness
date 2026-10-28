"""Hash-bound normalized candidates for the existing Suite compiler."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..contracts.models import ResolvedSource
from ..dataset_loader import DatasetLoadError, _matches
from ..schemas import DatasetBundle, DatasetFilters, EvalCase
from .candidates import STATIC_KINDS, _subject_pointer
from .delivery import pointer_value
from .models import CandidateCase, CandidateManifest


def _source_code_provenance(
    row: CandidateCase, payload: dict[str, Any], onboarding: dict[str, Any]
) -> None:
    expected = {
        ref.path.removeprefix("sources/"): ref.sha256
        for ref in row.source_refs
        if ref.path.startswith("sources/")
    }
    declared = payload.get("source_files", [])
    if not isinstance(declared, list) or any(
        not isinstance(item, dict)
        or set(item) != {"path", "sha256"}
        or not isinstance(item["path"], str)
        or not isinstance(item["sha256"], str)
        for item in declared
    ):
        raise DatasetLoadError("source code provenance requires path/hash pairs")
    actual = {item["path"]: item["sha256"] for item in declared}
    if len(actual) != len(declared) or any(
        actual.get(path) != digest for path, digest in expected.items()
    ):
        raise DatasetLoadError(
            "source code provenance cannot rewrite frozen source digests"
        )
    supplements = set(actual) - set(expected)
    if not supplements:
        return
    if row.agent_id != "nanobot" or supplements != {"nanobot/runtime_context.py"}:
        raise DatasetLoadError(
            "source code provenance contains undeclared runtime supplements"
        )
    digest = actual["nanobot/runtime_context.py"]
    matching = [
        item
        for item in onboarding.get("runtime_files", [])
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and item["path"].endswith("/nanobot/runtime_context.py")
        and item.get("sha256") == digest
    ]
    if len(matching) != 1:
        raise DatasetLoadError(
            "source code provenance supplement requires trusted runtime identity"
        )


def _provenance(
    sources: Sequence[ResolvedSource], metadata: dict[str, Any], cases: list[EvalCase]
) -> None:
    """An authored Suite cannot promote or relabel the provisional importer."""
    indexed = {source.logical_path: source for source in sources[1:]}
    if len(indexed) != len(sources) - 1 or "manifest.json" not in indexed:
        raise DatasetLoadError("candidate provenance requires a unique source manifest")
    manifest_source = indexed["manifest.json"]
    manifest = CandidateManifest.model_validate_json(manifest_source.content)
    expected_dependencies = {
        "manifest.json": manifest_source.sha256,
        **manifest.files_sha256,
    }
    if metadata.get("source_dependencies") != expected_dependencies:
        raise DatasetLoadError(
            "candidate provenance dependencies disagree with manifest"
        )
    onboarding = metadata.get("onboarding")
    if (
        not isinstance(onboarding, dict)
        or onboarding.get("release_eligible") is not False
    ):
        raise DatasetLoadError("candidate provenance must remain release-ineligible")
    partition = onboarding.get("partition")
    if partition not in {"static", "behavior"}:
        raise DatasetLoadError("candidate provenance partition is invalid")
    expected_identity = {
        "agent_id": manifest.agent_id,
        "source_manifest_sha256": manifest_source.sha256,
        "source_case_count": manifest.case_count,
        "source_state": manifest.state,
        "source_runtime_execution": manifest.runtime_execution,
        "source_approval": manifest.approval,
    }
    if any(onboarding.get(key) != value for key, value in expected_identity.items()):
        raise DatasetLoadError("candidate provenance identity disagrees with manifest")
    lifecycle = (
        manifest.state
        if manifest.state in {"DRAFT", "VALIDATED", "APPROVED", "FROZEN"}
        else "UNKNOWN"
    )
    if (
        metadata.get("lifecycle_state") != lifecycle
        or metadata.get("provider_id") != manifest.agent_id
        or metadata.get("capability_bundle_sha256") != manifest.bundle_sha256
    ):
        raise DatasetLoadError(
            "candidate provenance cannot change lifecycle or Agent identity"
        )
    original = []
    for dataset in manifest.datasets:
        source = indexed.get(dataset.path)
        if source is None or source.sha256 != dataset.sha256:
            raise DatasetLoadError("candidate provenance dataset is not bound")
        rows = [
            CandidateCase.model_validate_json(line)
            for line in source.content.splitlines()
            if line.strip()
        ]
        if len(rows) != dataset.case_count:
            raise DatasetLoadError("candidate provenance dataset count mismatch")
        original.extend(rows)
    if len(original) != manifest.case_count:
        raise DatasetLoadError("candidate provenance total count mismatch")
    rows_by_id = {
        row.case_id: row
        for row in original
        if (row.kind in STATIC_KINDS) == (partition == "static")
    }
    entries = onboarding.get("case_mapping", [])
    mapping = {entry.get("source_case_id"): entry for entry in entries}
    if len(mapping) != len(entries) or set(mapping) != set(rows_by_id):
        raise DatasetLoadError(
            "candidate provenance mapping must cover the source partition"
        )
    selected = {}
    for source_id, entry in mapping.items():
        row = rows_by_id[source_id]
        normalized_id = "case_" + hashlib.sha256(source_id.encode()).hexdigest()[:24]
        status = {
            key: getattr(row, key)
            for key in (
                "support_status",
                "execution_readiness",
                "runtime_execution",
                "approval",
                "source_basis",
            )
        }
        if (
            entry.get("case_id") != normalized_id
            or entry.get("source_status") != status
            or any(
                entry.get(key) != getattr(row, key)
                for key in ("kind", "layer", "target_id", "blocker_ids")
            )
        ):
            raise DatasetLoadError(
                "candidate provenance mapping changes source declarations"
            )
        if entry.get("disposition") == partition:
            if row.kind == "blocked_obligation" or row.blocker_ids:
                raise DatasetLoadError(
                    "candidate provenance cannot execute blocked obligations"
                )
            if partition == "behavior" and (
                row.support_status != "supported"
                or row.execution_readiness != "needs_runner"
            ):
                raise DatasetLoadError(
                    "candidate provenance cannot upgrade unsupported behavior"
                )
            if partition == "static" and row.execution_readiness != "static_only":
                raise DatasetLoadError(
                    "candidate provenance cannot upgrade static readiness"
                )
            selected[normalized_id] = row
        elif entry.get("disposition") != "blocked":
            raise DatasetLoadError("candidate provenance has invalid disposition")
    if (
        set(selected) != {case.case_id for case in cases}
        or metadata.get("total_count") != len(rows_by_id)
        or onboarding.get("selected_count") != len(cases)
        or onboarding.get("blocked_count") != len(rows_by_id) - len(cases)
    ):
        raise DatasetLoadError("candidate provenance selected/planned counts disagree")
    for case in cases:
        row = selected[case.case_id]
        expected_checks = [
            {
                "path": _subject_pointer(check.subject),
                "operator": check.operator,
                "expected": check.expected,
            }
            for check in row.oracle.checks
        ]
        if len(case.oracle.evaluation.checks) != 1 or case.oracle.evaluation.checks[
            0
        ].model_dump() != {
            "name": "observations_match",
            "weight": 1.0,
            "critical": False,
            "config": {"checks": expected_checks, "channel": "returned"},
        }:
            raise DatasetLoadError(
                "candidate provenance cannot rewrite the source Oracle"
            )
        expected_input = dict(row.input)
        if partition == "static":
            key = "schema_ref" if row.kind == "schema_contract" else "source_ref"
            reference = row.input[key]
            bound_source = indexed["source_delivery/" + reference["path"]]
            if bound_source.sha256 != reference["sha256"]:
                raise DatasetLoadError("candidate provenance reference hash mismatch")
            value = pointer_value(
                json.loads(bound_source.content), reference["pointer"]
            )
            expected_input = (
                {
                    "operation": "validate_schema",
                    "schema": value,
                    "instance": row.input["instance"],
                }
                if row.kind == "schema_contract"
                else {"operation": "inspect_snapshot", "declared_value": value}
            )
        payload = case.execution.adapter_input or {}
        _source_code_provenance(row, payload, onboarding)
        if (
            payload.get("input") != expected_input
            or payload.get("preconditions") != row.preconditions
        ):
            raise DatasetLoadError(
                "candidate provenance cannot rewrite execution inputs"
            )


class CandidateDatasetLoader:
    plugin_id = "candidate_delivery_v1"

    def fingerprint_sources(self) -> list[Path]:
        return [Path(__file__).parent]

    def load(
        self,
        sources: Sequence[ResolvedSource],
        *,
        filters: DatasetFilters | None,
        config: Mapping[str, Any],
    ) -> DatasetBundle:
        if config or not sources:
            raise DatasetLoadError("candidate loader requires sources and empty config")
        document = json.loads(sources[0].content)
        if set(document) != {"metadata", "cases"}:
            raise DatasetLoadError("normalized candidates require metadata and cases")
        metadata = document["metadata"]
        bound = {source.logical_path: source.sha256 for source in sources[1:]}
        expected = metadata.get("source_dependencies")
        if bound != expected:
            raise DatasetLoadError(
                "candidate source dependencies must be explicit and hash-bound"
            )
        cases = [EvalCase.model_validate(row) for row in document["cases"]]
        _provenance(sources, metadata, cases)
        metadata.pop("source_dependencies")
        if len({case.case_id for case in cases}) != len(cases):
            raise DatasetLoadError("duplicate normalized candidate ID")
        if metadata["total_count"] < len(cases):
            raise DatasetLoadError(
                "planned case count is smaller than executable count"
            )
        return DatasetBundle(
            path=str(sources[0].filesystem_path),
            sha256=sources[0].sha256,
            schema_versions=sorted({case.schema_version for case in cases}),
            cases=[case for case in cases if _matches(case, filters)],
            **metadata,
        )
