"""从冻结任务选择构造完整分母，缺失 trial 保留显式占位。"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy


def task_layer(task: dict) -> str:
    level, mode = (
        task.get("evaluation_level", "e2e"),
        task.get("execution_mode", "agent"),
    )
    if mode == "decision":
        return "decision"
    if level not in {"module", "chain", "e2e"} or mode not in {"module", "agent"}:
        raise ValueError("unknown evaluation layer")
    return level


def counts(trials: list[dict]) -> dict:
    verdicts = dict(Counter(row["verdict"] for row in trials))
    valid = sum(row["verdict"] not in {"INVALID", "MISSING"} for row in trials)
    return {
        "planned_trials": len(trials),
        "completed_trials": len(trials) - verdicts.get("MISSING", 0),
        "valid_trials": valid,
        "missing_trials": verdicts.get("MISSING", 0),
        "verdicts": verdicts,
        "pass_rate_planned": verdicts.get("PASS", 0) / len(trials) if trials else None,
        "pass_rate_valid": verdicts.get("PASS", 0) / valid if valid else None,
    }


def build_population(source: dict, *, dataset: dict, annotations=None) -> dict:
    selected, execution = source["selected_result"], source["execution_result"]
    if execution["identity"].get("dataset") != dataset["legacy_identity"]:
        raise ValueError("dataset legacy identity differs from source run")
    tasks = {t["id"]: t for t in dataset["tasks"]}
    if len(tasks) != len(dataset["tasks"]):
        raise ValueError("duplicate dataset task")
    cases = execution["planned_case_ids"]
    if not set(cases) <= tasks.keys():
        raise ValueError("source selection absent from dataset")
    rows = {(r["case_id"], r["trial"]): r for r in selected["trials"]}
    trials = []
    for case in cases:
        task = tasks[case]
        for trial in range(1, execution["trials_per_case"] + 1):
            row = rows.get((case, trial))
            if row:
                for field in (
                    "family",
                    "category",
                    "split",
                    "evaluation_level",
                    "execution_mode",
                ):
                    fallback = (
                        "e2e"
                        if field == "evaluation_level"
                        else "agent"
                        if field == "execution_mode"
                        else None
                    )
                    if row.get(field, fallback) != task.get(field, fallback):
                        raise ValueError(
                            f"source grouping differs from dataset: {field}"
                        )
            trials.append(
                {
                    "case_id": case,
                    "trial": trial,
                    "family": task["family"],
                    "layer": task_layer(task),
                    "category": task["category"],
                    "split": task["split"],
                    "verdict": row["assessment"]["verdict"] if row else "MISSING",
                    "record": deepcopy(row),
                }
            )
    framework = (
        execution["identity"].get("offline") is True
        or "reference" in execution.get("mode", "")
        or any(
            r["observation"].get("execution_kind")
            == "deterministic_reference_not_agent"
            for r in execution["trials"]
        )
    )
    return {
        "trials": trials,
        "judge_trials": deepcopy(source.get("judge_trials", [])),
        "cases": deepcopy([tasks[c] for c in cases]),
        "trials_per_case": execution["trials_per_case"],
        "framework_only": framework,
        "layers": {
            layer: counts([r for r in trials if r["layer"] == layer])
            for layer in sorted({r["layer"] for r in trials})
        },
    }
