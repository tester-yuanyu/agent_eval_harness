"""只读验证显式提供的执行/复评来源链，不跟随记录中的路径。"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from capability_snapshot_kit.hashing import sha256_json


def read_json(path: Path) -> tuple[dict, str]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError(f"non-finite JSON number: {value}")

    raw = Path(path).read_bytes()
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value, hashlib.sha256(raw).hexdigest()


def _result_path(path: Path) -> Path:
    path = Path(path)
    return path / "results.json" if path.is_dir() else path


def _rows(result: dict) -> dict[tuple[str, int], dict]:
    identity = result.get("identity")
    if not isinstance(identity, dict) or sha256_json(identity) != result.get(
        "identity_hash"
    ):
        raise ValueError("source identity hash mismatch")
    cases, repeats = result.get("planned_case_ids"), result.get("trials_per_case")
    if (
        not isinstance(cases, list)
        or any(not isinstance(c, str) or not c for c in cases)
        or len(cases) != len(set(cases))
        or type(repeats) is not int
        or repeats < 1
    ):
        raise ValueError("invalid source planned population")
    if (
        identity.get("case_ids", cases) != cases
        or identity.get("repeats", repeats) != repeats
    ):
        raise ValueError("source plan differs from identity")
    if not isinstance(result.get("run_id"), str) or not result["run_id"]:
        raise ValueError("missing source run id")
    if not isinstance(result.get("trials"), list):
        raise ValueError("missing source trials")
    rows = {}
    for row in result["trials"]:
        if not isinstance(row, dict):
            raise ValueError("source trial must be an object")
        case, trial = row.get("case_id"), row.get("trial")
        if (
            case not in cases
            or type(trial) is not int
            or not 1 <= trial <= repeats
            or (case, trial) in rows
        ):
            raise ValueError("duplicate or unexpected source trial")
        if row.get("identity_hash") != result["identity_hash"]:
            raise ValueError("source trial identity mismatch")
        if not isinstance(row.get("observation"), dict) or not isinstance(
            row.get("assessment"), dict
        ):
            raise ValueError("source trial requires observation and assessment")
        assessment = row["assessment"]
        if (
            assessment.get("verdict") not in {"PASS", "FAIL", "INVALID", "INCONCLUSIVE"}
            or assessment.get("validity") not in {"VALID", "INVALID"}
            or (assessment["verdict"] == "INVALID")
            != (assessment["validity"] == "INVALID")
        ):
            raise ValueError("inconsistent formal verdict/validity")
        rows[case, trial] = row
    return rows


def _operation(result: dict) -> tuple[str, dict]:
    provenance = result.get("provenance", {})
    regrade = result.get("regrade", {})
    if not isinstance(provenance, dict) or not isinstance(regrade, dict):
        raise ValueError("source provenance must be an object")
    if provenance.get("operation") == "judge_saved_evidence":
        return "judge", provenance
    if regrade.get("operation") == "regrade_saved_evidence":
        return "regrade", regrade
    if regrade or provenance.get("operation"):
        raise ValueError("unsupported source operation")
    return "execution", {}


def _verify_edge(child: dict, parent: dict, kind: str, provenance: dict) -> None:
    if (
        provenance.get("source_identity_hash") != parent["identity_hash"]
        or provenance.get("source_run_id") != parent["run_id"]
        or child["identity"].get("source_results_sha256")
        != provenance["source_results_sha256"]
    ):
        raise ValueError("source provenance identity mismatch")
    permitted = {"source_results_sha256"}
    permitted.update(
        {"scoring_version", "scoring_identity"}
        if kind == "regrade"
        else {"case_ids", "judge_config", "judge_repeats", "judge_source"}
    )
    if {k: v for k, v in child["identity"].items() if k not in permitted} != {
        k: v for k, v in parent["identity"].items() if k not in permitted
    }:
        raise ValueError("source execution identity changed")
    before, after = _rows(parent), _rows(child)
    if child["trials_per_case"] != parent["trials_per_case"]:
        raise ValueError("source repeat plan changed")
    if kind == "regrade":
        if (
            child["planned_case_ids"] != parent["planned_case_ids"]
            or before.keys() != after.keys()
        ):
            raise ValueError("regrade changed source population")
    elif not set(child["planned_case_ids"]) <= set(parent["planned_case_ids"]):
        raise ValueError("judge added source cases")
    if child["identity"].get("dataset") != parent["identity"].get("dataset"):
        raise ValueError("source dataset changed")
    for key, row in after.items():
        original = before.get(key)
        if original is None or row.get("source_trial_sha256") != sha256_json(original):
            raise ValueError("source trial hash mismatch")
        if row.get("source_assessment") != original["assessment"]:
            raise ValueError("source assessment mismatch")
        observed = deepcopy(row["observation"])
        if kind == "judge":
            events = observed.get("events", [])
            old_events = original["observation"].get("events", [])
            if events[: len(old_events)] != old_events or any(
                e.get("is_judge") is not True for e in events[len(old_events) :]
            ):
                raise ValueError("judge altered source events")
            observed["events"] = old_events
            old_assessment = original["assessment"]
            old_metrics = old_assessment.get("metrics", [])
            new_metrics = row["assessment"].get("metrics", [])
            if (
                new_metrics[: len(old_metrics)] != old_metrics
                or any(
                    m.get("formal") is not False
                    for m in new_metrics[len(old_metrics) :]
                )
                or {k: v for k, v in row["assessment"].items() if k != "metrics"}
                != {k: v for k, v in old_assessment.items() if k != "metrics"}
            ):
                raise ValueError("judge altered formal source assessment")
        if observed != original["observation"]:
            raise ValueError("source observation changed")
        for field in (
            "family",
            "category",
            "split",
            "evaluation_level",
            "execution_mode",
            "latency_seconds",
            "cleanup_status",
        ):
            if row.get(field) != original.get(field):
                raise ValueError(f"source trial metadata changed: {field}")


def load_analysis_source(
    run_dir: Path,
    *,
    source_artifacts: tuple[Path, ...] = (),
    judge_dir: Path | None = None,
) -> dict:
    selected, selected_hash = read_json(_result_path(run_dir))
    pool = {selected_hash: selected}
    for path in source_artifacts:
        value, digest = read_json(_result_path(path))
        pool[digest] = value
    judge_hash = None
    if judge_dir is not None:
        judge, judge_hash = read_json(_result_path(judge_dir))
        pool[judge_hash] = judge
    verified = set()

    def resolve(digest, visiting=()):
        if digest in visiting or len(visiting) >= 64:
            raise ValueError("source lineage cycle or excessive depth")
        if digest not in pool:
            raise ValueError(f"missing explicit source artifact: {digest}")
        value = pool[digest]
        _rows(value)
        kind, provenance = _operation(value)
        verified.add(digest)
        if kind == "execution":
            if value.get("execution_identity") or value.get("execution_run_id"):
                raise ValueError("derived source is missing provenance")
            return value
        parent_hash = provenance.get("source_results_sha256")
        root = resolve(parent_hash, (*visiting, digest))
        parent = pool[parent_hash]
        if _operation(parent)[0] == "judge":
            raise ValueError("judge evidence cannot parent a formal analysis")
        _verify_edge(value, parent, kind, provenance)
        if value.get("execution_identity", root["identity"]) != root["identity"]:
            raise ValueError("source execution identity mismatch")
        if value.get("execution_run_id", root["run_id"]) != root["run_id"]:
            raise ValueError("source execution run mismatch")
        for row in value["trials"]:
            if (
                row.get("execution_identity_hash", root["identity_hash"])
                != root["identity_hash"]
            ):
                raise ValueError("source execution trial identity mismatch")
        return root

    if _operation(selected)[0] == "judge":
        raise ValueError(
            "judge source is diagnostic; select an execution or regrade --run"
        )
    execution = resolve(selected_hash)
    judge_trials = []
    judge_plan = []
    if judge_hash:
        if (
            _operation(pool[judge_hash])[0] != "judge"
            or resolve(judge_hash) != execution
        ):
            raise ValueError("judge source belongs to another execution")
        judge_trials = pool[judge_hash]["trials"]
        judge_plan = [
            [case, trial]
            for case in pool[judge_hash]["planned_case_ids"]
            for trial in range(1, pool[judge_hash]["trials_per_case"] + 1)
        ]
    keys = [
        [execution["run_id"], execution["identity_hash"], *key]
        for key in _rows(execution)
    ]
    return {
        "selected_result": selected,
        "execution_result": execution,
        "canonical_keys": keys,
        "verified_source_hashes": sorted(verified),
        "selected_sha256": selected_hash,
        "judge_trials": judge_trials,
        "judge_plan": judge_plan,
    }
