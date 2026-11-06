"""Offline worker: reuse ExternalProvider without a second execution lifecycle."""

from __future__ import annotations

import json
import sys

from eval_framework.agent_adapter import execute_provider_request
from eval_framework.capabilities import CapabilityBundle, CapabilityRegistry
from eval_framework.providers.external import ExternalProvider, RuntimeBinding
from eval_framework.schemas import ExecutionProfile


def create_provider() -> ExternalProvider:
    return ExternalProvider(
        RuntimeBinding(version="1.0", agent_id="existing", adapter="static"),
        CapabilityRegistry(
            CapabilityBundle(
                root=".",
                provider_id="existing",
                bundle_format_version="3.0",
                capability_bundle_sha256="a" * 64,
                documents=(),
            )
        ),
        execution_profiles={"none": ExecutionProfile(allowed_tools=[])},
    )


if __name__ == "__main__":
    print(json.dumps(execute_provider_request(create_provider(), json.load(sys.stdin))))
