"""Fixed tool tasks, Inspect execution and DeepEval scoring.

Benchmark imports are offline by default. Explicit Judge and Langfuse clients
use their own configuration and remain opt-in.
"""

import os

# Package initialisation runs before ``benchmark.metrics`` imports DeepEval.
# Force the public Python entry point to share the CLI/worker isolation boundary
# instead of relying on fixtures or callers to set these flags early enough.
os.environ.update(
    {
        "CONFIDENT_API_KEY": "",
        "CONFIDENT_TRACING_ENABLED": "NO",
        "CONFIDENT_TRACE_INTERNAL": "0",
        "CONFIDENT_TRACE_SAMPLE_RATE": "0",
        "DEEPEVAL_DISABLE_DOTENV": "1",
        "DEEPEVAL_DISABLE_LEGACY_KEYFILE": "1",
        "DEEPEVAL_TELEMETRY_OPT_OUT": "1",
        "DEEPEVAL_NO_INSPECT_PROMPT": "1",
    }
)
