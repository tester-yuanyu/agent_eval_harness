from pathlib import Path


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


def test_engine_identity_includes_running_source_and_extension():
    import inspect_ai

    from eval_framework.inspect_engine import backend_metadata

    identity = backend_metadata()
    assert (
        identity["source"]["upstream_commit"]
        == "dfcb169e1cb170a8fbe2c37a0e3befc45c2c2b85"
    )
    assert len(identity["source"]["runtime_sha256"]) == 64
    assert len(identity["extension_sha256"]) == 64
    assert "third_party/inspect_ai/src/inspect_ai" in str(
        Path(inspect_ai.__file__).resolve()
    )
