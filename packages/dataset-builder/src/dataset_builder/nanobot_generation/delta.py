"Compare immutable deliveries without treating removed blockers as passed tests."

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from ..full_generation.inventory import pointer_value
from .inputs import safe_path, sha256


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def _unique(rows, key):
    indexed = {}
    for row in rows:
        ident = row[key]
        if ident in indexed:
            raise ValueError(f"duplicate {key}: {ident}")
        indexed[ident] = row
    return indexed


def _identity(blocker, gaps):
    if blocker["code"].startswith("SOURCE_GAP_"):
        refs = [
            ref
            for ref in blocker["source_refs"]
            if ref.get("path") == "capability_contract_gaps.json"
            and ref.get("pointer", "").startswith("/gaps/")
        ]
        if len(refs) != 1:
            raise ValueError("source gap requires exactly one bound gap reference")
        gap = pointer_value({"gaps": gaps}, refs[0]["pointer"])
        if gap["fact_id"] != blocker["target_id"]:
            raise ValueError("source gap target mismatch")
        return ["source_gap", gap["fact_id"], gap["capability_key"]]
    return ["blocker", blocker["target_id"], blocker["code"]]


def make_baseline(previous: Path) -> dict:
    """Read and hash-check a previous delivery into a portable comparison input."""
    previous = Path(previous).resolve()
    manifest = json.loads((previous / "manifest.json").read_text())
    if manifest["agent_id"] != "nanobot":
        raise ValueError("comparison baseline must be a nanobot delivery")
    files = manifest["files_sha256"]
    for relative, expected in files.items():
        path = safe_path(previous, relative)
        if not path.is_file() or sha256(path) != expected:
            raise ValueError("previous delivery hash mismatch: " + relative)

    def bound(relative):
        if relative not in files:
            raise ValueError("unbound previous artifact: " + relative)
        return json.loads(safe_path(previous, relative).read_text())

    inventory = bound("inventory.json")
    blockers = bound("blockers.json")
    source_manifest = bound("source_delivery/manifest.json")
    bundle_hash = manifest["bundle_sha256"]
    if (
        source_manifest["capability_bundle_sha256"] != bundle_hash
        or inventory["bundle_sha256"] != bundle_hash
        or inventory["agent_id"] != "nanobot"
    ):
        raise ValueError("previous source bundle identity mismatch")
    source_files = source_manifest["files_sha256"]
    for relative, expected in source_files.items():
        path = safe_path(previous / "source_delivery", relative)
        output_relative = path.relative_to(previous).as_posix()
        if files.get(output_relative) != expected or sha256(path) != expected:
            raise ValueError("previous source hash mismatch: " + relative)
    gaps = bound("source_delivery/capability_contract_gaps.json")["gaps"]
    if "capability_contract_gaps.json" not in source_files:
        raise ValueError("previous source gaps are unbound")
    for ident, artifact in inventory["artifacts"].items():
        relative = artifact["path"]
        if relative not in source_files:
            raise ValueError("previous snapshot is unbound: " + ident)
        if bound("source_delivery/" + relative) != artifact["payload"]:
            raise ValueError("previous inventory snapshot mismatch: " + ident)
    cases, dataset_paths = [], set()
    for dataset in manifest["datasets"]:
        relative = dataset["path"]
        if relative in dataset_paths:
            raise ValueError("duplicate previous dataset: " + relative)
        dataset_paths.add(relative)
        if files.get(relative) != dataset["sha256"]:
            raise ValueError("previous dataset hash binding mismatch: " + relative)
        rows = [
            json.loads(line)
            for line in safe_path(previous, relative).read_text().splitlines()
            if line.strip()
        ]
        if len(rows) != dataset["case_count"]:
            raise ValueError("previous dataset count mismatch: " + relative)
        cases.extend(rows)
    _unique(cases, "case_id")
    _unique(blockers, "blocker_id")
    if len(cases) != manifest["case_count"]:
        raise ValueError("previous candidate count mismatch")
    reference_hashes = {
        **source_files,
        "manifest.json": files["source_delivery/manifest.json"],
    }
    texts = {}

    def verify_references(value):
        if isinstance(value, list):
            for item in value:
                verify_references(item)
        elif isinstance(value, dict):
            if "path" in value and "sha256" in value:
                name = value["path"]
                if reference_hashes.get(name) != value["sha256"]:
                    raise ValueError("previous source reference hash mismatch: " + name)
                if name not in texts:
                    texts[name] = safe_path(
                        previous / "source_delivery", name
                    ).read_text()
                if "pointer" in value:
                    pointer_value(json.loads(texts[name]), value["pointer"])
                if "anchor" in value and (
                    not value["anchor"] or value["anchor"] not in texts[name]
                ):
                    raise ValueError(
                        "previous source reference anchor missing: " + name
                    )
            for item in value.values():
                verify_references(item)

    verify_references(cases)
    verify_references(blockers)
    return {
        "schema_version": "1.0",
        "agent_id": "nanobot",
        "previous_delivery": str(previous),
        "previous_manifest_sha256": sha256(previous / "manifest.json"),
        "source": {
            "bundle_sha256": bundle_hash,
            "bundle_path": source_manifest["bundle_path"],
            "manifest_sha256": files["source_delivery/manifest.json"],
            "files_sha256": reference_hashes,
        },
        "artifacts": inventory["artifacts"],
        "cases": cases,
        "blockers": [
            {"canonical_identity": _identity(b, gaps), "payload": b} for b in blockers
        ],
    }


def _semantic(value):
    """A relocated, rebound source reference does not change stimulus semantics."""
    if isinstance(value, list):
        return [_semantic(item) for item in value]
    if not isinstance(value, dict):
        return value
    value = dict(value)
    if "path" in value and "sha256" in value:
        value.pop("sha256")
        if value["path"].startswith("delivery/bundle/"):
            value["path"] = value["path"].removeprefix("delivery/")
    return {key: _semantic(item) for key, item in value.items()}


def _case_changes(old_cases, new_cases):
    old, new = _unique(old_cases, "case_id"), _unique(new_cases, "case_id")
    result = {key: [] for key in ("added", "removed", "updated", "unchanged")}
    for cid in sorted(old.keys() | new.keys()):
        before, after = old.get(cid), new.get(cid)
        row = {
            "case_id": cid,
            "target_id": (after or before)["target_id"],
            "previous_sha256": _digest(before) if before is not None else None,
            "current_sha256": _digest(after) if after is not None else None,
        }
        if before is None or after is None:
            result["added" if before is None else "removed"].append(row)
        elif before == after:
            result["unchanged"].append(row)
        else:
            row.update(
                input_changed=_semantic(before.get("input"))
                != _semantic(after.get("input")),
                oracle_changed=_semantic(before.get("oracle"))
                != _semantic(after.get("oracle")),
                source_rebound=before.get("source_refs") != after.get("source_refs"),
                changed_fields=sorted(
                    key
                    for key in before.keys() | after.keys()
                    if before.get(key) != after.get(key)
                ),
            )
            result["updated"].append(row)
    return result


def _resolved_claim(identity, data):
    if identity[0] != "source_gap":
        return False
    _, target, key = identity
    if any(
        gap["fact_id"] == target and gap["capability_key"] == key
        for gap in data["gaps"]
    ):
        return False
    payload = data["artifacts"].get(target, {}).get("payload", {})
    claims = payload.get("capabilities", []) + [payload.get("availability", {})]
    return any(
        claim.get("capability_key") == key
        and claim.get("support_status") == "supported"
        for claim in claims
    )


def _reviewed_replacements(data, cases, blockers):
    """Require the reviewed contract and its complete, unchanged candidate mapping."""
    from .v3_contract import case_id, catalog, validate_completeness

    if not data.get("execution_contract"):
        return False
    try:
        validate_completeness(data, cases, blockers)
        actual = _unique(cases, "case_id")
        for row in catalog(data):
            case = actual[case_id(row)]
            if (
                case.get("target_id") != row["target_id"]
                or case.get("source_basis") != "execution_contract"
                or case.get("kind") != "behavior_candidate"
                or case.get("input") != row["input"]
                or case.get("oracle") != {"checks": row["checks"]}
                or case.get("preconditions") != row["preconditions"]
                or case.get("runner_requirements") != row["requirements"]
            ):
                return False
            refs = row["sources"] + [
                {"path": "execution_contract.json", "pointer": pointer}
                for pointer in row["contract_keys"]
            ]
            for ref in refs:
                expected = {**ref, "sha256": data["files_sha256"][ref["path"]]}
                if expected not in case.get("source_refs", []):
                    return False
    except (ValueError, KeyError):
        return False
    return True


def _blocker_changes(baseline, data, cases, blockers):
    current = {}
    for blocker in blockers:
        identity = tuple(_identity(blocker, data["gaps"]))
        if identity in current:
            raise ValueError("duplicate canonical blocker identity")
        current[identity] = blocker
    result = {
        key: []
        for key in (
            "retained",
            "narrowed",
            "resolved",
            "added",
            "superseded",
            "unverified_removals",
        )
    }
    reviewed_replacements = _reviewed_replacements(data, cases, blockers)
    consumed = set()
    for entry in baseline["blockers"]:
        identity, before = entry["canonical_identity"], entry["payload"]
        target, code = before["target_id"], before["code"]
        match = tuple(identity)
        narrowed_boundary = code == "CONVERSATION_BOUNDARY_IMPLEMENTATION_MISMATCH"
        if narrowed_boundary:
            candidate = ("blocker", target, "CONDITIONAL_MCP_BOUNDARY_UNRESOLVED")
            if candidate in current:
                match = candidate
        after = current.get(match)
        row = {
            "canonical_identity": identity,
            "target_id": target,
            "previous_blocker_id": before["blocker_id"],
            "current_blocker_id": after["blocker_id"] if after else None,
            "previous": before,
            "current": after,
        }
        if after is not None:
            consumed.add(match)
            narrowed_semantics = code in {
                "INCOMPLETE_RESULT_PROTOCOLS",
                "INCOMPLETE_RETRY_POLICY",
            } and before.get("reason") != after.get("reason")
            category = (
                "narrowed"
                if match != tuple(identity) or narrowed_semantics
                else "retained"
            )
            row["reason"] = (
                "Contract supplies partial semantics; listed remainder persists."
                if category == "narrowed"
                else "Same unresolved obligation, including any source rebinding."
            )
            result[category].append(row)
            continue
        replacements = {
            "UNRESOLVED_BRANCH_NORMAL": {"normal"},
            "UNRESOLVED_BRANCH_ERROR": {
                "returned_error",
                "tool_error",
                "raised_exception",
                "cancelled",
                "iteration_limit",
                "empty_response",
            },
            "UNRESOLVED_BRANCH_EARLY_STOP": {
                "command_return",
                "suppressed_response",
                "iteration_limit",
            },
        }.get(code, set())
        current_branches = (
            data["artifacts"].get(target, {}).get("payload", {}).get("branches", [])
        )
        previous_branches = (
            baseline["artifacts"].get(target, {}).get("payload", {}).get("branches", [])
        )
        branches = {branch["branch_type"] for branch in current_branches}
        if (
            reviewed_replacements
            and previous_branches
            and previous_branches != current_branches
            and replacements
            and replacements <= branches
        ):
            row.update(
                replacement_branches=sorted(replacements & branches),
                reason="Replaced by specific branches; no execution pass implied.",
            )
            result["superseded"].append(row)
        elif _resolved_claim(identity, data):
            row["reason"] = (
                "Source explicitly declares support; runtime remains NOT_RUN."
            )
            result["resolved"].append(row)
        else:
            row["reason"] = "Absent without an explicit resolution; requires review."
            result["unverified_removals"].append(row)
    for identity, blocker in sorted(current.items()):
        if identity not in consumed:
            result["added"].append(
                {"canonical_identity": list(identity), "current": blocker}
            )
    return result


def _mapping_changes(old, new):
    return {
        "added": sorted(new.keys() - old.keys()),
        "removed": sorted(old.keys() - new.keys()),
        "updated": sorted(
            key for key in old.keys() & new.keys() if old[key] != new[key]
        ),
        "unchanged": sorted(
            key for key in old.keys() & new.keys() if old[key] == new[key]
        ),
    }


def compare(baseline: dict, data: dict, cases: list, blockers: list) -> dict:
    """Produce a deterministic semantic delta; neither loads nor executes an Agent."""
    if baseline["agent_id"] != "nanobot" or data["agent_id"] != "nanobot":
        raise ValueError("delta only compares nanobot deliveries")
    case_changes = _case_changes(baseline["cases"], cases)
    blocker_changes = _blocker_changes(baseline, data, cases, blockers)
    old_targets = {k: v["payload"] for k, v in baseline["artifacts"].items()}
    new_targets = {k: v["payload"] for k, v in data["artifacts"].items()}
    return deepcopy(
        {
            "schema_version": "1.0",
            "agent_id": "nanobot",
            "runtime_execution": "NOT_RUN",
            "previous": {
                "bundle_sha256": baseline["source"]["bundle_sha256"],
                "manifest_sha256": baseline["previous_manifest_sha256"],
                "source_manifest_sha256": baseline["source"]["manifest_sha256"],
            },
            "current": {
                "bundle_sha256": data["bundle_sha256"],
                "source_manifest_sha256": data["files_sha256"].get("manifest.json"),
            },
            "case_changes": case_changes,
            "blocker_changes": blocker_changes,
            "source_changes": _mapping_changes(
                baseline["source"]["files_sha256"], data["files_sha256"]
            ),
            "target_changes": _mapping_changes(old_targets, new_targets),
            "summary": {
                "cases": {key: len(rows) for key, rows in case_changes.items()},
                "blockers": {key: len(rows) for key, rows in blocker_changes.items()},
            },
            "interpretation": (
                "Resolved means an explicit source declaration closes that obligation. "
                "Narrowed and superseded retain their stated limitations. "
                "No category certifies Agent execution or business success."
            ),
        }
    )
