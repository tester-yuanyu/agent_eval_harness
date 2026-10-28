"""Environment-only configuration for the minimal Agent."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, SecretStr


class AppConfig(BaseModel):
    """Environment configuration for supported model providers."""

    model_config = ConfigDict(extra="forbid")

    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    deepseek_api_key: SecretStr | None = None
    deepseek_model: str | None = None


def load_config(env_file: str | Path | None = None) -> AppConfig:
    """Load configuration without supplying secret or model defaults."""

    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)

    return AppConfig(
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL"),
    )
