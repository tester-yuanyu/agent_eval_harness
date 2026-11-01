"""Upload-disabled subprocess entry point for DeepEval trace metrics."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from typing import Any

# These must be fixed before importing DeepEval through benchmark modules.
os.environ["CONFIDENT_API_KEY"] = ""
os.environ["CONFIDENT_TRACING_ENABLED"] = "NO"
os.environ["DEEPEVAL_DISABLE_DOTENV"] = "1"
os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
os.environ["DEEPEVAL_NO_INSPECT_PROMPT"] = "1"

from .agentic_metrics import score_saved_agentic_metrics  # noqa: E402
from .metrics import OpenAICompatibleJudge  # noqa: E402


class _AuditedNativeJudge(OpenAICompatibleJudge):
    """Retain failed model requests as evidence with unknown usage."""

    def generate(self, prompt: str, schema: Any = None, **kwargs: Any) -> Any:
        started = datetime.now(UTC).isoformat()
        previous_count = len(self.calls)
        try:
            return super().generate(prompt, schema=schema, **kwargs)
        except Exception as exc:
            if len(self.calls) == previous_count:
                content = prompt
                if schema is not None:
                    content += (
                        "\nReturn only a JSON object matching this schema:\n"
                        + json.dumps(schema.model_json_schema())
                    )
                self.calls.append(
                    {
                        "type": "generation",
                        "name": "deepeval_native_judge",
                        "model": self.model_name,
                        "start_time": started,
                        "end_time": datetime.now(UTC).isoformat(),
                        "input": content,
                        "output": None,
                        "error": type(exc).__name__,
                        "usage": {
                            "input_tokens": None,
                            "output_tokens": None,
                            "cost_usd": None,
                        },
                    }
                )
            raise


def main() -> int:
    payload = json.load(sys.stdin)
    judge = _AuditedNativeJudge(payload["model_config"])
    try:
        with tempfile.TemporaryDirectory(prefix="agent-eval-native-") as directory:
            with contextlib.redirect_stdout(sys.stderr):
                records = score_saved_agentic_metrics(
                    payload["task"],
                    payload["observation"],
                    judge,
                    dimensions=payload["dimensions"],
                    max_model_requests=payload.get("max_model_requests"),
                    work_dir=directory,
                )
    finally:
        judge.client.close()
    json.dump(records, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
