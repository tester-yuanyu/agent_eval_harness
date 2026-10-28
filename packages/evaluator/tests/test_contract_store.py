from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from eval_framework.contracts.models import ContractReference, DatasetSource
from eval_framework.contracts.store import (
    ContractStore,
    ContractStoreError,
    canonical_json_bytes,
    sha256_bytes,
)


def _write(path: Path, content: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return sha256_bytes(content)


def test_canonical_json_is_independent_of_key_order() -> None:
    first = canonical_json_bytes({"z": 1, "a": {"文": True}})
    second = canonical_json_bytes({"a": {"文": True}, "z": 1})

    assert first == second == b'{"a":{"\xe6\x96\x87":true},"z":1}'


def test_store_resolves_relative_source_and_verifies_hash(tmp_path: Path) -> None:
    content = b'{"case_id":"one"}\n'
    digest = _write(tmp_path / "datasets" / "cases.jsonl", content)
    store = ContractStore(tmp_path)

    resolved = store.resolve_source(
        DatasetSource(path="datasets/cases.jsonl", sha256=digest)
    )

    assert resolved.logical_path == "datasets/cases.jsonl"
    assert resolved.filesystem_path == (tmp_path / "datasets" / "cases.jsonl")
    assert resolved.content == content


@pytest.mark.parametrize("path", ["/tmp/cases.jsonl", "../cases.jsonl"])
def test_source_model_rejects_absolute_and_parent_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        DatasetSource(path=path, sha256="a" * 64)


def test_store_rejects_symlink_that_escapes_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    (root / "escape.json").symlink_to(outside)
    store = ContractStore(root)

    with pytest.raises(ContractStoreError) as captured:
        store.resolve_source(
            DatasetSource(
                path="escape.json",
                sha256=sha256_bytes(outside.read_bytes()),
            )
        )

    assert captured.value.code == "SOURCE_PATH_OUTSIDE_ROOT"


def test_store_rejects_source_hash_mismatch(tmp_path: Path) -> None:
    _write(tmp_path / "cases.jsonl", b"{}\n")

    with pytest.raises(ContractStoreError) as captured:
        ContractStore(tmp_path).resolve_source(
            DatasetSource(path="cases.jsonl", sha256="0" * 64)
        )

    assert captured.value.code == "SOURCE_FINGERPRINT_MISMATCH"
    assert "{}" not in str(captured.value)


def test_store_loads_json_object_contract(tmp_path: Path) -> None:
    raw = json.dumps({"id": "capabilities", "version": "1"}).encode()
    digest = _write(tmp_path / "contracts" / "capabilities.json", raw)
    reference = ContractReference(
        contract_id="capabilities",
        version="1",
        path="contracts/capabilities.json",
        sha256=digest,
    )

    resolved = ContractStore(tmp_path).load_contract(reference)

    assert resolved.content == {"id": "capabilities", "version": "1"}
    assert resolved.sha256 == digest


@pytest.mark.parametrize("content", [b"not-json", b"[]"])
def test_store_rejects_invalid_contract_json(
    tmp_path: Path,
    content: bytes,
) -> None:
    digest = _write(tmp_path / "contract.json", content)
    reference = ContractReference(
        contract_id="bad",
        version="1",
        path="contract.json",
        sha256=digest,
    )

    with pytest.raises(ContractStoreError) as captured:
        ContractStore(tmp_path).load_contract(reference)

    assert captured.value.code == "CONTRACT_INVALID_JSON"
    assert captured.value.evidence_refs == ["contract.json"]


def test_store_reports_missing_source_without_leaking_content(tmp_path: Path) -> None:
    store = ContractStore(tmp_path)

    with pytest.raises(ContractStoreError) as captured:
        store.resolve_source(
            DatasetSource(path="missing.jsonl", sha256="0" * 64)
        )

    assert captured.value.code == "SOURCE_NOT_FOUND"
