"""Standalone CLI for extraction, trusted collectors and immutable deliveries."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path

from capability_snapshot_kit.cli import main as protocol_main
from capability_snapshot_kit.spec_loader import load_capability_spec_pack_v3

from .models import FactDocument
from .providers import collect_document, load_plugin
from .requests import (
    ExtractionRequest,
    check_candidate_request,
    extract_document,
    prepare_request,
)
from .service import export_delivery


def profile_path(name: str) -> Path:
    if name != "conversation":
        raise ValueError(f"unknown profile: {name}")
    return Path(
        str(files("capability_snapshot_kit").joinpath("resources/conversation"))
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="capability-snapshot")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema", help="Print the versioned FactDocument input schema")
    prepare = commands.add_parser("prepare", help="Prepare an offline LLM request")
    prepare.add_argument("--source-root", type=Path, default=Path.cwd())
    prepare.add_argument("--include", action="append", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare_specs = prepare.add_mutually_exclusive_group()
    prepare_specs.add_argument("--spec-root", type=Path)
    prepare_specs.add_argument("--profile", choices=["conversation"])
    extract = commands.add_parser(
        "extract", help="Run an explicitly selected LLM plugin"
    )
    extract.add_argument("--request", type=Path, required=True)
    extract.add_argument(
        "--extractor", required=True, help="Trusted local module:factory"
    )
    extract.add_argument("--output", type=Path, required=True)
    export = commands.add_parser("export", help="Compile a source-backed delivery")
    export.add_argument(
        "--collector", help="Trusted local module:factory; executes Python"
    )
    export.add_argument("--candidate", type=Path)
    export.add_argument("--request", type=Path)
    export.add_argument("--source-root", type=Path, default=Path.cwd())
    specs = export.add_mutually_exclusive_group(required=True)
    specs.add_argument("--spec-root", type=Path)
    specs.add_argument("--profile", choices=["conversation"])
    export.add_argument("--output", type=Path, required=True)
    for name in ("validate", "resolve", "diff"):
        commands.add_parser(name, help="Existing Snapshot 3.0 protocol command")
    return parser


def _exclusive_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"validate", "resolve", "diff"}:
        return protocol_main(args, adapter_factory=lambda: None, default_spec_root=".")
    parsed = _parser().parse_args(args)
    try:
        if parsed.command == "schema":
            result = FactDocument.model_json_schema()
        elif parsed.command == "prepare":
            request = prepare_request(
                parsed.source_root,
                parsed.include,
                parsed.spec_root or profile_path(parsed.profile or "conversation"),
            )
            _exclusive_json(parsed.output, request.model_dump(mode="json"))
            result = {"status": "OK", "request": str(parsed.output)}
        elif parsed.command == "extract":
            request = ExtractionRequest.model_validate_json(parsed.request.read_text())
            if parsed.output.exists() or parsed.output.is_symlink():
                raise FileExistsError(f"output already exists: {parsed.output}")
            candidate = extract_document(
                load_plugin(parsed.extractor, "extract"), request
            )
            _exclusive_json(parsed.output, candidate.model_dump(mode="json"))
            result = {
                "status": "OK",
                "candidate": str(parsed.output),
                "basis": "declared",
            }
        else:
            if not parsed.collector and not parsed.candidate:
                raise ValueError("export requires --collector or --candidate")
            if parsed.request and not parsed.candidate:
                raise ValueError("--request requires --candidate")
            if parsed.output.exists() or parsed.output.is_symlink():
                raise FileExistsError(f"delivery already exists: {parsed.output}")
            runtime = (
                collect_document(
                    load_plugin(parsed.collector, "collect"), parsed.source_root
                )
                if parsed.collector
                else None
            )
            candidate = (
                FactDocument.model_validate_json(parsed.candidate.read_text())
                if parsed.candidate
                else None
            )
            if parsed.request:
                request = ExtractionRequest.model_validate_json(
                    parsed.request.read_text()
                )
                check_candidate_request(candidate, request)
                selected_spec = load_capability_spec_pack_v3(
                    parsed.spec_root or profile_path(parsed.profile)
                ).model_dump(mode="json")
                if request.evaluation_spec != selected_spec:
                    raise ValueError("export profile differs from extraction request")
            result = export_delivery(
                parsed.output,
                source_root=parsed.source_root,
                spec_root=parsed.spec_root or profile_path(parsed.profile),
                runtime=runtime,
                candidate=candidate,
            )
            result = {
                "status": "OK",
                "output": str(parsed.output),
                "capability_bundle_sha256": result["capability_bundle_sha256"],
            }
    except Exception as exc:
        # Plugin exceptions become machine-readable failures, never a partial success.
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0
