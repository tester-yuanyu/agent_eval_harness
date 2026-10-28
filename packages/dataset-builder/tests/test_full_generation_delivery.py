import shutil

import pytest
from test_full_generation_inventory import DELIVERY, HASH


def run(output, source=DELIVERY):
    from dataset_builder.full_generation.delivery import generate_full_dataset

    return generate_full_dataset(source / "bundle", source, output, HASH)


def test_existing_output_is_not_overwritten(tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    (out / "keep").write_text("unchanged")
    with pytest.raises(FileExistsError):
        run(out)
    assert (out / "keep").read_text() == "unchanged"


def test_mid_generation_failure_does_not_publish(tmp_path, monkeypatch):
    from dataset_builder.full_generation import delivery

    def fail(*args):
        raise RuntimeError("simulated disk/report failure")

    monkeypatch.setattr(delivery, "_before_publish", fail)
    with pytest.raises(RuntimeError):
        run(tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_bundle_mutation_before_publish_rejected(tmp_path, monkeypatch):
    from dataset_builder.full_generation import delivery

    source = tmp_path / "source"
    shutil.copytree(DELIVERY, source)

    def change(*args):
        (source / "bundle/agent.json").write_text("{}")

    monkeypatch.setattr(delivery, "_before_publish", change)
    with pytest.raises(ValueError):
        run(tmp_path / "output", source)
    assert not (tmp_path / "output").exists()


def test_review_starts_unchecked_and_counts_match(tmp_path):
    import json

    from dataset_builder.full_generation.delivery import verify_delivery

    out = tmp_path / "output"
    report = run(out)
    assert report.valid
    assert "- [x]" not in (out / "review.md").read_text()
    assert "- [ ]" in (out / "review.md").read_text()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["state"] == "DRAFT"
    assert len(json.loads((out / "coverage_matrix.json").read_text())["targets"]) == 23
    assert verify_delivery(out)["valid"]
    path = out / manifest["datasets"][0]["path"]
    path.write_text(path.read_text() + "\n")
    assert not verify_delivery(out)["valid"]


def test_cli_entry_exists():
    from dataset_builder.cli import parser

    args = parser().parse_args(
        [
            "generate-full",
            "--bundle",
            str(DELIVERY / "bundle"),
            "--delivery-root",
            str(DELIVERY),
            "--expected-bundle-hash",
            HASH,
            "--workspace",
            "/tmp/example",
        ]
    )
    assert args.command == "generate-full"
