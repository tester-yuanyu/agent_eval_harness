"""Deployment isolation properties, without Docker or network access."""

import importlib.util
import json
import stat
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "local_langfuse.py"


def _module():
    spec = importlib.util.spec_from_file_location("local_langfuse_deploy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_initialization_is_local_and_does_not_inherit_cloud_credentials(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("LANGFUSE_AI_API_KEY", "must-not-leak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-leak")
    deployment = _module()
    config = tmp_path / "local.json"
    state = tmp_path / "state"
    deployment.initialize(state, config, 3100, 9190)
    compose = json.loads((state / "compose.json").read_text())
    assert "must-not-leak" not in json.dumps(compose)
    for service in compose["services"].values():
        assert all(port.startswith("127.0.0.1:") for port in service.get("ports", []))
    assert not compose["services"]["postgres"].get("ports")
    assert (
        compose["services"]["langfuse-web"]["environment"]["TELEMETRY_ENABLED"]
        == "false"
    )
    settings = json.loads(config.read_text())
    assert settings["base_url"] == "http://127.0.0.1:3100"
    assert settings["enabled"] is True
    assert settings["include_content"] is False
    assert len(settings["secret_key"]) > 30
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert stat.S_IMODE(state.stat().st_mode) == 0o700


def test_repeat_initialization_preserves_credentials_and_refuses_new_port(tmp_path):
    import pytest

    deployment = _module()
    config = tmp_path / "local.json"
    state = tmp_path / "state"
    deployment.initialize(state, config, 3000, 9090)
    before = {file: file.read_bytes() for file in state.iterdir() if file.is_file()}
    deployment.initialize(state, config, 3000, 9090)
    assert all(file.read_bytes() == content for file, content in before.items())
    with pytest.raises(ValueError, match="existing"):
        deployment.initialize(state, config, 3001, 9090)


def test_reuse_writes_profile_without_docker_start_or_credentials(
    tmp_path, monkeypatch
):
    deployment = _module()
    monkeypatch.setattr(
        deployment,
        "docker_binary",
        lambda: (_ for _ in ()).throw(AssertionError("Docker must not run")),
    )
    profile = tmp_path / "profile.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "local_langfuse.py",
            "reuse",
            "--base-url",
            "http://127.0.0.1:3100",
            "--project-id",
            "existing",
            "--profile-output",
            str(profile),
        ],
    )
    assert deployment.main() == 0
    values = json.loads(profile.read_text())
    assert values["profile"] == "local"
    assert values["project_id"] == "existing"
    assert values["base_url"] == "http://127.0.0.1:3100"
    assert "secret_key" not in values and "public_key" not in values
