"""DeepEval's standalone algorithm, hosted inside an Inspect Scorer."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from inspect_ai.model import GenerateConfig, Model, get_model

from ..diagnostic_metrics import (
    METRIC_ID,
    ConversationMetricConfig,
    DiagnosticMetricResult,
)
from ..source_identity import content_identity
from .inspect import DEFAULT_BASE_URL

DEEPEVAL_VERSION = "4.2.9"
ADAPTER_VERSION = "conversation-completeness-v1"
JSON_INSTRUCTION = "\nReturn only a JSON object conforming to this JSON Schema:\n"


def _load_metric():
    """Disable implicit environment loading, telemetry and internal trace export."""
    try:
        installed = version("deepeval")
    except PackageNotFoundError as exc:
        raise ValueError(
            "DeepEval is required; reinstall agent-evaluator to enable this metric"
        ) from exc
    if installed != DEEPEVAL_VERSION:
        raise ValueError(f"Conversation metric requires deepeval=={DEEPEVAL_VERSION}")
    safe = {
        "DEEPEVAL_DISABLE_DOTENV": "1",
        "DEEPEVAL_DISABLE_LEGACY_KEYFILE": "1",
        "DEEPEVAL_TELEMETRY_OPT_OUT": "1",
        "CONFIDENT_TRACE_INTERNAL": "0",
        "CONFIDENT_TRACE_SAMPLE_RATE": "0",
    }
    os.environ.update(safe)
    from deepeval.config.settings import get_settings
    from deepeval.metrics import ConversationCompletenessMetric

    settings = get_settings()
    settings.DEEPEVAL_TELEMETRY_OPT_OUT = True
    settings.CONFIDENT_TRACE_INTERNAL = False
    settings.CONFIDENT_TRACE_SAMPLE_RATE = 0
    return ConversationCompletenessMetric


def _model_adapter(model, timeout):
    from deepeval.models import DeepEvalBaseLLM

    class InspectMetricModel(DeepEvalBaseLLM):
        def load_model(self):
            return model

        def get_model_name(self):
            return str(model)

        def generate(self, *args, **kwargs):
            raise RuntimeError("Conversation metric must use public a_measure")

        async def a_generate(self, prompt, schema=None):
            task = asyncio.current_task()
            self.active_tasks.add(task)
            try:
                return await self._generate(prompt, schema)
            finally:
                self.active_tasks.discard(task)

        async def _generate(self, prompt, schema):
            if schema is None:
                raise ValueError("Structured grading schema is required")
            output = await model.generate(
                prompt + JSON_INSTRUCTION + json.dumps(schema.model_json_schema()),
                config=GenerateConfig(
                    temperature=0,
                    max_retries=0,
                    timeout=math.ceil(timeout),
                ),
                cache=False,
            )
            if output.usage:
                self.usage.append(output.usage)
            content = output.completion.strip()
            if content.startswith("```json") and content.endswith("```"):
                content = content[7:-3].strip()
            return schema.model_validate_json(content)

    adapter = InspectMetricModel(model=str(model))
    adapter.usage = []
    adapter.active_tasks = set()
    return adapter


class ConversationMetricClient:
    def __init__(
        self, model: Model, config: ConversationMetricConfig, *, endpoint="mock"
    ):
        self.metric_type = _load_metric()
        self.model = model
        self.config = config
        self.endpoint = endpoint

    @classmethod
    def from_env(cls, config: ConversationMetricConfig):
        key, name = (
            os.getenv("DEEPSEEK_JUDGE_API_KEY"),
            os.getenv("DEEPSEEK_JUDGE_MODEL"),
        )
        if not key or not name:
            raise ValueError(
                "DEEPSEEK_JUDGE_API_KEY and DEEPSEEK_JUDGE_MODEL are required"
            )
        endpoint = os.getenv("DEEPSEEK_JUDGE_BASE_URL", DEFAULT_BASE_URL)
        return cls(
            get_model(
                f"openai-api/deepseek/{name}",
                api_key=key,
                base_url=endpoint,
                config=GenerateConfig(
                    temperature=0,
                    max_retries=0,
                    timeout=math.ceil(config.timeout_seconds),
                ),
                memoize=False,
            ),
            config,
            endpoint=endpoint,
        )

    def metadata(self):
        import deepeval

        return {
            "metric_id": METRIC_ID,
            "library": "deepeval",
            "library_version": DEEPEVAL_VERSION,
            "adapter_version": ADAPTER_VERSION,
            "runtime_sha256": content_identity(Path(deepeval.__file__).parent),
            "eval_mode": "llm",
            "model": str(self.model),
            "temperature": 0,
            "timeout_seconds": self.config.timeout_seconds,
            "max_retries": 0,
            "score_scale": "0_1",
            "gate_enabled": False,
            "scope": "actual_multi_turn",
            "strict_mode": False,
            "template": "ConversationCompletenessTemplate (bundled)",
            "json_instruction_sha256": hashlib.sha256(
                JSON_INSTRUCTION.encode()
            ).hexdigest(),
            "endpoint_sha256": hashlib.sha256(self.endpoint.encode()).hexdigest(),
        }

    async def evaluate(self, messages) -> DiagnosticMetricResult:
        from deepeval.test_case import ConversationalTestCase, Turn

        provenance = {
            "input_sha256": hashlib.sha256(
                json.dumps(
                    messages,
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            "input_turn_count": len(messages),
        }
        model = None
        issue = None
        try:
            model = _model_adapter(self.model, self.config.timeout_seconds)
            metric = self.metric_type(
                model=model,
                eval_mode="llm",
                async_mode=True,
                strict_mode=False,
                include_reason=True,
            )
            async with asyncio.timeout(self.config.timeout_seconds):
                await metric.a_measure(
                    ConversationalTestCase(
                        turns=[Turn(**item) for item in messages],
                    ),
                    _show_indicator=False,
                )
            intentions, verdicts = metric.user_intentions, metric.verdicts
            if (
                not intentions
                or any(not isinstance(i, str) or not i.strip() for i in intentions)
                or len(verdicts) != len(intentions)
                or any(v is None or v.verdict not in ("yes", "no") for v in verdicts)
                or metric.error is not None
            ):
                raise ValueError("Incomplete extracted intentions or verdicts")
            return DiagnosticMetricResult(
                status="SUCCESS",
                score=metric.score,
                reason=metric.reason,
                evidence={
                    "intentions": intentions,
                    "verdicts": [v.model_dump(mode="json") for v in verdicts],
                },
                token_usage=_usage(model),
                **provenance,
            )
        except TimeoutError:
            issue = "METRIC_TIMEOUT"
        except Exception:
            # Exception text may include HTTP credentials or business messages.
            issue = "METRIC_EVALUATION_FAILED"
        finally:
            # DeepEval gather propagates the first exception without cancelling
            # sibling model requests. Keep all work inside this metric's lifetime.
            pending = list(model.active_tasks) if model is not None else []
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        return DiagnosticMetricResult(
            status="ERROR", issue_code=issue, token_usage=_usage(model), **provenance
        )


def _usage(adapter):
    return (
        {
            "input_tokens": sum(u.input_tokens for u in adapter.usage),
            "output_tokens": sum(u.output_tokens for u in adapter.usage),
        }
        if adapter is not None and adapter.usage
        else {}
    )
