"""One-time mechanical migration for the two approved intent Suites."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITES = (
    "mini_agent_query_user_intent_v1",
    "mini_agent_query_gift_intent_v1",
)
GATES = [
    "evaluator",
    "capability_snapshot",
    "contract",
    "coverage",
    "duplicate",
    "leakage",
    "quality",
]


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def migrate(suite_id: str) -> None:
    suite_dir = ROOT / "suites" / suite_id
    suite_path = suite_dir / "suite.json"
    suite = json.loads(suite_path.read_text())
    if "policies" in suite:
        return
    generation = {
        "policy_kind": "generation",
        "policy_version": "1.0",
        "schema_version": "1.0",
        "config": {
            "candidate_protocol": suite.pop("candidate_protocol"),
            "compilation": suite.pop("compilation"),
        },
    }
    coverage = {
        "policy_kind": "coverage",
        "policy_version": "1.0",
        "schema_version": "1.0",
        "config": suite.pop("coverage"),
    }
    validation = {
        "policy_kind": "validation",
        "policy_version": "1.0",
        "schema_version": "1.0",
        "config": {
            "validation": suite.pop("validation"),
            "quality": suite.pop("quality_policy"),
            "enabled_gates": GATES,
        },
    }
    suite.pop("legacy_embedded_policy", None)
    suite["policies"] = {
        "source": {
            "base": "builder_root",
            "path": "policies/common/source_v1.json",
        },
        "coverage": {"base": "suite_dir", "path": "policies/coverage.json"},
        "generation": {
            "base": "suite_dir",
            "path": "policies/generation.json",
        },
        "validation": {
            "base": "suite_dir",
            "path": "policies/validation.json",
        },
        "review": {
            "base": "builder_root",
            "path": "policies/common/review_v1.json",
        },
        "freeze": {
            "base": "builder_root",
            "path": "policies/common/freeze_v1.json",
        },
    }
    _write(suite_dir / "policies" / "generation.json", generation)
    _write(suite_dir / "policies" / "coverage.json", coverage)
    _write(suite_dir / "policies" / "validation.json", validation)
    _write(suite_path, suite)


if __name__ == "__main__":
    for item in SUITES:
        migrate(item)
