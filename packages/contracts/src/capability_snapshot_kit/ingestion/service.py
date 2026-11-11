"""Create a validated, immutable delivery around an unchanged v3 bundle."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from capability_snapshot_kit.exporting import export_capability_bundle_v3
from capability_snapshot_kit.hashing import sha256_json
from capability_snapshot_kit.spec_loader import load_capability_spec_pack_v3
from capability_snapshot_kit.validation import validate_capability_bundle_v3

from .audit import audit_documents
from .models import FactDocument
from .publication import publish_delivery
from .reconcile import reconcile
from .sources import check_sources


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def export_delivery(
    output: Path,
    *,
    source_root: Path,
    spec_root: Path,
    runtime: FactDocument | None = None,
    candidate: FactDocument | None = None,
) -> dict[str, Any]:
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"delivery already exists: {output}")
    for document in (runtime, candidate):
        if document is not None:
            check_sources(document, source_root)
    effective, provenance, gaps = reconcile(runtime, candidate)
    specs = load_capability_spec_pack_v3(spec_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=output.parent) as temp:
        staging = Path(temp)
        export_capability_bundle_v3(staging / "bundle", specs, effective)
        validation = validate_capability_bundle_v3(staging / "bundle")
        write_json(staging / "source_audit.json", audit_documents(runtime, candidate))
        write_json(staging / "facts.json", effective.model_dump(mode="json"))
        write_json(staging / "provenance.json", provenance)
        write_json(staging / "gaps.json", {"gaps": gaps})
        write_json(
            staging / "validation.json",
            {
                **validation.model_dump(mode="json"),
                "execution_verified": False,
                "validation_scope": "schema_hash_references_and_source_integrity",
            },
        )
        # Retain exactly what entered reconciliation so original declarations
        # remain inspectable even when the effective status becomes unknown.
        write_json(
            staging / "inputs.json",
            {
                "collector": runtime.model_dump(mode="json") if runtime else None,
                "candidate": candidate.model_dump(mode="json") if candidate else None,
            },
        )
        agent = json.loads((staging / "bundle" / "agent.json").read_text())
        manifest = {
            "delivery_version": "1.0",
            "snapshot_format_version": "3.0",
            "bundle_path": "bundle",
            "capability_bundle_sha256": agent["capability_bundle_sha256"],
            "agent_snapshot_sha256": agent["snapshot_sha256"],
            "spec_sha256": sha256_json(specs.model_dump(mode="json")),
            "execution_verified": False,
            "files_sha256": {
                path.relative_to(staging).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in sorted(staging.rglob("*"))
                if path.is_file()
            },
        }
        write_json(staging / "manifest.json", manifest)
        for document in (runtime, candidate):
            if document is not None:
                check_sources(document, source_root)
        publish_delivery(staging, output)
    return manifest
