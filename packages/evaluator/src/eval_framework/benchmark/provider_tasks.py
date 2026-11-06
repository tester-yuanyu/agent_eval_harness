"""Frozen Provider task envelopes, independent of any concrete Agent."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from ..schemas import EvalCase

CONTRACT = "provider-tasks-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provider_dataset_identity(root: Path) -> dict:
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("task_contract") != CONTRACT:
        raise ValueError("unsupported Provider task contract")
    for name, expected in manifest["files"].items():
        path = (root / name).resolve()
        if (
            not path.is_relative_to(root)
            or not path.is_file()
            or sha256(path) != expected
        ):
            raise ValueError(f"Provider dataset file hash mismatch: {name}")
    return {**manifest, "manifest_sha256": sha256(root / "manifest.json")}


def as_eval_case(task: dict) -> EvalCase:
    return EvalCase.model_validate(
        {
            "schema_version": "1.0",
            "case_id": task["id"],
            "task_id": task["family"],
            "scenario_type": task["scenario_type"],
            "test_scope": task["scope"],
            "target": task["target"],
            "execution": task["execution"],
            "oracle": task["oracle"],
            "labels": task["labels"],
        }
    )


def public_execution(task: dict) -> dict:
    return copy.deepcopy(
        {
            "execution": task["execution"],
            "scope": task["scope"],
            "environment": task["environment"],
        }
    )


def load_provider_tasks(root: Path) -> list[dict]:
    identity = provider_dataset_identity(root)
    tasks = [
        json.loads(line)
        for line in (Path(root) / "tasks.jsonl").read_text().splitlines()
        if line.strip()
    ]
    if len(tasks) != identity["task_count"] or len({t["id"] for t in tasks}) != len(
        tasks
    ):
        raise ValueError("Provider task count/IDs do not match manifest")
    for task in tasks:
        case = as_eval_case(task)
        if (
            task["prompt"] != case.execution.user_input
            or task["followups"] != case.execution.user_responses
        ):
            raise ValueError("public task envelope differs from execution")
        if task["fixtures"] or task["split"] != "dev":
            raise ValueError(
                "Provider v1 uses public environment fixtures and dev split"
            )
        if case.test_scope == "module" and case.execution.user_responses:
            raise ValueError("module tasks cannot contain followup turns")
        expected = {
            "module": ("module", "module"),
            "link": ("chain", "agent"),
            "end_to_end": ("e2e", "agent"),
        }[case.test_scope]
        if (task["evaluation_level"], task["execution_mode"]) != expected:
            raise ValueError("Provider task level/mode/scope mismatch")
    return tasks
