"""Offline framework self-test through the real mini_agent and SQLite environment.

Model responses are scripted. Native confirmation cannot currently release writes,
so grant/correction cases deliberately report FAIL. No network calls are made.
"""

import argparse
import hashlib
import json
from collections import deque
from pathlib import Path
from tempfile import mkdtemp

from minimal_agent import build_default_intent_registry
from minimal_agent.capabilities import export_capability_bundle

from eval_framework import (
    ContractStore,
    compile_suite,
    execute_compiled_suite,
    load_suite_definition,
    write_report,
)
from eval_framework.composition import default_plugin_catalog
from eval_framework.providers.mini_agent.state_environment import GiftSQLiteEnvironment

PARAMETERS = {
    "gift_id": 300101,
    "gift_ids": None,
    "gift_nums": None,
    "user_id": 10001,
    "user_ids": None,
    "num": 2,
    "duration_days": 7,
    "environment": "qa",
}


def decision(status, parameters, *, intent="add_backpack_gift"):
    return {
        "intent": intent,
        "status": status,
        "next_action": {
            "READY": "CALL_TOOL",
            "NEED_CONFIRMATION": "ASK_CONFIRMATION",
            "NEED_CLARIFICATION": "ASK_USER",
            "REJECTED": "REJECT",
        }[status],
        "parameters": parameters,
        "missing_parameters": ["user_id"] if status == "NEED_CLARIFICATION" else [],
        "reason": "offline fixture response",
    }


class DemoModelClient:
    def __init__(self, execution):
        # Selected solely from execution input; no oracle reaches the model client.
        scripts = {
            "grant": [
                decision("NEED_CLARIFICATION", {}),
                decision("NEED_CONFIRMATION", PARAMETERS),
                decision("READY", PARAMETERS),
            ],
            "cancel": [
                decision("NEED_CONFIRMATION", PARAMETERS),
                decision("REJECTED", {}, intent="unsupported"),
            ],
            "correction": [
                decision("NEED_CONFIRMATION", PARAMETERS),
                decision("NEED_CONFIRMATION", {**PARAMETERS, "num": 3}),
                decision("READY", {**PARAMETERS, "num": 3}),
            ],
            "link": [decision("NEED_CONFIRMATION", PARAMETERS)],
        }
        self._responses = deque(scripts[execution.user_input])

    def classify_intent(self, user_input):
        return self._responses.popleft()

    def next_tool_step(self, request):
        raise AssertionError("Current native write policy must not enter the tool loop")

    def metadata(self):
        return {"model": "scripted-stateful-self-test"}


def check(name, config=None):
    return {"name": name, "weight": 1, "critical": True, "config": config or {}}


def build_suite(root):
    env = GiftSQLiteEnvironment(frozenset({"add_gift_to_backpack"}))
    try:
        export_capability_bundle(
            root / "bundle", build_default_intent_registry(), env.registry
        )
    finally:
        env.cleanup()
    waiting = {
        "status": "NEED_CONFIRMATION",
        "tool_calls": [],
        "state": {"grant_count": 0},
    }
    configurations = [
        (
            "grant",
            ["user_id 10001, gift_id 300101, num 2, qa", "confirm"],
            [
                {
                    "status": "NEED_CLARIFICATION",
                    "tool_calls": [],
                    "state": {"grant_count": 0},
                },
                waiting,
                {"status": "SUCCESS", "state": {"grant_count": 1}},
            ],
            1,
            2,
        ),
        (
            "cancel",
            ["cancel"],
            [
                waiting,
                {"status": "REJECTED", "tool_calls": [], "state": {"grant_count": 0}},
            ],
            0,
            0,
        ),
        (
            "correction",
            ["change num to 3", "confirm"],
            [
                waiting,
                {**waiting, "parameters": {"num": 3}},
                {
                    "status": "SUCCESS",
                    "parameters": {"num": 3},
                    "state": {"grant_count": 1},
                },
            ],
            1,
            3,
        ),
        ("link", [], [waiting], 0, 0),
    ]
    cases = []
    for name, responses, turns, count, quantity in configurations:
        link = name == "link"
        checks = [check("turns_match", {"turns": turns})]
        checks.append(check("no_state_change" if link else "final_state_match"))
        cases.append(
            {
                "schema_version": "1.0",
                "case_id": f"GIFT-{name.upper()}",
                "task_id": "stateful-gift",
                "scenario_type": "normal",
                "test_scope": "link" if link else "end_to_end",
                "target": "gift-task",
                "execution": {
                    "user_input": name,
                    "user_responses": responses,
                    "tool_profile": "gift",
                    "max_steps": 4,
                    "timeout_seconds": 30,
                },
                "oracle": {
                    "goal_state": {"grant_count": count, "total_quantity": quantity},
                    "forbidden_tools": ["add_gift_to_backpack"] if link else [],
                    "evaluation": {"checks": checks},
                },
                "labels": ["offline", "framework-self-test"],
                "cleanup": {"required": True, "strategy": "temporary_directory"},
            }
        )
    dataset_path = root / "cases.json"
    dataset_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "dataset_version": "stateful-gift-self-test-v1",
                    "lifecycle_state": "FROZEN",
                    "provider_id": "mini_agent",
                    "execution_profiles": {
                        "gift": {"allowed_tools": ["add_gift_to_backpack"]}
                    },
                },
                "cases": cases,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    suite = {
        "schema_version": "1.0",
        "suite_id": "stateful-gift-self-test",
        "suite_version": "1.0.0",
        "lifecycle_state": "FROZEN",
        "dataset_loader": {
            "plugin_id": "fixture_json_document_v1",
            "version": "1.0.0",
            "config": {},
        },
        "dataset_sources": [{"path": "cases.json", "sha256": digest(dataset_path)}],
        "provider": {
            "plugin_id": "mini_agent_provider_v1",
            "version": "1.0.0",
            "config": {"environment": "gift_sqlite_v1"},
        },
        "capability_bundle": {
            "contract_id": "gift-fixture-bundle",
            "version": "3.0",
            "path": "bundle/agent.json",
            "sha256": digest(root / "bundle/agent.json"),
        },
        "run_config": {"run_mode": "framework_self_test", "trials_per_case": 2},
    }
    suite_path = root / "suite.json"
    suite_path.write_text(json.dumps(suite, indent=2), encoding="utf-8")
    return suite_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="artifacts")
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = Path(mkdtemp(prefix="stateful-gift-", dir=output))
    suite_path = build_suite(root)
    catalog = default_plugin_catalog()
    compiled = compile_suite(
        load_suite_definition(suite_path), catalog, ContractStore(root)
    )
    result = execute_compiled_suite(
        compiled, catalog, model_client_factory=DemoModelClient, output_dir=root
    )
    paths = write_report(result, root)
    print(
        json.dumps(
            {
                "suite": str(suite_path),
                "run_directory": paths.output_dir,
                "report": paths.report,
                "quality_counts": result.summary.quality_counts,
            }
        )
    )


if __name__ == "__main__":
    main()
