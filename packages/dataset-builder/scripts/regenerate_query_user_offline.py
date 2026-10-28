"""Regenerate the deterministic QueryUserInfo authoring workspace."""

from __future__ import annotations

import json

from dataset_builder.generation_client import ScriptedGenerationClient
from dataset_builder.pipeline import (
    build_review,
    compile_candidates,
    generate_candidates,
    prepare_generation,
    validate_draft,
)
from dataset_builder.suite_definition import ROOT, load_suite


def main() -> None:
    suite = load_suite("mini_agent_query_user_intent_v1")
    workspace = ROOT / "workspaces" / "generation_run_query_user_offline_bootstrap"
    seed = json.loads((suite.suite_dir / "seed_catalog.json").read_text())

    request = prepare_generation(suite, workspace)
    raw = generate_candidates(
        request,
        ScriptedGenerationClient(seed),
        workspace,
    )
    compile_candidates(suite, raw, workspace)
    draft = workspace / "draft.jsonl"
    report = validate_draft(suite, draft, workspace)
    if not report.valid:
        raise RuntimeError("regenerated QueryUserInfo draft did not validate")
    build_review(suite, draft, report, workspace / "review.md")


if __name__ == "__main__":
    main()
