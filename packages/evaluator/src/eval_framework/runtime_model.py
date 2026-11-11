"""Neutral Inspect model factory; credentials stay in the host Inspect process."""

from __future__ import annotations

import os


def inspect_model(config: dict):
    """Only Inspect receives provider credentials; workers receive a proxy token."""
    from inspect_ai.model import GenerateConfig, get_model

    name = str(config.get("inspect_model") or config.get("model", "mockllm/model"))
    if "/" not in name:
        name = "openai/" + name
    key = os.environ.get(config.get("api_key_env", "DEEPSEEK_API_KEY"))
    if not name.startswith("mockllm/") and not key:
        raise ValueError(f"missing {config.get('api_key_env', 'DEEPSEEK_API_KEY')}")
    return get_model(
        name,
        base_url=config.get("base_url"),
        api_key=key,
        config=GenerateConfig(
            temperature=config.get("temperature", 0),
            max_tokens=config.get("max_tokens", 2048),
            extra_body=config.get("extra_body"),
            max_retries=0,
        ),
    )
