"""发布门槛不把静态有效或进程成功当作执行通过。"""

import json
from copy import deepcopy

import pytest


def sample():
    return {
        "schema_version": "1.0",
        "cases": [
            {
                "case_id": "read-1",
                "prompt": "读取 input.txt 的完整内容。",
                "fixtures": {"input.txt": "hello\n"},
                "reference_path": "input.txt",
                "expected_output": "hello\n",
            }
        ],
    }


def setup_files(tmp_path):
    from eval_contracts.readiness import assertion_identity, digest_bytes

    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps(sample()))
    identity = {
        "runner_id": "native-read-file-v1",
        "implementation_sha256": "a" * 64,
        "runtime": {"python": "test", "assertions_sha256": assertion_identity()},
    }
    evidence = {
        "schema_version": "1.0",
        "dataset_sha256": digest_bytes(dataset.read_bytes()),
        "runner": identity,
        "results": [
            {
                "case_id": "read-1",
                "status": "completed",
                "evidence_complete": True,
                "before_files": {"input.txt": "hello\n"},
                "final_files": {"input.txt": "hello\n"},
                "final_output": "hello\n",
                "executed_tools": ["read_file"],
                "observed_path": "input.txt",
                "errors": [],
            }
        ],
    }
    proof = tmp_path / "evidence.json"
    proof.write_text(json.dumps(evidence))
    return dataset, proof, identity


def test_static_validation_and_missing_runner(tmp_path):
    from dataset_builder.readiness import assess

    dataset, proof, identity = setup_files(tmp_path)
    result = assess(dataset, None, identity)
    assert result["static_valid"] is True
    assert result["ready_for_review"] is False
    assert result["runtime_binding_rate"] == 0
    assert result["reference_verified_rate"] == 0


def test_reference_success_is_not_human_approval(tmp_path):
    from dataset_builder.readiness import assess

    dataset, proof, identity = setup_files(tmp_path)
    result = assess(dataset, proof, identity)
    assert result["ready_for_review"] is True
    assert result["release_ready"] is False
    assert result["reference_verified_rate"] == 1


@pytest.mark.parametrize(
    "change",
    ["oracle", "fixture", "remove", "runner", "duplicate", "missing", "wrong_output"],
)
def test_stale_or_failed_evidence_blocks_release(tmp_path, change):
    from dataset_builder.readiness import assess

    dataset, proof, identity = setup_files(tmp_path)
    data = json.loads(dataset.read_text())
    evidence = json.loads(proof.read_text())
    if change == "oracle":
        data["cases"][0]["expected_output"] = "wrong"
    elif change == "fixture":
        data["cases"][0]["fixtures"]["input.txt"] = "changed"
    elif change == "remove":
        data["cases"] = []
    elif change == "runner":
        identity["implementation_sha256"] = "b" * 64
    elif change == "duplicate":
        evidence["results"].append(deepcopy(evidence["results"][0]))
    elif change == "missing":
        evidence["results"] = []
    else:
        evidence["results"][0]["final_output"] = "wrong"
    dataset.write_text(json.dumps(data))
    proof.write_text(json.dumps(evidence))
    assert assess(dataset, proof, identity)["ready_for_review"] is False


def test_freeze_requires_bound_review_and_is_immutable(tmp_path):
    from dataset_builder.readiness import assess, freeze_release
    from eval_contracts.readiness import digest_bytes

    dataset, proof, identity = setup_files(tmp_path)
    review = {
        "approved": True,
        "reviewer": "reviewer",
        "reviewed_case_ids": ["read-1"],
        "dataset_sha256": digest_bytes(dataset.read_bytes()),
        "evidence_sha256": digest_bytes(proof.read_bytes()),
    }
    output = tmp_path / "release"
    assert assess(dataset, proof, identity, review)["release_ready"] is True
    freeze_release(dataset, proof, identity, review, output)
    assert (output / "dataset.json").read_bytes() == dataset.read_bytes()
    assert json.loads((output / "manifest.json").read_text())["state"] == "FROZEN"
    with pytest.raises(FileExistsError):
        freeze_release(dataset, proof, identity, review, output)
    review["evidence_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        freeze_release(dataset, proof, identity, review, tmp_path / "other")


@pytest.mark.parametrize("mutation", ["empty", "duplicate", "escape", "unknown"])
def test_invalid_input_rejected(mutation):
    from eval_contracts.readiness import ReadinessDataset

    data = sample()
    if mutation == "empty":
        data["cases"] = []
    elif mutation == "duplicate":
        data["cases"].append(deepcopy(data["cases"][0]))
    elif mutation == "escape":
        data["cases"][0]["reference_path"] = "../outside"
    else:
        data["cases"][0]["tool"] = "exec"
    with pytest.raises(ValueError):
        ReadinessDataset.model_validate(data)


def test_same_output_from_wrong_path_does_not_prove_binding(tmp_path):
    from dataset_builder.readiness import assess

    dataset, proof, identity = setup_files(tmp_path)
    data = json.loads(proof.read_text())
    data["results"][0]["observed_path"] = "other.txt"
    proof.write_text(json.dumps(data))
    assert not assess(dataset, proof, identity)["ready_for_review"]


def test_builder_assertion_implementation_must_match_evidence(tmp_path):
    from dataset_builder.readiness import assess

    dataset, proof, identity = setup_files(tmp_path)
    identity["runtime"]["assertions_sha256"] = "0" * 64
    data = json.loads(proof.read_text())
    data["runner"] = identity
    proof.write_text(json.dumps(data))
    assert not assess(dataset, proof, identity)["ready_for_review"]


def test_assess_cli_fails_when_supplied_review_is_invalid(tmp_path):
    from dataset_builder.cli import main

    dataset, proof, identity = setup_files(tmp_path)
    identity_file = tmp_path / "identity.json"
    identity_file.write_text(json.dumps(identity))
    review = tmp_path / "review.json"
    review.write_text("{}")
    assert (
        main(
            [
                "assess-readiness",
                "--dataset",
                str(dataset),
                "--evidence",
                str(proof),
                "--identity",
                str(identity_file),
                "--review",
                str(review),
            ]
        )
        == 1
    )
