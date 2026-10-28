"""Mini Agent compatibility normalization over the neutral capability loader."""

from __future__ import annotations

from pathlib import Path

from ...capabilities import CapabilityBundle
from ...capability_loader import load_capability_bundle


def load_mini_agent_capability_bundle(
    root: Path,
    *,
    expected_sha256: str | None = None,
) -> CapabilityBundle:
    bundle = load_capability_bundle(root, expected_sha256=expected_sha256)
    # Legacy bundles were already normalized by their source-owned loader.
    if (Path(root) / "bundle_manifest.json").is_file():
        return bundle
    documents = []
    for document in bundle.documents:
        payload = dict(document.payload)
        if document.snapshot_type == "tool":
            idempotency = payload.get("idempotency_rules")
            read_only = (
                isinstance(idempotency, dict)
                and idempotency.get("mode") == "READ_ONLY"
            )
            payload["tool_type"] = "read" if read_only else "write"
            simulations = payload.get("simulation_capabilities", [])
            payload["fault_modes"] = (
                simulations if isinstance(simulations, list) else []
            )
        documents.append(document.model_copy(update={"payload": payload}))
    return bundle.model_copy(update={"documents": tuple(documents)})
