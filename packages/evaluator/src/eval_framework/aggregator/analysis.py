"""版本化本地分析；输出仅包含公开标识、统计及证据引用。"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path

from capability_snapshot_kit.hashing import sha256_json
from eval_contracts import benchmark_analysis
from eval_contracts.benchmark_analysis import AnalysisPolicy

from .failures import classify_failure, summarize_failures
from .populations import build_population


def analysis_sources_identity() -> dict:
    root = Path(__file__).parents[1]
    paths = sorted(
        {
                *Path(__file__).parent.glob("*.py"),
                *root.glob("benchmark/analysis*.py"),
                *root.glob("benchmark/datasets/*.py"),
            }
    )
    hashes = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
    }
    path = Path(benchmark_analysis.__file__)
    hashes["eval_contracts/benchmark_analysis.py"] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    return hashes


def analyze_run(
    source: dict, *, dataset: dict, annotations=None, policy: AnalysisPolicy
) -> dict:
    population = build_population(source, dataset=dataset, annotations=annotations)
    identity = {
        "version": policy.analysis_version,
        "policy": asdict(policy),
        "source_hashes": source["verified_source_hashes"],
        "selected_sha256": source["selected_sha256"],
        "dataset_identity_hash": sha256_json(dataset["legacy_identity"]),
        "analysis_sources": analysis_sources_identity(),
    }
    execution = source["execution_result"]
    return {
        "identity": identity,
        "identity_hash": sha256_json(identity),
        "execution_run_id": execution["run_id"],
        "execution_identity_hash": execution["identity_hash"],
        "scope": "framework_demo"
        if population["framework_only"]
        else "saved_execution_analysis",
        "layers": population["layers"],
        "failures": summarize_failures(population),
        "judge_coverage": {
            "scored_trials": len(source["judge_trials"]),
            "planned_trials": len(population["trials"]),
        },
        "availability": {
            "reliability": "pending",
            "efficiency": "pending",
            "annotations": "not_provided",
        },
        "trials": [
            {
                **{
                    k: row[k]
                    for k in ("case_id", "trial", "family", "layer", "verdict")
                },
                "failure": classify_failure(row["record"]),
            }
            for row in population["trials"]
        ],
        "limitations": [
            "分层分母独立；不输出跨层总成功率。",
            "只读保存证据，复评不增加执行。",
            "诊断不覆盖正式 verdict；不声明统计显著性。",
        ],
    }
