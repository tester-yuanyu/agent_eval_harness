"""保存运行的严格成对比较；不执行 Agent，也不重新评分。"""

from capability_snapshot_kit.hashing import sha256_json as digest

from .summaries import summarize


def compare_runs(baseline: dict, candidate: dict) -> dict:
    for run in (baseline, candidate):
        count = run["trials_per_case"]
        cases = run["planned_case_ids"]
        if type(count) is not int or count < 1 or len(set(cases)) != len(cases):
            raise ValueError("comparison requires valid planned cases and trials")
        seen = set()
        for row in run["trials"]:
            key = (row["case_id"], row["trial"])
            if (
                type(row["trial"]) is not int
                or not 1 <= row["trial"] <= count
                or row["case_id"] not in cases
            ):
                raise ValueError("comparison contains invalid trial identifiers")
            if key in seen:
                raise ValueError("comparison contains duplicate case/trial rows")
            seen.add(key)
            if row.get("identity_hash") != run.get("identity_hash"):
                raise ValueError("trial identity_hash differs from its run")
        if "identity_hash" in run and run["identity_hash"] != digest(run["identity"]):
            raise ValueError("run identity_hash does not match identity")
    for field in ("dataset", "scoring_version"):
        if baseline["identity"][field] != candidate["identity"][field]:
            raise ValueError(f"comparison requires identical {field}")
    for field in (
        "harness_version",
        "harness_source",
        "scoring_identity",
        "offline",
        "inspect_ai",
    ):
        if baseline["identity"].get(field) != candidate["identity"].get(field):
            raise ValueError(f"comparison requires identical {field}")
    for field in ("execution_backend", "scoring_backend"):
        if baseline.get(field) != candidate.get(field):
            raise ValueError(f"comparison requires identical {field}")
    if baseline.get("mode") != candidate.get("mode"):
        raise ValueError("cannot compare offline reference with real Agent results")
    if (
        baseline["planned_case_ids"] != candidate["planned_case_ids"]
        or baseline["trials_per_case"] != candidate["trials_per_case"]
    ):
        raise ValueError(
            "comparison requires identical task selection and repeat count"
        )
    expected = {
        (case, t)
        for case in baseline["planned_case_ids"]
        for t in range(1, baseline["trials_per_case"] + 1)
    }
    rows = []
    indices = [
        {(r["case_id"], r["trial"]): r for r in run["trials"]}
        for run in (baseline, candidate)
    ]
    if any(set(index) != expected for index in indices):
        raise ValueError("cannot formally compare incomplete runs")
    for key in sorted(expected):
        left, right = (index[key]["assessment"]["verdict"] for index in indices)
        if left != right:
            rows.append(
                {
                    "case_id": key[0],
                    "trial": key[1],
                    "baseline": left,
                    "candidate": right,
                }
            )
    summaries = [
        summarize(run["trials"], run["planned_case_ids"], run["trials_per_case"])
        for run in (baseline, candidate)
    ]
    return {
        "baseline_run_id": baseline.get("run_id"),
        "candidate_run_id": candidate.get("run_id"),
        "dataset": baseline["identity"]["dataset"],
        "changed_trials": rows,
        "baseline": summaries[0],
        "candidate": summaries[1],
        "pass_rate_delta": summaries[1]["pass_rate_planned"]
        - summaries[0]["pass_rate_planned"],
        "interpretation": (
            "Descriptive paired comparison; no statistical significance claim."
        ),
        "configuration_changes": {
            k: [baseline.get("config", {}).get(k), candidate.get("config", {}).get(k)]
            for k in set(baseline.get("config", {})) | set(candidate.get("config", {}))
            if baseline.get("config", {}).get(k) != candidate.get("config", {}).get(k)
        },
    }
