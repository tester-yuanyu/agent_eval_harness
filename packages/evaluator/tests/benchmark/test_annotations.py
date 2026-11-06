import hashlib
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
DATASET = ROOT / "data/benchmarks/file-tools-v2"


def rewrite_records(output, change):
    path = output / "annotations.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    change(rows)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    manifest = json.loads((output / "manifest.json").read_text())
    manifest["files"]["annotations.jsonl"] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest))


def test_binding_includes_raw_manifest_and_full_frozen_contract(tmp_path):
    from eval_framework.benchmark.datasets.binding import build_dataset_binding

    first = build_dataset_binding(DATASET)
    copy = tmp_path / "data"
    shutil.copytree(DATASET, copy)
    manifest = copy / "manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b"\n")
    second = build_dataset_binding(copy)
    assert first["binding"]["legacy_identity"] == second["binding"]["legacy_identity"]
    assert first["dataset_sha256"] != second["dataset_sha256"]


def test_annotations_build_is_immutable_and_public_projection_hides_basis(tmp_path):
    from eval_framework.benchmark.datasets.annotations import (
        build_annotations,
        load_annotations,
        public_labels,
    )
    from eval_framework.benchmark.datasets.binding import build_dataset_binding
    from eval_framework.benchmark.tasks import load_tasks

    output = tmp_path / "annotations"
    before = (DATASET / "tasks.jsonl").read_bytes()
    build_annotations(DATASET, output)
    binding = build_dataset_binding(DATASET)
    loaded = load_annotations(
        output, dataset_binding=binding, case_ids={t["id"] for t in load_tasks(DATASET)}
    )
    assert len(loaded.records) == 420
    assert {r["review_status"] for r in loaded.records} == {"proposed"}
    value = {**loaded.records[0], "basis_refs": ["PRIVATE_SENTINEL"]}
    assert "PRIVATE_SENTINEL" not in json.dumps(public_labels(value))
    with pytest.raises(ValueError):
        build_annotations(DATASET, output)
    assert (DATASET / "tasks.jsonl").read_bytes() == before


@pytest.mark.parametrize(
    "change", ["duplicate", "capability", "hash", "binding", "taxonomy"]
)
def test_annotation_tampering_is_rejected(tmp_path, change):
    from eval_framework.benchmark.datasets.annotations import (
        build_annotations,
        load_annotations,
    )
    from eval_framework.benchmark.datasets.binding import build_dataset_binding
    from eval_framework.benchmark.tasks import load_tasks

    output = tmp_path / "annotations"
    build_annotations(DATASET, output)
    binding = build_dataset_binding(DATASET)
    if change == "duplicate":
        rewrite_records(output, lambda rows: rows.append(rows[0]))
    elif change == "capability":
        rewrite_records(output, lambda rows: rows[0].update(capabilities=["invented"]))
    elif change == "hash":
        (output / "annotations.jsonl").write_text("{}\n")
    elif change == "binding":
        binding["dataset_sha256"] = "0" * 64
    else:
        (output / "taxonomy.json").write_text("{}")
    with pytest.raises(ValueError):
        load_annotations(
            output,
            dataset_binding=binding,
            case_ids={t["id"] for t in load_tasks(DATASET)},
        )


def test_only_reviewed_labels_enter_overlapping_buckets(tmp_path):
    from eval_framework.aggregator.buckets import bucket_report

    from .analysis_fixtures import run
    from .test_analysis_populations import population

    pop = population(tmp_path, run())
    records = [
        {
            "case_id": "a",
            "review_status": "reviewed",
            "capabilities": ["single_tool", "multi_turn_state"],
            "difficulty": "easy",
        },
        {
            "case_id": "b",
            "review_status": "proposed",
            "capabilities": ["single_tool"],
            "difficulty": "hard",
        },
    ]
    result = bucket_report(pop, records)["e2e"]
    assert result["unlabeled_tasks"] == 1
    assert result["capabilities"]["single_tool"]["planned_trials"] == 3
    assert result["capabilities"]["multi_turn_state"]["planned_trials"] == 3
    assert "hard" not in result["difficulty"]


def test_published_version_rejects_different_content_in_another_directory(tmp_path):
    from eval_framework.benchmark.datasets.annotations import load_annotations
    from eval_framework.benchmark.datasets.binding import build_dataset_binding
    from eval_framework.benchmark.tasks import load_tasks

    altered = tmp_path / "altered"
    shutil.copytree(ROOT / "data/benchmark-annotations/file-tools-v2/1.0.0", altered)
    rewrite_records(altered, lambda rows: rows[0].update(basis_refs=["different"]))
    with pytest.raises(ValueError, match="version"):
        load_annotations(
            altered,
            dataset_binding=build_dataset_binding(DATASET),
            case_ids={t["id"] for t in load_tasks(DATASET)},
        )


def test_unregistered_proposal_requires_explicit_version_registry_for_analysis(
    tmp_path,
):
    from eval_framework.benchmark.datasets.annotations import (
        build_annotations,
        load_annotations,
    )
    from eval_framework.benchmark.datasets.binding import build_dataset_binding
    from eval_framework.benchmark.tasks import load_tasks

    output = tmp_path / "proposal"
    proposal = build_annotations(DATASET, output, version="1.1.0")
    assert proposal.registration_status == "unregistered"
    kwargs = {
        "dataset_binding": build_dataset_binding(DATASET),
        "case_ids": {t["id"] for t in load_tasks(DATASET)},
    }
    with pytest.raises(ValueError, match="not registered"):
        load_annotations(output, **kwargs)
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "format_version": "benchmark-annotation-registry-v1",
                "datasets": {
                    "file-tools-v2": {
                        "1.1.0": {
                            "dataset_sha256": proposal.manifest["dataset_sha256"],
                            "content_sha256": proposal.content_sha256,
                        }
                    }
                },
            }
        )
    )
    assert (
        load_annotations(output, registry_path=registry, **kwargs).registration_status
        == "registered"
    )


def test_external_registry_cannot_rebind_a_bundled_published_version(tmp_path):
    from capability_snapshot_kit.hashing import sha256_json

    from eval_framework.benchmark.datasets.annotations import load_annotations
    from eval_framework.benchmark.datasets.binding import build_dataset_binding
    from eval_framework.benchmark.tasks import load_tasks

    altered = tmp_path / "altered"
    shutil.copytree(ROOT / "data/benchmark-annotations/file-tools-v2/1.0.0", altered)
    rewrite_records(altered, lambda rows: rows[0].update(basis_refs=["different"]))
    content_hash = sha256_json(
        {
            name: hashlib.sha256((altered / name).read_bytes()).hexdigest()
            for name in ("manifest.json", "annotations.jsonl", "taxonomy.json")
        }
    )
    binding = build_dataset_binding(DATASET)
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "format_version": "benchmark-annotation-registry-v1",
                "datasets": {
                    "file-tools-v2": {
                        "1.0.0": {
                            "dataset_sha256": binding["dataset_sha256"],
                            "content_sha256": content_hash,
                        }
                    }
                },
            }
        )
    )
    with pytest.raises(ValueError, match="version"):
        load_annotations(
            altered,
            dataset_binding=binding,
            case_ids={t["id"] for t in load_tasks(DATASET)},
            registry_path=registry,
        )
