import json
from pathlib import Path

import pytest


def staged(tmp_path):
    path = tmp_path / "staging"
    path.mkdir()
    (path / "manifest.json").write_text(json.dumps({"state": "complete"}))
    (path / "bundle").mkdir()
    (path / "bundle/agent.json").write_text("{}")
    (path / "facts.json").write_text("{}")
    return path


def test_manifest_is_last_and_existing_output_is_not_replaced(tmp_path, monkeypatch):
    from capability_snapshot_kit.ingestion import publication

    source = staged(tmp_path)
    output = tmp_path / "out"
    order = []
    real = publication.os.replace

    def observe(src, dst):
        if Path(src).name == "manifest.json":
            assert (output / "bundle/agent.json").is_file() and (
                output / "facts.json"
            ).is_file()
        else:
            assert not (output / "manifest.json").exists()
        order.append(Path(src).name)
        return real(src, dst)

    monkeypatch.setattr(publication.os, "replace", observe)
    publication.publish_delivery(source, output)
    assert order[-1] == "manifest.json"
    with pytest.raises(FileExistsError):
        publication.publish_delivery(output, output)
    assert (output / "bundle/agent.json").is_file()


@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_publication_failure_removes_only_new_partial_output(
    tmp_path, monkeypatch, fail_at
):
    from capability_snapshot_kit.ingestion import publication

    source = staged(tmp_path)
    output = tmp_path / "out"
    real = publication.os.replace
    calls = 0

    def fail(src, dst):
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise OSError("simulated write failure")
        return real(src, dst)

    monkeypatch.setattr(publication.os, "replace", fail)
    with pytest.raises(OSError):
        publication.publish_delivery(source, output)
    assert not output.exists()
