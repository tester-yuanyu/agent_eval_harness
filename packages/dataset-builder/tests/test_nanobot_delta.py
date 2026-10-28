import copy
import hashlib
import json
from pathlib import Path

import pytest


def _write(root, relative, value, *, lines=False):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        "".join(json.dumps(row) + "\n" for row in value) if lines else json.dumps(value)
    )
    path.write_text(text)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _previous(root):
    gaps = {
        "gaps": [
            {
                "fact_id": "tool.read_file",
                "capability_key": "tool.execution",
                "reason": "Execution unknown",
            }
        ]
    }
    payload = {
        "snapshot_id": "tool.read_file",
        "snapshot_type": "tool",
        "capabilities": [
            {"capability_key": "tool.execution", "support_status": "unknown"}
        ],
        "result_protocols": {"registry_return_type": "Any"},
    }
    files = {
        "bundle/tools/read_file.json": _write(
            root, "source_delivery/bundle/tools/read_file.json", payload
        ),
        "capability_contract_gaps.json": _write(
            root, "source_delivery/capability_contract_gaps.json", gaps
        ),
    }
    source_manifest = {
        "capability_bundle_sha256": "old-bundle",
        "bundle_path": "bundle",
        "files_sha256": files,
    }
    _write(root, "source_delivery/manifest.json", source_manifest)
    refs = [
        {
            "path": "capability_contract_gaps.json",
            "sha256": files["capability_contract_gaps.json"],
            "pointer": "/gaps/0",
        }
    ]
    blockers = [
        {
            "blocker_id": "gap-0",
            "code": "SOURCE_GAP_000",
            "target_id": "tool.read_file",
            "source_refs": refs,
            "reason": "Execution unknown",
            "required_action": "Supply execution evidence",
        }
    ]
    case = {
        "case_id": "stable-id",
        "target_id": "tool.read_file",
        "input": {"operation": "invoke_tool", "arguments": {"path": "a"}},
        "oracle": {"checks": [{"expected": "a"}]},
        "source_refs": refs,
    }
    dataset_path = "datasets/tools/read_file.jsonl"
    digest = _write(root, dataset_path, [case], lines=True)
    _write(root, "blockers.json", blockers)
    _write(
        root,
        "inventory.json",
        {
            "agent_id": "nanobot",
            "bundle_sha256": "old-bundle",
            "artifacts": {
                "tool.read_file": {
                    "path": "bundle/tools/read_file.json",
                    "payload": payload,
                }
            },
        },
    )
    _write(
        root,
        "manifest.json",
        {
            "agent_id": "nanobot",
            "bundle_sha256": "old-bundle",
            "case_count": 1,
            "datasets": [{"path": dataset_path, "sha256": digest, "case_count": 1}],
            "files_sha256": {
                p.relative_to(root).as_posix(): hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
                for p in root.rglob("*")
                if p.is_file()
            },
        },
    )
    return case, blockers


def _current(baseline):
    return {
        "agent_id": "nanobot",
        "bundle_sha256": "new-bundle",
        "files_sha256": baseline["source"]["files_sha256"],
        "artifacts": copy.deepcopy(baseline["artifacts"]),
        "gaps": [
            {"fact_id": "evidence.run_exception", "capability_key": "available"},
            {"fact_id": "tool.read_file", "capability_key": "tool.execution"},
        ],
    }


def test_baseline_preserves_full_candidates_and_identity_not_gap_position(tmp_path):
    from dataset_builder.nanobot_generation.delta import make_baseline

    case, blockers = _previous(tmp_path)
    baseline = make_baseline(tmp_path)
    assert baseline["cases"] == [case]
    assert baseline["blockers"][0]["payload"] == blockers[0]
    assert baseline["blockers"][0]["canonical_identity"] == [
        "source_gap",
        "tool.read_file",
        "tool.execution",
    ]
    assert baseline["source"]["bundle_sha256"] == "old-bundle"


def test_baseline_rejects_tampered_previous_dataset(tmp_path):
    from dataset_builder.nanobot_generation.delta import make_baseline

    _previous(tmp_path)
    (tmp_path / "datasets/tools/read_file.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="hash"):
        make_baseline(tmp_path)


def test_baseline_rejects_unbound_candidate_source_even_when_delivery_is_rehashed(
    tmp_path,
):
    from dataset_builder.nanobot_generation.delta import make_baseline

    case, _ = _previous(tmp_path)
    case["source_refs"][0]["sha256"] = "stale-source-hash"
    relative = "datasets/tools/read_file.jsonl"
    digest = _write(tmp_path, relative, [case], lines=True)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["datasets"][0]["sha256"] = digest
    manifest["files_sha256"][relative] = digest
    _write(tmp_path, "manifest.json", manifest)
    with pytest.raises(ValueError, match="source reference"):
        make_baseline(tmp_path)


def test_rebinding_is_separate_from_input_and_oracle_changes(tmp_path):
    from dataset_builder.nanobot_generation.delta import compare, make_baseline

    _previous(tmp_path)
    baseline = make_baseline(tmp_path)
    cases = copy.deepcopy(baseline["cases"])
    cases[0]["source_refs"][0]["sha256"] = "new-hash"
    blockers = copy.deepcopy([x["payload"] for x in baseline["blockers"]])
    blockers[0].update(blocker_id="new-gap", code="SOURCE_GAP_hashed")
    blockers[0]["source_refs"][0]["pointer"] = "/gaps/1"
    result = compare(baseline, _current(baseline), cases, blockers)
    changed = result["case_changes"]["updated"]
    assert len(changed) == 1
    assert changed[0]["source_rebound"] is True
    assert changed[0]["input_changed"] is False
    assert changed[0]["oracle_changed"] is False
    assert len(result["blocker_changes"]["retained"]) == 1
    assert result["blocker_changes"]["resolved"] == []
    cases[0]["input"]["arguments"]["path"] = "b"
    cases[0]["oracle"]["checks"][0]["expected"] = "b"
    changed = compare(baseline, _current(baseline), cases, blockers)["case_changes"][
        "updated"
    ][0]
    assert changed["input_changed"] is True
    assert changed["oracle_changed"] is True


def test_removed_unknown_blocker_is_not_claimed_resolved(tmp_path):
    from dataset_builder.nanobot_generation.delta import compare, make_baseline

    _previous(tmp_path)
    baseline = make_baseline(tmp_path)
    data = _current(baseline)
    result = compare(baseline, data, baseline["cases"], [])
    assert result["blocker_changes"]["resolved"] == []
    assert len(result["blocker_changes"]["unverified_removals"]) == 1
    data["artifacts"]["tool.read_file"]["payload"]["capabilities"][0][
        "support_status"
    ] = "supported"
    data["gaps"] = []
    result = compare(baseline, data, baseline["cases"], [])
    assert len(result["blocker_changes"]["resolved"]) == 1
    assert result["runtime_execution"] == "NOT_RUN"


def test_boundary_narrows_without_claiming_unreviewed_branches_superseded(tmp_path):
    from dataset_builder.nanobot_generation.delta import compare, make_baseline

    _previous(tmp_path)
    baseline = make_baseline(tmp_path)
    target = "chain.end_to_end"
    old_boundary = {
        "blocker_id": "old-boundary",
        "code": "CONVERSATION_BOUNDARY_IMPLEMENTATION_MISMATCH",
        "target_id": target,
        "source_refs": [],
        "reason": "Whole boundary conflicts",
    }
    old_branch = {
        "blocker_id": "old-error",
        "code": "UNRESOLVED_BRANCH_ERROR",
        "target_id": target,
        "source_refs": [],
        "reason": "No error contract",
    }
    for b in (old_boundary, old_branch):
        baseline["blockers"].append(
            {"payload": b, "canonical_identity": ["blocker", target, b["code"]]}
        )
    current_boundary = {
        **old_boundary,
        "blocker_id": "mcp-only",
        "code": "CONDITIONAL_MCP_BOUNDARY_UNRESOLVED",
        "reason": "MCP configuration remains unresolved",
    }
    data = _current(baseline)
    data["artifacts"][target] = {
        "payload": {
            "snapshot_type": "chain",
            "branches": [
                {"branch_type": "returned_error"},
                {"branch_type": "raised_exception"},
            ],
        }
    }
    current = [baseline["blockers"][0]["payload"], current_boundary]
    current[0] = copy.deepcopy(current[0])
    current[0]["source_refs"][0]["pointer"] = "/gaps/1"
    result = compare(baseline, data, baseline["cases"], current)
    assert len(result["blocker_changes"]["narrowed"]) == 1
    assert result["blocker_changes"]["superseded"] == []
    assert len(result["blocker_changes"]["unverified_removals"]) == 1
    assert result["blocker_changes"]["resolved"] == []


@pytest.mark.parametrize("branch", ["normal", "error", "early_stop"])
def test_unchanged_package_cannot_hide_deleted_legacy_branch_blocker(tmp_path, branch):
    from dataset_builder.nanobot_generation.delta import compare, make_baseline

    _previous(tmp_path)
    baseline = make_baseline(tmp_path)
    target = "chain.end_to_end"
    baseline["artifacts"][target] = {
        "payload": {
            "snapshot_type": "chain",
            "branches": [
                {"branch_type": "normal"},
                {"branch_type": "error"},
                {"branch_type": "early_stop"},
            ],
        }
    }
    blocker = {
        "blocker_id": "legacy-branch",
        "code": "UNRESOLVED_BRANCH_" + branch.upper(),
        "target_id": target,
        "source_refs": [],
        "reason": "Branch unresolved",
    }
    baseline["blockers"].append(
        {"payload": blocker, "canonical_identity": ["blocker", target, blocker["code"]]}
    )
    data = _current(baseline)
    data["bundle_sha256"] = baseline["source"]["bundle_sha256"]
    data["gaps"] = [{"fact_id": "tool.read_file", "capability_key": "tool.execution"}]
    remaining = [baseline["blockers"][0]["payload"]]
    result = compare(baseline, data, baseline["cases"], remaining)
    assert result["blocker_changes"]["superseded"] == []
    assert result["blocker_changes"]["resolved"] == []
    assert [
        row["previous_blocker_id"]
        for row in result["blocker_changes"]["unverified_removals"]
    ] == ["legacy-branch"]


@pytest.fixture(scope="module")
def reviewed_migration():
    from dataset_builder.nanobot_generation.cases import build_cases
    from dataset_builder.nanobot_generation.delta import make_baseline
    from dataset_builder.nanobot_generation.inputs import load_input

    previous = (
        Path(__file__).resolve().parents[1] / "workspaces/nanobot_full_eval_20261023"
    )
    source = Path("/Users/yuanyu/Desktop/nanobot/exports/nanobot_snapshot_v3")
    baseline = make_baseline(previous)
    data = load_input(
        source, "8462eaa3c43061cc6e9f5eefaee216f9fed12e2513d86b3f7efbd476e1d06adb"
    )
    cases, blockers = build_cases(data)
    return baseline, data, cases, blockers


@pytest.mark.parametrize(
    "mutation",
    ["none", "unreviewed_hash", "unchanged_branches", "missing_case", "altered_oracle"],
)
def test_supersession_requires_reviewed_changed_contract_and_complete_candidates(
    reviewed_migration, mutation
):
    from dataset_builder.nanobot_generation.delta import compare

    baseline, data, cases, blockers = copy.deepcopy(reviewed_migration)
    if mutation == "unreviewed_hash":
        data["files_sha256"]["execution_contract.json"] = "0" * 64
    elif mutation == "unchanged_branches":
        baseline["artifacts"]["chain.end_to_end"]["payload"]["branches"] = (
            copy.deepcopy(data["artifacts"]["chain.end_to_end"]["payload"]["branches"])
        )
    elif mutation in {"missing_case", "altered_oracle"}:
        normal = next(
            c
            for c in cases
            if c["source_basis"] == "execution_contract"
            and c["input"].get("arguments", {}).get("session_key") == "sdk:v3-normal"
        )
        if mutation == "missing_case":
            cases.remove(normal)
        else:
            normal["oracle"] = {"checks": []}
    result = compare(baseline, data, cases, blockers)
    if mutation == "none":
        assert len(result["blocker_changes"]["superseded"]) == 3
        assert result["blocker_changes"]["unverified_removals"] == []
    else:
        assert result["blocker_changes"]["superseded"] == []
        assert len(result["blocker_changes"]["unverified_removals"]) == 3
    assert result["blocker_changes"]["resolved"] == []
