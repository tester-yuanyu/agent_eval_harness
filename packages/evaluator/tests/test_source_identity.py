def test_content_identity_covers_uncommitted_runtime_and_templates(tmp_path):
    from eval_framework.source_identity import content_identity

    package = tmp_path / "package"
    package.mkdir()
    (package / "rule.py").write_text("answer = 1\n")
    (package / "rubric.json").write_text('{"version": 1}')
    before = content_identity(package)
    (package / "rule.py").write_text("answer = 2\n")
    assert content_identity(package) != before
    before = content_identity(package)
    (package / "rubric.json").write_text('{"version": 2}')
    assert content_identity(package) != before
    before = content_identity(package)
    (package / "__pycache__").mkdir()
    (package / "__pycache__/rule.pyc").write_bytes(b"cache")
    assert content_identity(package) == before
    (package / "capability.md").write_text("Runtime contract version 1\n")
    before = content_identity(package)
    (package / "capability.md").write_text("Runtime contract version 2\n")
    assert content_identity(package) != before


def test_engine_identity_includes_running_source_and_extension():
    from importlib.metadata import version

    from eval_framework.inspect_engine import backend_metadata

    identity = backend_metadata()
    assert identity["source"]["distribution"] == "inspect_ai"
    assert identity["source"]["distribution_version"] == version("inspect_ai")
    assert len(identity["source"]["runtime_sha256"]) == 64
    assert len(identity["extension_sha256"]) == 64
    assert len(identity["contracts_sha256"]) == 64
    assert len(identity["capability_protocol_sha256"]) == 64


def test_checkpoint_reuses_bytes_but_rechecks_same_size_mtime_edits(
    tmp_path, monkeypatch
):
    import os
    from pathlib import Path

    from eval_framework.source_identity import content_identity, identity_checkpoint

    source = tmp_path / "rule.py"
    source.write_text("answer=1")
    stat = source.stat()
    reads = []
    original = Path.read_bytes

    def read(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    with identity_checkpoint():
        before = content_identity(tmp_path)
        assert content_identity(tmp_path) == before
    assert reads.count(source) == 1
    source.write_text("answer=2")
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with identity_checkpoint():
        after = content_identity(tmp_path)
    assert before != after
    source.unlink()
    with identity_checkpoint():
        assert content_identity(tmp_path) != after


def test_checkpoint_exception_resets_and_child_task_does_not_share_snapshot(tmp_path):
    import asyncio

    import pytest

    from eval_framework.source_identity import content_identity, identity_checkpoint

    source = tmp_path / "rule.py"
    source.write_text("first")
    with pytest.raises(RuntimeError), identity_checkpoint():
        original = content_identity(tmp_path)
        raise RuntimeError("leave checkpoint")
    source.write_text("second")
    assert content_identity(tmp_path) != original

    async def child():
        source.write_text("third")
        return content_identity(tmp_path)

    async def parent():
        with identity_checkpoint():
            before = content_identity(tmp_path)
            after = await asyncio.create_task(child())
            assert after != before

    asyncio.run(parent())
