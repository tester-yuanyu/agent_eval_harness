import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dataset_builder.nanobot_generation.inputs import load_input

SOURCE = Path("/Users/yuanyu/Desktop/nanobot/exports/nanobot_snapshot_v3")
HASH = "8462eaa3c43061cc6e9f5eefaee216f9fed12e2513d86b3f7efbd476e1d06adb"
PREVIOUS = Path("workspaces/nanobot_full_eval_20261023")


def load():
    return load_input(SOURCE, HASH)


def test_v3_contract_is_hash_bound_and_matches_snapshots():
    data = load()
    assert len(data["artifacts"]) == 37
    assert data["execution_contract"]["contract_version"] == "nanobot-collector-v2"
    assert data["artifacts"]["agent.nanobot"]["path"] == "delivery/bundle/agent.json"
    assert len(data["files_sha256"]) == 128
    assert (
        data["artifacts"]["evidence.run_exception"]["payload"]["availability"][
            "support_status"
        ]
        == "unknown"
    )


def test_v3_schema_not_python_hooks_and_missing_property_definitions():
    from dataset_builder.nanobot_generation.schema_cases import schema_examples

    data = load()
    schema = data["artifacts"]["module.dialogue"]["payload"]["input_schema"]
    examples = schema_examples(schema)
    assert examples
    assert any(
        isinstance(x["instance"], dict)
        and x["instance"].get("channel") == "system"
        and not x["expected_valid"]
        for x in examples
    )
    assert any(
        isinstance(x["instance"], dict)
        and isinstance(x["instance"].get("model"), str)
        and isinstance(x["instance"].get("model_preset"), str)
        and not x["expected_valid"]
        for x in examples
    )
    assert any(
        isinstance(x["instance"], dict)
        and x["instance"].get("hooks") is None
        and x["expected_valid"]
        for x in examples
    )
    for example in examples:
        assert (
            Draft202012Validator(schema).is_valid(example["instance"])
            == example["expected_valid"]
        )
    evidence_schema = data["artifacts"]["evidence.execution_contract"]["payload"][
        "payload_schema"
    ]
    ev = schema_examples(evidence_schema)
    assert any(e["expected_valid"] for e in ev)
    assert any(
        isinstance(e["instance"], dict)
        and "boundary" not in e["instance"]
        and not e["expected_valid"]
        for e in ev
    )
    assert any(
        isinstance(e["instance"], dict)
        and e["instance"].get("contract_version") == "nanobot-collector-v2"
        and e["expected_valid"]
        for e in ev
    )


def test_v3_old_expectations_not_guessed_and_old_gaps_narrowed():
    from dataset_builder.nanobot_generation.cases import build_cases

    data = load()
    cases, blockers = build_cases(data)
    assert {c["target_id"] for c in cases} == set(data["artifacts"])
    codes = {b["code"] for b in blockers}
    assert "UNRESOLVED_BRANCH_EARLY_STOP" not in codes
    assert "CRITICAL_CHAIN_NOT_DECLARED" in codes
    assert "EXCEPTION_OBSERVER_NOT_IMPLEMENTED" in codes
    result_gap = next(b for b in blockers if b["code"] == "INCOMPLETE_RESULT_PROTOCOLS")
    assert "per-tool" in result_gap["reason"]
    assert any(
        r["path"] == "execution_contract.json" for r in result_gap["source_refs"]
    )
    new = [c for c in cases if c["source_basis"] == "execution_contract"]
    assert len(new) == 31
    assert all(
        any(
            r["path"] == "execution_contract.json" and r.get("pointer")
            for r in c["source_refs"]
        )
        for c in new
    )
    assert all(c["runtime_execution"] == "NOT_RUN" for c in cases)


def test_v3_contract_oracle_mutation_is_rejected():
    from dataset_builder.nanobot_generation.cases import build_cases
    from dataset_builder.nanobot_generation.validation import validate_cases

    data = load()
    cases, blockers = build_cases(data)
    assert validate_cases(data, cases, blockers)["valid"]
    tampered = copy.deepcopy(cases)
    candidate = next(c for c in tampered if c["source_basis"] == "execution_contract")
    candidate["oracle"]["checks"][0]["expected"] = "GUESSED_SUCCESS"
    assert not validate_cases(data, tampered, blockers)["valid"]


@pytest.mark.parametrize(
    "mutation",
    ["downgrade_basis", "drop_links", "drop_case", "drop_all", "drop_mcp_gap"],
)
def test_v3_reviewed_contract_mapping_cannot_be_bypassed(mutation):
    from dataset_builder.nanobot_generation.cases import build_cases
    from dataset_builder.nanobot_generation.validation import validate_cases

    data = load()
    cases, blockers = build_cases(data)
    candidate = next(c for c in cases if c["source_basis"] == "execution_contract")
    if mutation == "downgrade_basis":
        candidate["source_basis"] = "implementation_derived"
        candidate["oracle"]["checks"][0]["expected"] = "GUESSED"
    elif mutation == "drop_links":
        candidate["blocker_ids"] = []
    elif mutation == "drop_case":
        cases.remove(candidate)
    elif mutation == "drop_all":
        cases = [c for c in cases if c["source_basis"] != "execution_contract"]
    else:
        blockers = [
            b for b in blockers if b["code"] != "CONDITIONAL_MCP_BOUNDARY_UNRESOLVED"
        ]
    assert not validate_cases(data, cases, blockers)["valid"]


def test_v3_does_not_silently_release_tool_execution():
    from dataset_builder.nanobot_generation.cases import build_cases

    data = load()
    cases, _ = build_cases(data)
    tools = [
        c
        for c in cases
        if c["target_id"].startswith("tool.") and c["kind"] == "behavior_candidate"
    ]
    assert len(tools) == 70
    assert all(
        c["support_status"] == "unknown" and c["execution_readiness"] == "blocked"
        for c in tools
    )


def test_old_delivery_still_verifies_after_upgrade():
    from dataset_builder.nanobot_generation.delivery import verify

    assert verify(PREVIOUS)["valid"]


def test_v3_delivery_delta_is_portable_and_recomputed(tmp_path):
    from dataset_builder.nanobot_generation.delivery import generate, verify
    from dataset_builder.nanobot_generation.inputs import sha256

    output = tmp_path / "v3"
    result = generate(SOURCE, output, HASH, previous=PREVIOUS)
    assert result["valid"]
    delta = json.loads((output / "reports/contract_delta.json").read_text())
    assert delta["summary"]["cases"]["added"] > 0
    assert delta["summary"]["blockers"]["narrowed"] > 0
    assert not delta["blocker_changes"]["unverified_removals"]
    assert (output / "CHANGELOG.md").is_file()
    moved = tmp_path / "moved"
    output.rename(moved)
    assert verify(moved)["valid"]
    # Rehashing a fabricated delta must not make it pass semantic verification.
    delta["summary"]["blockers"]["resolved"] = 999
    path = moved / "reports/contract_delta.json"
    path.write_text(json.dumps(delta))
    manifest_path = moved / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files_sha256"]["reports/contract_delta.json"] = sha256(path)
    manifest_path.write_text(json.dumps(manifest))
    checked = verify(moved)
    assert not checked["valid"]
    assert any("delta" in issue for issue in checked["issues"])
