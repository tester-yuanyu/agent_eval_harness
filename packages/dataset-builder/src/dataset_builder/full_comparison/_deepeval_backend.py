# ruff: noqa: E501
# Preserve the original SDK prompt transport text.
"""Optional DeepEval model adapter, imported only by that backend."""
from deepeval.models import DeepSeekModel

from .backend import canonical, strict_sdk_value


class ControlledDeepSeek(DeepSeekModel):
    def __init__(self, provider, key):
        self.provider = provider
        super().__init__(
            model=provider.model,
            api_key=key,
            temperature=0.4,
            cost_per_input_token=0.3 / 1e6,
            cost_per_output_token=1.2 / 1e6,
        )

    def generate(self, prompt, schema=None, audio=None):
        if audio:
            raise ValueError("text-only experiment")
        if schema is not None:
            prompt += (
                "\nFINAL SDK TRANSPORT CONTRACT (takes priority over embedded candidate schemas): "
                + canonical(schema.model_json_schema())
                + "\nRespond ONLY with JSON matching this transport schema. All string fields, especially input, "
                "must remain JSON strings, never objects. If a string contains JSON, serialize it once with normal JSON escaping. "
                "Do not add candidate-envelope fields to the outer transport response. The candidate instructions describe the CONTENT of the string only."
            )
        else:
            prompt += "\nReturn only the requested Candidate JSON object without markdown fences or explanatory text."
        raw, cost = self.provider.complete(prompt, json_mode=True)
        return (strict_sdk_value(raw, schema) if schema else raw), cost

    async def a_generate(self, *args, **kwargs):
        raise RuntimeError("per-slot generation must be synchronous")

