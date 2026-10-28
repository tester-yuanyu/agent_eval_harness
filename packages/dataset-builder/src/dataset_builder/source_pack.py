"""Source-pack loading and hashing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .suite_definition import SuiteDefinition


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def build_source_pack(
    suite: SuiteDefinition, snapshot_files: tuple[Path, ...] = ()
) -> tuple[str, list[dict[str, str]]]:
    # The legacy argument is intentionally ignored: raw protocol snapshots are
    # never authoring inputs after deterministic conversion to Capability IR.
    del snapshot_files
    ir = suite.capability_ir
    ir_text = json.dumps(ir.model_dump(mode="json"), ensure_ascii=False, indent=2)
    sections: list[str] = [f"# Capability IR\n\n{ir_text}"]
    manifest: list[dict[str, str]] = [
        {
            "path": f"capability-ir://{suite.suite_id}",
            "sha256": ir.canonical_sha256,
        }
    ]
    for path in suite.source_files:
        if not path.is_file():
            raise FileNotFoundError(f"source-pack file missing: {path}")
        raw = path.read_bytes()
        sections.append(f"# 来源文件：{path.name}\n\n{raw.decode('utf-8').strip()}")
        manifest.append({"path": str(path), "sha256": sha256_bytes(raw)})
    return "\n\n---\n\n".join(sections) + "\n", manifest
