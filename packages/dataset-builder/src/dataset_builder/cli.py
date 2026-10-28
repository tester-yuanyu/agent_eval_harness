"""Command-line interface for separated authoring lifecycle stages."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .generation_client import OpenAIResponsesGenerationClient
from .pipeline import (
    approval_from_review,
    build_review,
    compile_candidates,
    freeze_dataset,
    generate_candidates,
    ingest_response,
    prepare_generation,
    validate_draft,
)
from .schemas import GenerationRequest
from .suite_definition import load_suite


def _request(path: Path) -> GenerationRequest:
    return GenerationRequest.model_validate_json(path.read_text())


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="dataset-builder")
    commands = root.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--suite", required=True)
    prepare.add_argument("--workspace", type=Path, required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--request", type=Path, required=True)
    generate.add_argument("--workspace", type=Path, required=True)
    generate.add_argument("--backend", choices=("openai", "deepeval"), default="openai")
    ingest = commands.add_parser("ingest")
    ingest.add_argument("--request", type=Path, required=True)
    ingest.add_argument("--response", type=Path, required=True)
    ingest.add_argument("--workspace", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--suite", required=True)
    validate.add_argument("--draft", type=Path, required=True)
    review = commands.add_parser("review")
    review.add_argument("--suite", required=True)
    review.add_argument("--draft", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--suite", required=True)
    freeze.add_argument("--draft", type=Path, required=True)
    freeze.add_argument("--reviewer", required=True)
    freeze.add_argument("--review-file", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    full = commands.add_parser("generate-full")
    full.add_argument("--bundle", type=Path, required=True)
    full.add_argument("--delivery-root", type=Path, required=True)
    full.add_argument("--expected-bundle-hash", required=True)
    full.add_argument("--workspace", type=Path, required=True)
    full_validate = commands.add_parser("validate-full")
    full_validate.add_argument("--workspace", type=Path, required=True)
    nano = commands.add_parser("generate-nanobot")
    nano.add_argument("--delivery-root", type=Path, required=True)
    nano.add_argument("--expected-bundle-hash", required=True)
    nano.add_argument("--workspace", type=Path, required=True)
    nano.add_argument("--previous", type=Path)
    nano_validate = commands.add_parser("validate-nanobot")
    nano_validate.add_argument("--workspace", type=Path, required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "generate-nanobot":
            from .nanobot_generation.delivery import generate

            result = generate(
                args.delivery_root,
                args.workspace,
                args.expected_bundle_hash,
                previous=args.previous,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "validate-nanobot":
            from .nanobot_generation.delivery import verify

            result = verify(args.workspace)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["valid"] else 1
        elif args.command == "generate-full":
            from .full_generation.delivery import generate_full_dataset

            result = generate_full_dataset(
                args.bundle,
                args.delivery_root,
                args.workspace,
                args.expected_bundle_hash,
            )
            print(result.model_dump_json(indent=2))
        elif args.command == "validate-full":
            from .full_generation.delivery import verify_delivery

            result = verify_delivery(args.workspace)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["valid"] else 1
        elif args.command == "prepare":
            prepare_generation(load_suite(args.suite), args.workspace)
        elif args.command == "generate":
            request = _request(args.request)
            suite = load_suite(request.suite_id)
            if args.backend == "deepeval":
                from .deepeval_generation import DeepEvalGenerationClient

                client = DeepEvalGenerationClient.from_env(suite)
            else:
                client = OpenAIResponsesGenerationClient.from_env()
            raw = generate_candidates(
                request,
                client,
                args.workspace,
            )
            compile_candidates(suite, raw, args.workspace)
        elif args.command == "ingest":
            request = _request(args.request)
            suite = load_suite(request.suite_id)
            raw = ingest_response(request, args.response, args.workspace)
            compile_candidates(suite, raw, args.workspace)
        elif args.command == "validate":
            report = validate_draft(load_suite(args.suite), args.draft)
            print(report.model_dump_json(indent=2))
            return 0 if report.valid else 1
        elif args.command == "review":
            suite = load_suite(args.suite)
            report = validate_draft(suite, args.draft)
            build_review(suite, args.draft, report, args.output)
            return 0 if report.valid else 1
        elif args.command == "freeze":
            suite = load_suite(args.suite)
            approval = approval_from_review(
                args.draft,
                args.review_file,
                args.reviewer,
            )
            freeze_dataset(suite, args.draft, approval, args.output)
        return 0
    except Exception as exc:
        error = {"error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
