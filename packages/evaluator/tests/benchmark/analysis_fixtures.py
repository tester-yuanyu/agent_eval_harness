"""显式合成的已保存结果；仅测试分析，不伪装真实模型成绩。"""

import json
from copy import deepcopy

from capability_snapshot_kit.hashing import sha256_json


def tasks():
    return [
        dict(
            id=c,
            family=f,
            category="files",
            split="dev",
            evaluation_level="e2e",
            execution_mode="agent",
        )
        for c, f in (("a", "fa"), ("b", "fb"))
    ]


def run(repeats=3):
    identity = {
        "dataset": {"id": "synthetic"},
        "offline": False,
        "case_ids": ["a", "b"],
        "repeats": repeats,
        "config": {"model": "offline-fixture"},
        "runtime": {"id": "test"},
    }
    identity_hash = sha256_json(identity)
    rows = []
    for task in tasks():
        for trial in range(1, repeats + 1):
            rows.append(
                {
                    **{k: v for k, v in task.items() if k != "id"},
                    "identity_hash": identity_hash,
                    "case_id": task["id"],
                    "trial": trial,
                    "latency_seconds": 1.0,
                    "observation": {
                        "execution_kind": "real_agent",
                        "status": "completed",
                        "evidence_complete": True,
                        "events": [],
                        "usage": {},
                    },
                    "assessment": {
                        "verdict": "FAIL"
                        if task["id"] == "b" and trial == 3
                        else "PASS",
                        "validity": "VALID",
                        "checks": [],
                        "errors": [],
                        "metrics": [],
                    },
                }
            )
    return {
        "run_id": "synthetic-execution",
        "identity": identity,
        "identity_hash": identity_hash,
        "mode": "real_agent",
        "planned_case_ids": ["a", "b"],
        "trials_per_case": repeats,
        "trials": rows,
    }


def save(path, value):
    path.mkdir(parents=True, exist_ok=True)
    (path / "results.json").write_text(json.dumps(value, ensure_ascii=False))
    return path


def dataset():
    return {"tasks": deepcopy(tasks()), "legacy_identity": {"id": "synthetic"}}
