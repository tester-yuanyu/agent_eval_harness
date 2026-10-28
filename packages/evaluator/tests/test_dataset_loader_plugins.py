from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import module_case

from eval_framework.contracts.models import ResolvedSource
from eval_framework.contracts.store import sha256_bytes
from eval_framework.dataset_loader import DatasetLoadError, load_dataset
from eval_framework.plugins.builtin.dataset_loaders import (
    JsonDocumentDatasetLoader,
    LegacyJsonlDatasetLoader,
)
from eval_framework.schemas import DatasetBundle, DatasetFilters


def _source(path: Path, content: bytes) -> ResolvedSource:
    path.write_bytes(content)
    return ResolvedSource(
        logical_path=path.name,
        filesystem_path=path,
        sha256=sha256_bytes(content),
        content=content,
    )


def _jsonl_source(tmp_path: Path, cases: list[dict]) -> ResolvedSource:
    content = ("\n".join(json.dumps(case) for case in cases) + "\n").encode()
    return _source(tmp_path / "cases.jsonl", content)


def _document_source(tmp_path: Path, cases: list[dict]) -> ResolvedSource:
    content = json.dumps(
        {
            "metadata": {
                "dataset_version": "fixture",
                "lifecycle_state": "FROZEN",
                "provider_id": "fixture_provider",
                "execution_profiles": {"legacy": {"allowed_tools": []}},
            },
            "cases": cases,
        }
    ).encode()
    return _source(tmp_path / "cases.json", content)


def assert_loader_conforms(loader, source: ResolvedSource) -> None:
    loaded = loader.load([source], filters=None, config={})

    assert isinstance(loaded, DatasetBundle)
    assert [case.case_id for case in loaded.cases] == ["MODULE-1"]
    assert loaded.sha256 == source.sha256


def test_legacy_jsonl_loader_conforms(tmp_path: Path) -> None:
    assert_loader_conforms(
        LegacyJsonlDatasetLoader(),
        _jsonl_source(tmp_path, [module_case()]),
    )


def test_json_document_loader_conforms(tmp_path: Path) -> None:
    assert_loader_conforms(
        JsonDocumentDatasetLoader(),
        _document_source(tmp_path, [module_case()]),
    )


def test_loaders_reject_invalid_source_counts(tmp_path: Path) -> None:
    source = _jsonl_source(tmp_path, [module_case()])

    with pytest.raises(DatasetLoadError, match="exactly one source"):
        LegacyJsonlDatasetLoader().load([], filters=None, config={})
    with pytest.raises(DatasetLoadError, match="exactly one source"):
        JsonDocumentDatasetLoader().load([], filters=None, config={})
    with pytest.raises(DatasetLoadError, match="exactly one source"):
        JsonDocumentDatasetLoader().load([source, source], filters=None, config={})


def test_legacy_loader_accepts_jsonl_content_without_jsonl_suffix(
    tmp_path: Path,
) -> None:
    source = _jsonl_source(tmp_path, [module_case()]).model_copy(
        update={"logical_path": "cases.ndjson"}
    )

    loaded = LegacyJsonlDatasetLoader().load([source], filters=None, config={})

    assert [case.case_id for case in loaded.cases] == ["MODULE-1"]


def test_path_loader_uses_first_manifest_matching_dataset_hash(tmp_path: Path) -> None:
    source = _jsonl_source(tmp_path, [module_case()])
    Path(source.filesystem_path).with_suffix(".manifest.json").write_text(
        json.dumps({"dataset_sha256": "0" * 64, "dataset_version": "stale"})
    )
    (tmp_path / "generation_manifest.json").write_text(
        json.dumps(
            {
                "dataset_sha256": source.sha256,
                "dataset_version": "matching-fallback",
                "execution_profiles": {"legacy": {"allowed_tools": []}},
            }
        )
    )

    loaded = load_dataset(source.filesystem_path)

    assert loaded.dataset_version == "matching-fallback"
    assert loaded.manifest_path == str(
        (tmp_path / "generation_manifest.json").resolve()
    )


def test_json_document_loader_rejects_duplicate_case_id(tmp_path: Path) -> None:
    source = _document_source(tmp_path, [module_case(), module_case()])

    with pytest.raises(DatasetLoadError, match="duplicate case_id"):
        JsonDocumentDatasetLoader().load([source], filters=None, config={})


def test_json_document_loader_applies_canonical_filters(tmp_path: Path) -> None:
    first = module_case("MODULE-1")
    second = module_case("MODULE-2")
    second["labels"] = ["selected"]
    source = _document_source(tmp_path, [first, second])

    loaded = JsonDocumentDatasetLoader().load(
        [source],
        filters=DatasetFilters(labels=["selected"]),
        config={},
    )

    assert [case.case_id for case in loaded.cases] == ["MODULE-2"]
    assert loaded.total_count == 2


def test_json_document_fixture_is_loadable() -> None:
    path = Path(__file__).parent / "fixtures" / "json_document_dataset.json"
    source = ResolvedSource(
        logical_path=path.name,
        filesystem_path=path,
        sha256=sha256_bytes(path.read_bytes()),
        content=path.read_bytes(),
    )

    loaded = JsonDocumentDatasetLoader().load([source], filters=None, config={})

    assert [case.case_id for case in loaded.cases] == ["MODULE-1"]
