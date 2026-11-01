"""Regrade immutable saved execution evidence without any Agent invocation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from .metrics import METRICS_VERSION, score_task
from .runner import digest, now, save_json, scoring_identity, summarize
from .tasks import dataset_identity, load_tasks


def _validate_source(source: dict[str, Any], tasks: dict[str, dict[str, Any]]) -> None:
    if digest(source["identity"]) != source["identity_hash"]:
        raise ValueError("Source run identity hash is inconsistent")
    selected = source["planned_case_ids"]
    repeats = source["trials_per_case"]
    if (
        not selected
        or len(set(selected)) != len(selected)
        or not set(selected).issubset(tasks)
        or isinstance(repeats, bool)
        or not isinstance(repeats, int)
        or repeats < 1
    ):
        raise ValueError("Source task selection or repeat count is invalid")
    expected = {(case, trial) for case in selected for trial in range(1, repeats + 1)}
    seen = set()
    for row in source["trials"]:
        key = row["case_id"], row["trial"]
        if key not in expected or key in seen:
            raise ValueError("Source contains an unexpected or duplicate trial")
        seen.add(key)
        if row.get("identity_hash") != source["identity_hash"]:
            raise ValueError("Source trial identity does not match its run")
        task = tasks[row["case_id"]]
        if any(
            row.get(field) != task[field] for field in ("category", "split", "family")
        ):
            raise ValueError("Source trial grouping does not match the frozen dataset")
        if not isinstance(row.get("observation"), dict):
            raise ValueError("Source trial has no saved observation")
        if (
            source.get("mode") == "real_agent"
            and row["observation"].get("execution_kind")
            == "deterministic_reference_not_agent"
        ):
            raise ValueError("Reference evidence cannot be labeled as a real Agent run")
    if seen != expected:
        raise ValueError(
            "Source execution is incomplete; missing trials cannot be invented"
        )


def regrade_run(
    source_dir: Path, dataset_path: Path, output_dir: Path
) -> dict[str, Any]:
    """Write a new grading run while preserving every original execution byte.

    The new run remains an analysis of its original executions, not new trials.
    The source hash and original execution identity make that distinction auditable.
    Existing output directories are rejected rather than silently overwritten.
    """
    source_dir, output_dir = Path(source_dir).resolve(), Path(output_dir).resolve()
    if output_dir == source_dir or output_dir.is_relative_to(source_dir):
        raise ValueError("Regrading output must be outside the original run directory")
    if output_dir.exists():
        raise ValueError("Regrading output already exists; use a new directory")
    source_path = source_dir / "results.json"
    raw = source_path.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    source = json.loads(raw)
    frozen_identity = dataset_identity(Path(dataset_path))
    if source["identity"]["dataset"] != frozen_identity:
        raise ValueError("Regrading dataset does not match the source run")
    tasks = {task["id"]: task for task in load_tasks(Path(dataset_path))}
    _validate_source(source, tasks)
    grading = scoring_identity()
    identity = copy.deepcopy(source["identity"])
    identity.update(
        scoring_version=METRICS_VERSION,
        scoring_identity=grading,
        source_results_sha256=source_hash,
    )
    identity_hash = digest(identity)
    graded_at = now()
    provenance = {
        "operation": "regrade_saved_evidence",
        "source_run_id": source["run_id"],
        "source_results_sha256": source_hash,
        "source_identity_hash": source["identity_hash"],
        "graded_at": graded_at,
        "new_agent_executions": 0,
        "new_model_requests": 0,
    }
    records = []
    for original in source["trials"]:
        row = copy.deepcopy(original)
        assessment = score_task(tasks[row["case_id"]], row["observation"])
        if row.get("cleanup_status") != "complete":
            assessment.update(verdict="INVALID", validity="INVALID")
            assessment["errors"].append(
                {
                    "kind": "harness",
                    "code": "CLEANUP_NOT_COMPLETE",
                    "message": "Regrading cannot erase a workspace cleanup failure",
                }
            )
        row.update(
            identity_hash=identity_hash,
            execution_identity_hash=original.get(
                "execution_identity_hash", source["identity_hash"]
            ),
            source_assessment=copy.deepcopy(original["assessment"]),
            source_trial_sha256=digest(original),
            assessment=assessment,
            graded_at=graded_at,
        )
        records.append(row)
    result = copy.deepcopy(source)
    result.update(
        run_id=output_dir.name + "-regrade-" + identity_hash[:8],
        identity=identity,
        identity_hash=identity_hash,
        execution_identity=copy.deepcopy(
            source.get("execution_identity", source["identity"])
        ),
        execution_run_id=source.get("execution_run_id", source["run_id"]),
        regrade=provenance,
        scoring_backend="deepeval",
        trials=records,
        summary=summarize(
            records, source["planned_case_ids"], source["trials_per_case"]
        ),
    )
    if source_path.read_bytes() != raw or scoring_identity() != grading:
        raise ValueError(
            "Source evidence or grading implementation changed while regrading"
        )
    output_dir.mkdir(parents=True, exist_ok=False)
    order = {case: index + 1 for index, case in enumerate(source["planned_case_ids"])}
    for row in records:
        name = f"{order[row['case_id']]:04d}-t{row['trial']}.json"
        save_json(output_dir / "trials" / name, row)
    save_json(
        output_dir / "run.json",
        {
            key: value
            for key, value in result.items()
            if key not in {"trials", "summary"}
        },
    )
    save_json(output_dir / "results.json", result)
    return result
