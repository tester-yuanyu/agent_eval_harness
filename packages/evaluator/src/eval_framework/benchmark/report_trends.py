"""保存结果的同口径趋势；无网络、无 Agent、无重新评分。"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from ..aggregator.comparison import compare_runs
from .report_diagnostics import build_diagnostics, canonical

VERSION = "report-trends-v1"
VARIABLE_CONFIG = {"model", "model_name", "inspect_model", "base_url", "api_key_env"}
LOCAL_PATH_CONFIG = {"repository_root", "capability_bundle", "python", "nanobot_root"}


def _controls(run):
    identity = run["identity"]
    required = (
        "dataset",
        "scoring_identity",
        "harness_source",
        "inspect_ai",
        "config",
        "runtime",
    )
    if any(identity.get(key) is None for key in required):
        raise ValueError("trend requires complete saved controls")

    def runtime(value):
        return {k: v for k, v in value.items() if k not in {"source_sha256", "model"}}

    return {
        **{k: identity[k] for k in required if k not in {"config", "runtime"}},
        "config": {
            k: v
            for k, v in identity["config"].items()
            if k not in VARIABLE_CONFIG | LOCAL_PATH_CONFIG
        },
        "runtime_controls": runtime(identity["runtime"]),
        "runtime_modes": {
            k: runtime(v) for k, v in identity.get("runtime_modes", {}).items()
        },
        "selection": run["planned_case_ids"],
        "repeats": run["trials_per_case"],
        "execution_backend": run.get("execution_backend"),
        "scoring_backend": run.get("scoring_backend"),
        "mode": run.get("mode"),
    }


def build_trend(sources):
    if not sources:
        raise ValueError("trend needs at least one saved run")
    baseline = sources[0]["run"]
    controls = _controls(baseline)
    seen = set()
    rows = []
    grouping = None
    for source in sources:
        run, analysis = source["run"], source["analysis"]
        if run["run_id"] in seen:
            raise ValueError("duplicate run in trend")
        seen.add(run["run_id"])
        compare_runs(baseline, run)
        if _controls(run) != controls:
            raise ValueError(
                "trend requires identical controls; model/runtime source may vary"
            )
        trial_map = {(r["case_id"], r["trial"]): r for r in run["trials"]}
        groups = {}
        mapping = {}
        for row in analysis["trials"]:
            key = (row["case_id"], row["trial"])
            if key in mapping or not row.get("goal_bound"):
                raise ValueError(
                    "trend grouping needs unique, frozen-task-bound trials"
                )
            if (
                key not in trial_map
                or row["verdict"] != trial_map[key]["assessment"]["verdict"]
            ):
                raise ValueError("diagnostic verdict differs from saved result")
            if row["verdict"] not in {"PASS", "FAIL", "INVALID"}:
                raise ValueError("unknown verdict")
            mapping[key] = row["operation"]
            groups.setdefault(row["operation"], Counter())[row["verdict"]] += 1
        if set(mapping) != set(trial_map) or (
            grouping is not None and mapping != grouping
        ):
            raise ValueError("trend trial grouping changed")
        grouping = mapping
        experiments = sorted({t["experiment_id"] for t in source["receipt"]["traces"]})
        if len(experiments) != 1:
            raise ValueError(
                "run trend currently requires one Langfuse experiment per run"
            )
        rows.append(
            {
                "run_id": run["run_id"],
                "source_hash": analysis["source_hash"],
                "finished_at": run["finished_at"],
                "experiment_id": experiments[0],
                "model": {
                    k: v
                    for k, v in run["identity"]["config"].items()
                    if k in VARIABLE_CONFIG
                },
                "runtime": run["identity"]["runtime"],
                "groups": {
                    mode: {
                        "passed": c["PASS"],
                        "total": sum(c.values()),
                        "invalid": c["INVALID"],
                        "pass_rate_percent": 100 * c["PASS"] / sum(c.values()),
                    }
                    for mode, c in sorted(groups.items())
                },
            }
        )
    grouping_rows = [
        {"case_id": k[0], "trial": k[1], "operation": v}
        for k, v in sorted(grouping.items())
    ]
    cohort = hashlib.sha256(
        canonical({"version": VERSION, "controls": controls, "grouping": grouping_rows})
    ).hexdigest()
    return {
        "version": VERSION,
        "formal": False,
        "cohort_id": cohort,
        "controls": controls,
        "grouping": grouping_rows,
        "runs": sorted(rows, key=lambda r: (r["finished_at"], r["run_id"])),
        "interpretation": (
            "同口径描述性趋势；模型与运行实现可变化，不作因果或显著性声明。"
        ),
        "chart_bucketing": (
            "时间图自动分桶；同桶内各 run 通过率等权平均，逐 run 明细以此文件为准。"
        ),
    }


def load_trend(run_dirs):
    sources = []
    for directory in run_dirs:
        root = Path(directory)
        raw = (root / "results.json").read_bytes()
        receipt = json.loads((root / "langfuse_export.json").read_text())
        verified = json.loads((root / "langfuse_verification.json").read_text())
        digest = hashlib.sha256(raw).hexdigest()
        if (
            receipt["source_hash"] != digest
            or verified.get("source_hash") != digest
            or verified.get("status") != "VERIFIED"
        ):
            raise ValueError("trend requires verified saved source")
        sources.append(
            {
                "run": json.loads(raw),
                "analysis": build_diagnostics(root),
                "receipt": receipt,
            }
        )
    return build_trend(sources)
