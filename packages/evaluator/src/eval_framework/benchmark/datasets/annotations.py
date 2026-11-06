"""独立、不可覆盖的注释资产；加载只读且验证三份原始文件。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from capability_snapshot_kit.hashing import sha256_json
from eval_contracts import benchmark_annotations
from eval_contracts.benchmark_annotations import CAPABILITIES, AnnotationRecord

from ..analysis_sources import read_json
from ..domains import file_tools_annotations
from .binding import build_dataset_binding
from .io import file_sha256
from .loader import load_dataset

TAXONOMY = {
    "taxonomy_version": "capability-taxonomy-v1",
    "capabilities": list(CAPABILITIES),
    "difficulty_rule_version": "structural-complexity-v1",
    "difficulty": ["easy", "medium", "hard", "unknown"],
    "easy_max": {
        "reference_tool_calls": 2,
        "dependency_depth": 1,
        "interaction_turns": 1,
        "recovery_branches": 0,
    },
    "hard_min": {
        "reference_tool_calls": 7,
        "dependency_depth": 4,
        "interaction_turns": 3,
        "recovery_branches": 2,
    },
}


@dataclass(frozen=True)
class AnnotationSet:
    manifest: dict
    records: list[dict]
    content_sha256: str
    missing_case_ids: list[str]
    registry_sha256: str | None = None
    registration_status: str = "unregistered"


def public_labels(annotation: dict) -> dict:
    return {k: annotation[k] for k in ("capabilities", "difficulty", "review_status")}


def _verify_version(
    manifest, content_hash, registry_path=None, *, allow_unregistered=False
):
    registry, registry_hash = read_json(
        registry_path or Path(__file__).with_name("annotation_versions.json")
    )
    if registry.get("format_version") != "benchmark-annotation-registry-v1":
        raise ValueError("unsupported annotation version registry")
    entry = (
        registry.get("datasets", {})
        .get(manifest.get("dataset_id"), {})
        .get(manifest["annotation_version"])
    )
    if registry_path is not None:
        bundled, bundled_hash = read_json(
            Path(__file__).with_name("annotation_versions.json")
        )
        registered = (
            bundled["datasets"]
            .get(manifest.get("dataset_id"), {})
            .get(manifest["annotation_version"])
        )
        if registered is not None:
            if entry is not None and entry != registered:
                raise ValueError(
                    "annotation version registry cannot rebind a published version"
                )
            entry = registered
        registry_hash = sha256_json(
            {"bundled": bundled_hash, "external": registry_hash}
        )
    if entry is None:
        if allow_unregistered:
            return registry_hash, "unregistered"
        raise ValueError(
            "annotation version is not registered; publish an immutable registry entry"
        )
    if entry != {
        "dataset_sha256": manifest["dataset_sha256"],
        "content_sha256": content_hash,
    }:
        raise ValueError("annotation version content differs from registered binding")
    return registry_hash, "registered"


def load_annotations(
    path: Path,
    *,
    dataset_binding: dict,
    case_ids: set[str],
    registry_path: Path | None = None,
    allow_unregistered: bool = False,
) -> AnnotationSet:
    path = Path(path)
    manifest, manifest_hash = read_json(path / "manifest.json")
    if (
        manifest.get("format_version") != "benchmark-annotations-v1"
        or manifest.get("dataset_sha256") != dataset_binding["dataset_sha256"]
        or manifest.get("dataset_binding") != dataset_binding["binding"]
    ):
        raise ValueError("annotation dataset binding mismatch")
    if (
        not isinstance(manifest.get("annotation_version"), str)
        or not manifest["annotation_version"]
    ):
        raise ValueError("missing annotation version")
    if set(manifest.get("files", {})) != {"annotations.jsonl", "taxonomy.json"}:
        raise ValueError("annotation file set mismatch")
    hashes = {name: file_sha256(path / name) for name in manifest["files"]}
    if hashes != manifest["files"]:
        raise ValueError("annotation file hash mismatch")
    taxonomy, _ = read_json(path / "taxonomy.json")
    if (
        taxonomy != TAXONOMY
        or manifest.get("taxonomy_version") != taxonomy["taxonomy_version"]
    ):
        raise ValueError("unsupported annotation taxonomy")
    records = []
    seen = set()
    for line in (path / "annotations.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = AnnotationRecord.model_validate_json(line).model_dump()
        case = record["case_id"]
        if (
            case in seen
            or case not in case_ids
            or record["dataset_sha256"] != dataset_binding["dataset_sha256"]
        ):
            raise ValueError("duplicate/unknown annotation case or dataset")
        seen.add(case)
        records.append(record)
    states = {r["review_status"] for r in records}
    status = next(iter(states)) if len(states) == 1 else "mixed" if states else "empty"
    if (
        manifest.get("record_count") != len(records)
        or manifest.get("review_status") != status
    ):
        raise ValueError("annotation count/review status mismatch")
    content_hash = sha256_json({"manifest.json": manifest_hash, **hashes})
    registry_hash, registration_status = _verify_version(
        manifest, content_hash, registry_path, allow_unregistered=allow_unregistered
    )
    return AnnotationSet(
        manifest,
        records,
        content_hash,
        sorted(case_ids - seen),
        registry_hash,
        registration_status,
    )


def build_annotations(
    dataset_path: Path,
    output: Path,
    *,
    version: str = "1.0.0",
    registry_path: Path | None = None,
) -> AnnotationSet:
    output = Path(output)
    if output.exists():
        raise ValueError("annotation output already exists; publish a new version")
    dataset = load_dataset(dataset_path)
    if dataset["contract_version"] not in {
        "file-tools-task-v1",
        "file-tools-task-v2",
        "model-decisions-task-v1",
    }:
        raise ValueError(
            "annotation suggestions currently support file-tools contracts only"
        )
    binding = build_dataset_binding(dataset_path)
    records = [
        AnnotationRecord.model_validate(
            {**r, "dataset_sha256": binding["dataset_sha256"]}
        ).model_dump()
        for r in file_tools_annotations.suggest_file_tools_annotations(dataset["tasks"])
    ]
    lines = "".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
        for r in records
    )
    taxonomy = json.dumps(TAXONOMY, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    manifest = {
        "format_version": "benchmark-annotations-v1",
        "annotation_version": version,
        "taxonomy_version": TAXONOMY["taxonomy_version"],
        "dataset_id": dataset["legacy_identity"].get("dataset_id"),
        "dataset_sha256": binding["dataset_sha256"],
        "dataset_binding": binding["binding"],
        "record_count": len(records),
        "review_status": "proposed" if records else "empty",
        "source": "deterministic_suggestions_pending_human_review",
        "rules_sources": {
            "suggestions": file_sha256(Path(file_tools_annotations.__file__)),
            "contract": file_sha256(Path(benchmark_annotations.__file__)),
        },
        "files": {
            "annotations.jsonl": hashlib.sha256(lines.encode()).hexdigest(),
            "taxonomy.json": hashlib.sha256(taxonomy.encode()).hexdigest(),
        },
    }
    manifest_text = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )
    content_hash = sha256_json(
        {
            "manifest.json": hashlib.sha256(manifest_text.encode()).hexdigest(),
            **manifest["files"],
        }
    )
    _verify_version(manifest, content_hash, registry_path, allow_unregistered=True)
    output.mkdir(parents=True, exist_ok=False)
    (output / "annotations.jsonl").write_text(lines, encoding="utf-8")
    (output / "taxonomy.json").write_text(taxonomy, encoding="utf-8")
    (output / "manifest.json").write_text(manifest_text, encoding="utf-8")
    return load_annotations(
        output,
        dataset_binding=binding,
        case_ids={t["id"] for t in dataset["tasks"]},
        registry_path=registry_path,
        allow_unregistered=True,
    )
