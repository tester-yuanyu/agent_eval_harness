"""Built-in adapters from external dataset formats to DatasetBundle."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ...contracts.models import ResolvedSource
from ...dataset_loader import (
    DatasetLoadError,
    _execution_profiles,
    _matches,
    load_jsonl_dataset,
)
from ...schemas import DatasetBundle, DatasetFilters, EvalCase

EMPTY_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


def _one_source(sources: Sequence[ResolvedSource]) -> ResolvedSource:
    if len(sources) != 1:
        raise DatasetLoadError("dataset Loader requires exactly one source")
    return sources[0]


def _empty_config(config: Mapping[str, Any]) -> None:
    if config:
        raise DatasetLoadError("dataset Loader config must be empty")


class LegacyJsonlDatasetLoader:
    plugin_id = "legacy_jsonl_eval_case_v1"
    config_schema = EMPTY_CONFIG_SCHEMA

    def load(
        self,
        sources: Sequence[ResolvedSource],
        *,
        filters: DatasetFilters | None,
        config: Mapping[str, Any],
    ) -> DatasetBundle:
        _empty_config(config)
        if not sources:
            raise DatasetLoadError(
                "legacy JSONL Loader requires exactly one source for the dataset"
            )
        return load_jsonl_dataset(
            sources[0],
            filters,
            manifest_sources=sources[1:],
        )

    def fingerprint_sources(self) -> list[Path]:
        return [Path(__file__).resolve().parents[2] / "dataset_loader.py"]


class JsonDocumentDatasetLoader:
    plugin_id = "fixture_json_document_v1"
    config_schema = EMPTY_CONFIG_SCHEMA

    def load(
        self,
        sources: Sequence[ResolvedSource],
        *,
        filters: DatasetFilters | None,
        config: Mapping[str, Any],
    ) -> DatasetBundle:
        _empty_config(config)
        source = _one_source(sources)
        try:
            document = json.loads(source.content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DatasetLoadError(
                f"dataset={source.filesystem_path} field=<json>: {exc}"
            ) from exc
        if not isinstance(document, dict) or set(document) != {"metadata", "cases"}:
            raise DatasetLoadError(
                "JSON document dataset requires exactly metadata and cases"
            )
        metadata = document["metadata"]
        raw_cases = document["cases"]
        if not isinstance(metadata, dict) or not isinstance(raw_cases, list):
            raise DatasetLoadError("JSON document metadata/cases have invalid types")
        cases: list[EvalCase] = []
        seen: set[str] = set()
        for index, candidate in enumerate(raw_cases):
            case_id = candidate.get("case_id") if isinstance(candidate, dict) else None
            try:
                case = EvalCase.model_validate(candidate)
            except ValidationError as exc:
                detail = exc.errors(include_url=False)[0]
                field = "/".join(str(item) for item in detail["loc"])
                raise DatasetLoadError(
                    f"dataset={source.filesystem_path} index={index} "
                    f"case_id={case_id or '<unknown>'} field={field}: "
                    f"{detail['msg']}"
                ) from exc
            if case.case_id in seen:
                raise DatasetLoadError(
                    f"dataset={source.filesystem_path} index={index} "
                    f"case_id={case.case_id} field=case_id: duplicate case_id"
                )
            seen.add(case.case_id)
            cases.append(case)
        selected = [case for case in cases if _matches(case, filters)]
        profiles, profiles_source = _execution_profiles(
            metadata.get("execution_profiles", ...),
            selected,
            None,
        )
        lifecycle = metadata.get("lifecycle_state", "UNKNOWN")
        if lifecycle not in {"DRAFT", "VALIDATED", "APPROVED", "FROZEN"}:
            lifecycle = "UNKNOWN"
        return DatasetBundle(
            path=str(source.filesystem_path),
            sha256=source.sha256,
            schema_versions=sorted({case.schema_version for case in cases}),
            dataset_version=str(metadata.get("dataset_version") or "unknown"),
            lifecycle_state=lifecycle,
            suite_id=metadata.get("suite_id"),
            manifest_path=None,
            provider_id=str(metadata.get("provider_id") or "unknown"),
            capability_bundle_path=None,
            capability_bundle_sha256=metadata.get("capability_bundle_sha256"),
            execution_profiles=profiles,
            execution_profiles_source=profiles_source,
            total_count=len(cases),
            cases=selected,
        )
