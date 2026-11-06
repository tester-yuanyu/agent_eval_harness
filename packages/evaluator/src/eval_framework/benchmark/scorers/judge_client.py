"""显式 opt-in 的 DeepEval 模型客户端；只记录实际请求用量。"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any

from deepeval.models import DeepEvalBaseLLM


class OpenAICompatibleJudge(DeepEvalBaseLLM):
    """Opt-in public DeepEval model adapter with bounded calls and actual usage."""

    def __init__(self, config: dict[str, Any]):
        from openai import OpenAI

        self.model_name = config["model"]
        self.max_tokens = int(config.get("max_tokens", 1000))
        self.extra_body = dict(config.get("extra_body", {}))
        key = config.get("api_key") or os.environ.get(
            config.get("api_key_env", "OPENAI_API_KEY")
        )
        if not key:
            raise ValueError("Judge API key is not configured")
        self.client = OpenAI(
            api_key=key,
            base_url=config.get("base_url"),
            timeout=float(config.get("timeout", 45)),
            max_retries=0,
        )
        self.calls: list[dict[str, Any]] = []
        super().__init__(model=self.model_name)

    def load_model(self) -> Any:
        return self.client

    def get_model_name(self) -> str:
        return self.model_name

    def supports_log_probs(self) -> bool:
        return False

    def generate(self, prompt: str, schema: Any = None, **_kwargs: Any) -> Any:
        content = prompt
        if schema is not None:
            content += (
                "\nReturn only a JSON object matching this schema:\n"
                + json.dumps(schema.model_json_schema())
            )
        started = datetime.now(UTC).isoformat()
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": content}],
            temperature=0,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
            extra_body=self.extra_body,
        )
        output = response.choices[0].message.content or ""
        usage = response.usage
        self.calls.append(
            {
                "type": "generation",
                "name": "deepeval_response_judge",
                "model": self.model_name,
                "response_model": getattr(response, "model", None),
                "start_time": started,
                "end_time": datetime.now(UTC).isoformat(),
                "input": content,
                "output": output,
                "usage": {
                    "input_tokens": getattr(usage, "prompt_tokens", None),
                    "output_tokens": getattr(usage, "completion_tokens", None),
                    "cost_usd": None,
                },
            }
        )
        if schema is None:
            return output
        return schema.model_validate_json(output)

    async def a_generate(self, prompt: str, schema: Any = None, **kwargs: Any) -> Any:
        return await asyncio.to_thread(self.generate, prompt, schema=schema, **kwargs)
