"""Build inputs are a content-bound copy of runtime sources, never a home mount."""

import json
import subprocess


def test_context_excludes_secrets_git_and_venv_and_changes_with_source(tmp_path):
    from eval_framework.benchmark.inspect_docker import prepare_docker_sandbox

    root = tmp_path / "source"
    (root / "nanobot").mkdir(parents=True)
    (root / "nanobot/__init__.py").write_text("VALUE = 1\n")
    (root / "pyproject.toml").write_text(
        '[project]\nname="tiny"\nversion="1"\ndependencies=[]\n'
    )
    (root / ".env").write_text("API_KEY=do-not-copy")
    (root / "nanobot/.env").write_text("API_KEY=do-not-copy")
    (root / ".venv").mkdir()
    (root / ".venv/secret").write_text("do-not-copy")
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "add", "nanobot/__init__.py", "pyproject.toml"],
        check=True,
    )
    config = {
        "nanobot_root": str(root),
        "model": "mockllm/model",
        "tokenizer_mode": "byte_fallback",
    }
    first = prepare_docker_sandbox(config, tmp_path / "build")
    assert first[0] == "docker"
    context = __import__("pathlib").Path(first[1]).parent
    assert not list(context.rglob(".git"))
    assert not list(context.rglob(".env"))
    assert not list(context.rglob(".venv"))
    assert (context / "source/nanobot/__init__.py").read_text() == "VALUE = 1\n"
    first_manifest = json.loads((context / "source-manifest.json").read_text())
    (root / "nanobot/__init__.py").write_text("VALUE = 2\n")
    second = prepare_docker_sandbox(config, tmp_path / "build")
    second_manifest = json.loads(
        (
            __import__("pathlib").Path(second[1]).parent / "source-manifest.json"
        ).read_text()
    )
    assert first_manifest["source_sha256"] != second_manifest["source_sha256"]
    assert first[1] != second[1]


def test_environment_binding_rejects_rebuilt_image_and_dependency_drift(
    tmp_path, monkeypatch
):
    import pytest

    from eval_framework.benchmark import inspect_docker

    compose = tmp_path / "sandbox-build" / "hash" / "compose.json"
    compose.parent.mkdir(parents=True)
    compose.write_text(json.dumps({"services": {"default": {"image": "test:tag"}}}))
    image_id = ["sha256:first"]
    monkeypatch.setattr(inspect_docker, "docker_image_id", lambda image: image_id[0])
    env = {"python": "3.11", "packages": {"nanobot": "1"}}
    inspect_docker.bind_docker_environment(str(compose), env)
    binding = tmp_path / "sandbox-environment.json"
    original = binding.read_bytes()
    assert json.loads(original)["image_id"] == "sha256:first"
    inspect_docker.bind_docker_environment(str(compose), env)
    assert binding.read_bytes() == original
    image_id[0] = "sha256:rebuilt"
    with pytest.raises(inspect_docker.SandboxEnvironmentChanged):
        inspect_docker.bind_docker_environment(str(compose))
    image_id[0] = "sha256:first"
    with pytest.raises(inspect_docker.SandboxEnvironmentChanged):
        inspect_docker.bind_docker_environment(str(compose), {"python": "3.12"})
    assert binding.read_bytes() == original


def test_saved_samples_cannot_resume_with_a_missing_environment_binding(tmp_path):
    import pytest

    from eval_framework.benchmark.inspect_docker import (
        SandboxEnvironmentChanged,
        bind_docker_environment,
    )

    compose = tmp_path / "sandbox-build/hash/compose.json"
    compose.parent.mkdir(parents=True)
    compose.write_text("{}")
    (tmp_path / "inspect").mkdir()
    (tmp_path / "inspect/old.eval").touch()
    with pytest.raises(
        SandboxEnvironmentChanged, match="no Docker environment binding"
    ):
        bind_docker_environment(str(compose))
