"""独立、可复现的报告解释产物；只读历史证据，无 Agent 或 Langfuse 依赖。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .report_insights import diagnose, intent_mode, load_contracts, load_report_tasks

VERSION = "report-diagnostics-v1"
RULES_VERSION = "evidence-rules-v2"


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def profile_hash(profile):
    return hashlib.sha256(
        canonical({k: v for k, v in profile.items() if k != "sha256"})
    ).hexdigest()


def load_profile(run_dir):
    path = Path(run_dir) / "report-diagnostics.json"
    if not path.exists():
        return None
    profile = json.loads(path.read_text())
    if (
        profile.get("schema_version") != VERSION
        or not profile.get("profile_id")
        or not profile.get("profile_version")
    ):
        raise ValueError("unsupported diagnostic profile identity")
    if profile.get("sha256") != profile_hash(profile):
        raise ValueError("diagnostic profile Hash mismatch")
    aliases = profile.get("aliases", {})
    if not isinstance(aliases, dict) or any(
        not isinstance(v, dict)
        or any(
            not isinstance(a, str) or not isinstance(b, str) or not a or not b
            for a, b in v.items()
        )
        for v in aliases.values()
    ):
        raise ValueError("invalid intent-scoped aliases")
    return profile


def build_diagnostics(run_dir):
    root = Path(run_dir)
    raw = (root / "results.json").read_bytes()
    run = json.loads(raw)
    contracts, warnings = load_contracts(run)
    tasks, task_warnings = load_report_tasks(run)
    profile = load_profile(root)
    trials = []
    numbers = {}
    for row in run["trials"]:
        view = dict(row)
        if row["case_id"] in tasks:
            view["_report_task"] = tasks[row["case_id"]]
        findings = diagnose(row, contracts, aliases=(profile or {}).get("aliases", {}))
        for finding in findings:
            finding["number"] = numbers.setdefault(finding["kind"], len(numbers) + 1)
        trials.append(
            {
                "case_id": row["case_id"],
                "trial": row["trial"],
                "category": row.get("category"),
                "operation": intent_mode(view, contracts),
                "goal_bound": row["case_id"] in tasks,
                "verdict": row["assessment"]["verdict"],
                "findings": findings,
            }
        )
    body = {
        "version": VERSION,
        "rules_version": RULES_VERSION,
        "rules_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
            + Path(__file__).with_name("report_insights.py").read_bytes()
        ).hexdigest(),
        "formal": False,
        "run_id": run["run_id"],
        "source_hash": hashlib.sha256(raw).hexdigest(),
        "profile": profile,
        "reference_contracts": {k: v["report_source"] for k, v in contracts.items()},
        "warnings": warnings + task_warnings,
        "trials": trials,
    }
    body["analysis_id"] = hashlib.sha256(canonical(body)).hexdigest()
    return body


def write_diagnostics(run_dir):
    root = Path(run_dir)
    analysis = build_diagnostics(root)
    raw = canonical(analysis) + b"\n"
    directory = root / "report-diagnostics"
    directory.mkdir(exist_ok=True)
    archive = directory / (analysis["analysis_id"] + ".json")
    if archive.exists() and archive.read_bytes() != raw:
        raise ValueError("immutable diagnostic artifact changed")
    archive.write_bytes(raw)
    target = root / "diagnostics.json"
    target.write_bytes(raw)
    return target
