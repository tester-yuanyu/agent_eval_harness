"""Contain evidence-channel failures without changing Agent execution results."""

import json
import os
import tempfile
from pathlib import Path

from agent_trace_sdk import EvidenceReader, status_for


def atomic_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)



def finish_evidence(sink, *, execution_completed, association):
    issues = []
    try:
        sink.finish(execution_completed=execution_completed)
    except Exception:
        issues.append({"kind": "export", "code": "EVIDENCE_FINISH_FAILED"})
    try:
        memory = sink.manifest()
    except Exception:
        memory = None
        issues.append({"kind": "export", "code": "EVIDENCE_MANIFEST_FAILED"})
    try:
        events, manifest = EvidenceReader().read(sink.directory, memory_manifest=memory)
    except Exception:
        # Never rescue a failed independent read with embedded Agent events.
        events = []
        manifest = memory or {
            "execution_completed": False,
            "collection_closed": False,
            "issues": [],
        }
        issues.append({"kind": "export", "code": "EVIDENCE_READ_FAILED"})
    try:
        saved = json.loads((sink.directory / "association.json").read_text())
        if saved != association or manifest.get("trace_id") != association["trace_id"]:
            raise ValueError("association mismatch")
        if any(event.get("trace_id") != association["trace_id"] for event in events):
            raise ValueError("event association mismatch")
    except (OSError, ValueError):
        issues.append({"kind": "export", "code": "EVIDENCE_ASSOCIATION_FAILED"})
        # Unassociated events remain on disk, but cannot establish a Trial verdict.
        events = []
    manifest.setdefault("issues", []).extend(issues)
    manifest["status"] = status_for(
        manifest["issues"],
        completed=manifest.get("execution_completed", False)
        and manifest.get("collection_closed", False),
    )
    return events, manifest
