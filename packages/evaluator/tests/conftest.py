from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from eval_framework.capabilities import CapabilityBundle, CapabilityRegistry
from eval_framework.dataset_loader import load_dataset
from eval_framework.schemas import CaseResult
from eval_framework.tool_catalog import ToolCatalog, ToolContract


@pytest.fixture
def legacy_tool_catalog():
    tools = {
        "query_information": ToolContract(
            name="query_information",
            operation="read",
            fault_modes=frozenset({"normal", "empty_result", "error", "timeout"}),
        ),
        "prepare_resource": ToolContract(
            name="prepare_resource",
            operation="write",
            fault_modes=frozenset(
                {"normal", "error", "timeout", "commit_then_timeout"}
            ),
        ),
        "add_gift_to_backpack": ToolContract(
            name="add_gift_to_backpack",
            operation="write",
            fault_modes=frozenset(
                {"normal", "error", "timeout", "commit_then_timeout"}
            ),
        ),
    }
    return ToolCatalog(
        profiles={
            "legacy": frozenset({"query_information", "prepare_resource"}),
            "shadow_read": frozenset(),
            "shadow_full": frozenset({"add_gift_to_backpack"}),
        },
        tools=tools,
    )


def intent(
    name="query_information",
    status="READY",
    action="CALL_TOOL",
    parameters=None,
    missing=None,
):
    return {
        "intent": name,
        "status": status,
        "next_action": action,
        "parameters": parameters
        if parameters is not None
        else {"resource_type": "fixture", "environment": "test"},
        "missing_parameters": missing or [],
        "reason": "fixture",
    }


def assertion(name, weight=1, critical=False, config=None):
    return {
        "name": name,
        "weight": weight,
        "critical": critical,
        "config": config or {},
    }


def module_case(case_id="MODULE-1"):
    expected = intent()
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "task_id": "intent-routing",
        "scenario_type": "normal",
        "test_scope": "module",
        "target": "intent_router",
        "execution": {
            "user_input": "query fixture",
            "user_responses": [],
            "tool_profile": "legacy",
            "allowed_tools": None,
            "fault_injection": {},
            "max_steps": 4,
            "timeout_seconds": 5,
        },
        "oracle": {
            "expected_module_output": expected,
            "expected_agent_status": None,
            "expected_tool_calls": [],
            "forbidden_tools": [],
            "goal_state": None,
            "process_constraints": {},
            "expected_response": None,
            "evaluation": {
                "checks": [
                    assertion("output_schema_valid", critical=True),
                    assertion("intent_match", 2, True),
                    assertion("status_match"),
                    assertion("next_action_match"),
                    assertion("params_match"),
                    assertion("missing_params_match"),
                ]
            },
        },
        "labels": ["offline", "module"],
        "cleanup": None,
    }


def link_case(case_id="LINK-1"):
    case = module_case(case_id)
    case["execution"]["user_input"] = "query fixture chain"
    case["test_scope"] = "link"
    case["task_id"] = "query-chain"
    case["target"] = "legacy_query"
    case["oracle"]["expected_module_output"] = None
    case["oracle"]["expected_agent_status"] = "SUCCESS"
    case["oracle"]["expected_tool_calls"] = [
        {
            "name": "query_information",
            "arguments": {"resource_type": "fixture", "environment": "test"},
            "count": 1,
            "status": "SUCCESS",
        }
    ]
    case["oracle"]["evaluation"]["checks"] = [
        assertion("status_match", critical=True),
        assertion("tool_called", critical=True),
        assertion("tool_call_count"),
        assertion("tool_args_match"),
        assertion("tool_result_consistent", critical=True),
        assertion("no_state_change", critical=True),
    ]
    return case


def e2e_case(case_id="E2E-1"):
    return {
        "schema_version": "1.0",
        "case_id": case_id,
        "task_id": "confirmed-write",
        "scenario_type": "normal",
        "test_scope": "end_to_end",
        "target": "shadow_write",
        "execution": {
            "user_input": "grant gift",
            "user_responses": ["确认"],
            "tool_profile": "shadow_full",
            "allowed_tools": ["add_gift_to_backpack"],
            "fault_injection": {},
            "max_steps": 4,
            "timeout_seconds": 5,
        },
        "oracle": {
            "expected_module_output": None,
            "expected_agent_status": "SUCCESS",
            "expected_tool_calls": [
                {
                    "name": "add_gift_to_backpack",
                    "arguments": None,
                    "count": 1,
                    "status": "SUCCESS",
                }
            ],
            "forbidden_tools": [],
            "goal_state": {"mock_backpack_grant_count": 1},
            "process_constraints": {},
            "expected_response": {"expected_outcome": "SUCCESS"},
            "evaluation": {
                "checks": [
                    assertion("final_state_match", 2, True),
                    assertion("no_duplicate_side_effect", 1, True),
                    assertion("confirmation_requested", 1, True),
                    assertion("confirmation_accepted", 1, True),
                    assertion("no_write_before_confirmation", 1, True),
                    assertion("response_consistent"),
                ]
            },
        },
        "labels": ["offline", "write"],
        "cleanup": {"required": True, "strategy": "temporary_directory"},
    }


@pytest.fixture
def cases():
    return [module_case(), link_case(), e2e_case()]


@pytest.fixture
def dataset_path(tmp_path, cases):
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(case) for case in cases) + "\n")
    project_root = Path(__file__).resolve().parents[1]
    source_root = project_root / "datasets/mini_agent/capability_bundles" / (
        "ee27d000bf68bcf0034e6fd9bd9048c66a38799473a5bac4619410c72673486b"
    )
    bundle_root = tmp_path / "capability_bundles" / "fixture"
    shutil.copytree(source_root, bundle_root)
    bundle_sha256 = json.loads(
        (bundle_root / "bundle_manifest.json").read_text()
    )["capability_bundle_sha256"]
    dataset_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(".manifest.json").write_text(
        json.dumps(
            {
                "dataset_version": "fixture",
                "state": "UNKNOWN",
                "dataset_sha256": dataset_sha256,
                "capability_bundle": {
                    "provider_id": "mini_agent",
                    "sha256": bundle_sha256,
                    "path": "capability_bundles/fixture",
                },
                "execution_profiles": {
                    "legacy": {
                        "allowed_tools": ["query_information", "prepare_resource"]
                    },
                    "shadow_full": {
                        "allowed_tools": ["add_gift_to_backpack"]
                    },
                },
            }
        )
    )
    return path


@pytest.fixture
def capability_registry(dataset_path):
    dataset = load_dataset(dataset_path)
    assert dataset.capability_bundle_path is not None
    return CapabilityRegistry(
        CapabilityBundle.load(Path(dataset.capability_bundle_path))
    )


@pytest.fixture
def case_result_factory():
    def build(**updates):
        payload = {
            "evaluator_run_id": "eval-run",
            "case_id": "MODULE-1",
            "task_id": "intent-routing",
            "scenario_type": "normal",
            "test_scope": "module",
            "user_input": "query fixture",
            "trial_id": "trial_001",
            "run_mode": "framework_self_test",
            "tool_profile": "legacy",
            "tool_version": "fixture-tools",
            "max_steps": 4,
            "timeout_seconds": 5,
            "session_id": None,
            "agent_run_ids": [],
            "execution_status": "COMPLETED",
            "quality_conclusion": "PASS",
            "score": 100,
            "module_output": intent(),
            "turn_results": [],
            "tool_calls": [],
            "trace_events": [],
            "turn_snapshots": [],
            "system_snapshot": None,
            "assertion_results": [],
            "first_failed_assertion": None,
            "latency_ms": 1,
            "evidence_refs": [],
            "cleanup_status": "CLEANED",
        }
        payload.update(updates)
        return CaseResult.model_validate(payload)

    return build
