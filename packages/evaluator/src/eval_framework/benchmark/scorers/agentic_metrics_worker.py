"""Upload-disabled subprocess entry point for DeepEval trace metrics."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile

# These must be fixed before importing DeepEval through benchmark modules.
os.environ["CONFIDENT_API_KEY"] = ""
os.environ["CONFIDENT_TRACING_ENABLED"] = "NO"
os.environ["DEEPEVAL_DISABLE_DOTENV"] = "1"
os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
os.environ["DEEPEVAL_NO_INSPECT_PROMPT"] = "1"

from .agentic_metrics import score_saved_agentic_metrics  # noqa: E402
from .judge_client import AuditedJudge  # noqa: E402


class _AuditedNativeJudge(AuditedJudge):
    """Preserve the native worker's historical failed-request event name."""

    failure_event_name = "deepeval_native_judge"


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
