from __future__ import annotations

import json
import shutil
from pathlib import Path

from dataset_builder.capability_bundle import calculate_artifact_sha256
from dataset_builder.generation_client import ScriptedGenerationClient
from dataset_builder.pipeline import (
    compile_candidates,
    generate_candidates,
    prepare_generation,
    validate_draft,
)
from dataset_builder.suite_definition import load_suite_from_path

ROOT = Path(__file__).resolve().parents[1]
MINI_AGENT_CAPABILITIES = ROOT.parents[1] / "examples/mini_agent" / "capabilities"


def _synthetic_suite(tmp_path: Path):
    suite_dir = tmp_path / "echo_agent_suite"
    shutil.copytree(ROOT / "suites" / "mini_agent_query_gift_intent_v1", suite_dir)
    shutil.copytree(MINI_AGENT_CAPABILITIES, suite_dir / "capabilities")
    (suite_dir / "outputs").mkdir()

    agent_path = suite_dir / "capabilities" / "agent.json"
    agent = json.loads(agent_path.read_text())
    agent["agent_id"] = "echo_agent"
    agent["snapshot_id"] = "agent.echo_agent"
    agent["contract_version"] = "echo-agent-capability-contract-v3"
    agent["snapshot_sha256"] = calculate_artifact_sha256(agent)
    agent_path.write_text(json.dumps(agent, ensure_ascii=False, indent=2) + "\n")

    config_path = suite_dir / "suite.json"
    config = json.loads(config_path.read_text())
    config["metadata"].update(
        {
            "suite_id": "echo_agent_query_gift_intent_v1",
            "target_agent": "echo_agent",
            "prompt_version": "echo-agent-query-gift-v1",
        }
    )
    config["capability_input"]["bundle"] = {
        "base": "suite_dir",
        "path": "capabilities",
    }
    config["paths"]["freeze_output"] = {
        "base": "suite_dir",
        "path": "outputs/frozen.jsonl",
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    return load_suite_from_path(config_path)


def test_second_agent_uses_same_policy_pipeline_without_identity_adapter(tmp_path):
    suite = _synthetic_suite(tmp_path)
    workspace = tmp_path / "run"

    request = prepare_generation(suite, workspace)
    seed = json.loads(suite.seed_catalog_path.read_text())
    raw = generate_candidates(
        request,
        ScriptedGenerationClient(seed),
        workspace,
    )
    cases = compile_candidates(suite, raw, workspace)
    draft = workspace / "draft.jsonl"
    report = validate_draft(suite, draft, workspace)

    assert report.valid
    assert len(cases) == suite.coverage_plan["case_count"]
    assert request.agent_snapshot_sha256 == (
        suite.validated_capability_bundle.root.snapshot_sha256
    )
    assert request.capability_bundle_sha256 == (
        suite.validated_capability_bundle.capability_bundle_sha256
    )
    assert request.policy_bindings == list(suite.policy_bindings)
    assert {item["role"] for item in request.plugin_bindings} == {
        "snapshot_loader",
        "capability_adapter",
        "capability_resolver",
        "source_pack_compiler",
        "coverage_planner",
        "case_generator",
        "validation_gate",
        "review_renderer",
        "dataset_freezer",
    }
    assert all("mini_agent" not in item["protocol"] for item in request.plugin_bindings)
