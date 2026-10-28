"""Injectable machine-readable CLI for the Capability Snapshot Protocol."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from capability_snapshot_kit.adapter import CapabilityAdapterV3
from capability_snapshot_kit.diffing import diff_capability_bundles_v3
from capability_snapshot_kit.exporting import export_capability_bundle_v3
from capability_snapshot_kit.resolution import (
    CapabilitySelectionV3,
    resolve_capability_graph_v3,
)
from capability_snapshot_kit.spec_loader import load_capability_spec_pack_v3
from capability_snapshot_kit.validation import (
    CapabilityBundleValidationErrorV3,
    load_capability_bundle_v3,
    validate_capability_bundle_v3,
)
from capability_snapshot_kit.versions import SNAPSHOT_FORMAT_VERSION_V3


def _parser(default_spec_root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="capability-snapshot-kit")
    subparsers = parser.add_subparsers(dest="command", required=True)
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--output", required=True, type=Path)
    export_parser.add_argument("--spec-root", type=Path, default=default_spec_root)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--input", required=True, type=Path)
    resolve_parser = subparsers.add_parser("resolve")
    resolve_parser.add_argument("--input", required=True, type=Path)
    resolve_parser.add_argument("--selection", required=True, type=Path)
    diff_parser = subparsers.add_parser("diff")
    diff_parser.add_argument("--old", required=True, type=Path)
    diff_parser.add_argument("--new", required=True, type=Path)
    return parser


def _require_v3(root: Path) -> None:
    payload = json.loads((root / "agent.json").read_text(encoding="utf-8"))
    actual = payload.get("snapshot_format_version")
    if actual != SNAPSHOT_FORMAT_VERSION_V3:
        raise ValueError(
            "snapshot format mismatch: expected "
            f"{SNAPSHOT_FORMAT_VERSION_V3!r}, got {actual!r}"
        )


def _selection(path: Path) -> CapabilitySelectionV3:
    return CapabilitySelectionV3.model_validate_json(path.read_text(encoding="utf-8"))


def main(
    argv: Sequence[str] | None = None,
    *,
    adapter_factory: Callable[[], CapabilityAdapterV3],
    default_spec_root: str | Path,
) -> int:
    """Run the portable CLI with host-owned Adapter construction injected."""

    arguments = _parser(Path(default_spec_root)).parse_args(argv)
    try:
        if arguments.command == "export":
            specs = load_capability_spec_pack_v3(arguments.spec_root)
            paths = export_capability_bundle_v3(
                arguments.output,
                specs,
                adapter_factory(),
            )
            result = validate_capability_bundle_v3(arguments.output).model_dump(
                mode="json"
            )
            result = {
                "status": "OK",
                "artifact_count": len(paths),
                "output": str(arguments.output),
                **result,
            }
        elif arguments.command == "validate":
            _require_v3(arguments.input)
            result = validate_capability_bundle_v3(arguments.input).model_dump(
                mode="json"
            )
        elif arguments.command == "resolve":
            _require_v3(arguments.input)
            result = resolve_capability_graph_v3(
                load_capability_bundle_v3(arguments.input),
                _selection(arguments.selection),
            ).model_dump(mode="json")
        else:
            _require_v3(arguments.old)
            _require_v3(arguments.new)
            result = diff_capability_bundles_v3(
                arguments.old,
                arguments.new,
            ).model_dump(mode="json")
    except (CapabilityBundleValidationErrorV3, OSError, ValueError) as exc:
        error: dict[str, Any] = {
            "status": "ERROR",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        print(json.dumps(error, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0
