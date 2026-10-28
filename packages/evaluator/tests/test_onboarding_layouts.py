"""Delivery layout discovery must preserve the source binding."""

import json
import shutil

import pytest
from test_onboarding import compile_prepared, make_delivery, sha, write_json

from eval_framework.onboarding import prepare_input


def nested_delivery(tmp_path):
    root = make_delivery(tmp_path)
    parent = root / "source_delivery/delivery"
    parent.mkdir()
    shutil.move(str(root / "source_delivery/bundle"), parent / "bundle")

    def rebind(value):
        if isinstance(value, dict):
            return {
                key: "delivery/" + item
                if key == "path"
                and isinstance(item, str)
                and item.startswith("bundle/")
                else rebind(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [rebind(item) for item in value]
        return value

    manifest = json.loads((root / "manifest.json").read_text())
    for dataset in manifest["datasets"]:
        path = root / dataset["path"]
        rows = [rebind(json.loads(line)) for line in path.read_text().splitlines()]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        dataset["sha256"] = sha(path)
    manifest["files_sha256"] = {
        path.relative_to(root).as_posix(): sha(path)
        for path in root.rglob("*")
        if path.is_file() and path != root / "manifest.json"
    }
    write_json(root / "manifest.json", manifest)
    return root


def test_nested_delivery_bundle_compiles_without_moving_original_sources(tmp_path):
    source = nested_delivery(tmp_path)
    before = sha(source / "manifest.json")
    prepared = prepare_input(source, tmp_path / "output")
    _, compiled = compile_prepared(prepared)
    assert len(compiled[0].dataset.cases) == 1
    assert compiled[0].definition["capability_bundle"]["path"] == (
        "source_delivery/delivery/bundle/agent.json"
    )
    assert (prepared.root / "source_delivery/delivery/bundle/agent.json").is_file()
    assert not (prepared.root / "source_delivery/bundle").exists()
    assert sha(source / "manifest.json") == before


def test_multiple_manifest_bound_agent_roots_are_rejected(tmp_path):
    source = nested_delivery(tmp_path)
    original = source / "source_delivery/delivery/bundle/agent.json"
    duplicate = source / "source_delivery/bundle/agent.json"
    duplicate.parent.mkdir()
    duplicate.write_bytes(original.read_bytes())
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["files_sha256"][duplicate.relative_to(source).as_posix()] = sha(duplicate)
    write_json(source / "manifest.json", manifest)
    with pytest.raises(ValueError, match="ambiguous.*capability"):
        prepare_input(source, tmp_path / "output")


@pytest.mark.parametrize("bundle_path", ["delivery/bundle", "../outside", "missing"])
def test_hash_bound_source_manifest_controls_bundle_location(tmp_path, bundle_path):
    source = nested_delivery(tmp_path)
    declaration = source / "source_delivery/manifest.json"
    write_json(declaration, {"bundle_path": bundle_path})
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files_sha256"]["source_delivery/manifest.json"] = sha(declaration)
    write_json(manifest_path, manifest)
    if bundle_path == "delivery/bundle":
        prepared = prepare_input(source, tmp_path / "output")
        _, compiled = compile_prepared(prepared)
        assert compiled[0].definition["capability_bundle"]["path"] == (
            "source_delivery/delivery/bundle/agent.json"
        )
    else:
        with pytest.raises(ValueError, match="unsafe.*path|not bound"):
            prepare_input(source, tmp_path / "output")
