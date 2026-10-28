"""Run an offline external Provider through Inspect and verify real verdicts.

This is a framework self-test, not a benchmark of mini_agent. The copied bundle
is reference documentation. The external static adapter reads supplied snapshots;
only the trusted Scorer receives expectations. No model or hosted service is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from tempfile import mkdtemp

from eval_framework import (
    ContractStore,
    compile_suite,
    execute_compiled_suite,
    load_suite_definition,
    write_report,
)
from eval_framework.composition import default_plugin_catalog

REFERENCE_BUNDLE = "99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8"
EXPECTED = {
    "DEMO-PASS": "PASS",
    "DEMO-FAIL": "FAIL",
    "DEMO-INCONCLUSIVE": "INCONCLUSIVE",
}


def build_suite(root: Path) -> Path:
    repository = Path(__file__).resolve().parents[1]
    source = repository / "packages/evaluator/datasets/mini_agent/capability_bundles"
    shutil.copytree(source / REFERENCE_BUNDLE, root / "bundle")
    cases = []
    for name, actual in (
        ("PASS", {"value": 42}),
        ("FAIL", {"value": 7}),
        ("INCONCLUSIVE", {}),
    ):
        cases.append(
            {
                "schema_version": "1.0",
                "case_id": f"DEMO-{name}",
                "task_id": "offline-observation-demo",
                "scenario_type": "normal",
                "test_scope": "module",
                "target": "offline_snapshot",
                "execution": {
                    "user_input": "Read the supplied local snapshot.",
                    "tool_profile": "none",
                    "timeout_seconds": 10,
                    "adapter_input": {
                        "input": {
                            "operation": "inspect_snapshot",
                            "declared_value": actual,
                        },
                        "preconditions": [],
                    },
                },
                "oracle": {
                    "expected_response": {"private_note": "oracle-secret"},
                    "evaluation": {
                        "checks": [
                            {
                                "name": "observations_match",
                                "weight": 1,
                                "critical": True,
                                "config": {
                                    "checks": [
                                        {
                                            "path": "/declared_value/value",
                                            "operator": "equals",
                                            "expected": 42,
                                        }
                                    ]
                                },
                            }
                        ]
                    },
                },
                "labels": ["offline", "framework-self-test"],
            }
        )
    dataset = root / "cases.json"
    dataset.write_text(
        json.dumps(
            {
                "metadata": {
                    "dataset_version": "offline-demo-v1",
                    "lifecycle_state": "FROZEN",
                    "provider_id": "mini_agent",
                    "execution_profiles": {"none": {"allowed_tools": []}},
                },
                "cases": cases,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    suite = {
        "schema_version": "1.0",
        "suite_id": "offline-external-demo",
        "suite_version": "1.0.0",
        "lifecycle_state": "FROZEN",
        "dataset_loader": {
            "plugin_id": "fixture_json_document_v1",
            "version": "1.0.0",
            "config": {},
        },
        "dataset_sources": [{"path": "cases.json", "sha256": digest(dataset)}],
        "provider": {
            "plugin_id": "external_provider_v1",
            "version": "1.0.0",
            "config": {
                "binding": {
                    "version": "1.0",
                    "agent_id": "mini_agent",
                    "adapter": "static",
                }
            },
        },
        "capability_bundle": {
            "contract_id": "offline-demo-reference",
            "version": "3.0",
            "path": "bundle/agent.json",
            "sha256": digest(root / "bundle/agent.json"),
        },
        "run_config": {"run_mode": "framework_self_test", "trials_per_case": 1},
    }
    path = root / "suite.json"
    path.write_text(json.dumps(suite, indent=2), encoding="utf-8")
    return path


def run_demo(output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    root = Path(mkdtemp(prefix="demo-", dir=output.resolve()))
    suite = build_suite(root)
    catalog = default_plugin_catalog()
    compiled = compile_suite(load_suite_definition(suite), catalog, ContractStore(root))
    result = execute_compiled_suite(compiled, catalog, output_dir=root)
    paths = write_report(result, root)
    conclusions = {case.case_id: case.quality_conclusion for case in result.cases}
    if conclusions != EXPECTED or len(result.cases) != len(EXPECTED):
        raise RuntimeError(
            f"Unexpected offline verdicts: {conclusions}; report: {paths.report}"
        )
    if not all(case.execution_status == "COMPLETED" for case in result.cases):
        raise RuntimeError("An offline case did not complete execution")
    inspect_logs = list(Path(paths.output_dir).rglob("*.eval"))
    if len(inspect_logs) != 1:
        raise RuntimeError(f"Expected one native Inspect log, found {inspect_logs}")
    manifest = {
        "suite": str(suite),
        "run_directory": paths.output_dir,
        "report": paths.report,
        "results": paths.results,
        "inspect_log": str(inspect_logs[0]),
        "conclusions": conclusions,
    }
    (root / "demo.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    print(json.dumps(run_demo(args.output_dir)))


if __name__ == "__main__":
    main()
