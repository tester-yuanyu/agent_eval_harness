from minimal_agent.runtime.config import load_config


def test_config_reads_openai_values_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    monkeypatch.setenv("OPENAI_MODEL", "configured-model")

    config = load_config()

    assert config.openai_api_key is not None
    assert config.openai_api_key.get_secret_value() == "test-only-key"
    assert config.openai_model == "configured-model"


def test_config_has_no_secret_or_model_defaults(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    config = load_config()

    assert config.openai_api_key is None
    assert config.openai_model is None


def test_config_reads_deepseek_values_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")

    config = load_config()

    assert config.deepseek_api_key is not None
    assert config.deepseek_api_key.get_secret_value() == "deepseek-test-key"
    assert config.deepseek_model == "deepseek-flash"
