from __future__ import annotations

import time
from pathlib import Path

import pytest
from conftest import intent
from minimal_agent.runtime.model_client import InvalidModelOutputError
from support.model_client import DeterministicModelClient as ScriptedModelClient

from eval_framework import RunConfig, load_dataset, run_evaluation
from eval_framework.capabilities import CapabilityBundle, CapabilityRegistry
from eval_framework.diagnostics import DiagnosticRegistry
from eval_framework.provider import AdapterOutput, ProviderExceptionInfo
from eval_framework.runner import run_provider_evaluation
from eval_framework.schemas import AssertionResult, ExecutionProfile, ExecutionSpec
from eval_framework.scoring import score_assertions
from eval_framework.tool_catalog import ToolCatalog


def scripts(execution: ExecutionSpec):
    if execution.user_input == "query fixture" and execution.tool_profile == "legacy":
        return ScriptedModelClient([intent()])
    if execution.user_input == "grant gift":
        return ScriptedModelClient(
            [
                intent(
                    "add_backpack_gift",
                    "NEED_CONFIRMATION",
                    "ASK_CONFIRMATION",
                    {
                        "gift_id": 300101,
                        "user_id": 10001,
                        "num": 1,
                        "duration_days": 7,
                        "environment": "qa",
                    },
                )
            ]
        )
    return ScriptedModelClient(
        [
            intent(),
            {
                "type": "function_call",
                "call_id": "call-query",
                "name": "query_information",
                "arguments": {"resource_type": "fixture", "environment": "test"},
            },
            {"type": "message", "content": "done"},
        ]
    )


def test_module_link_e2e_all_run_offline_and_are_isolated(dataset_path):
    dataset = load_dataset(dataset_path)
    registry = CapabilityRegistry(
        CapabilityBundle.load(Path(dataset.capability_bundle_path))
    )

    class ThreeScopeProvider:
        provider_id = "mini_agent"
        provider_version = "three-scope-test-v1"
        diagnostics = DiagnosticRegistry()

        def __init__(self):
            self.capabilities = registry
            self.tools = ToolCatalog.from_registry(
                registry,
                profiles={
                    "legacy": ExecutionProfile(
                        allowed_tools=["query_information", "prepare_resource"]
                    ),
                    "shadow_read": ExecutionProfile(
                        allowed_tools=[
                            "query_user_info",
                            "query_gift_info",
                            "query_pool_config",
                        ]
                    ),
                    "shadow_full": ExecutionProfile(
                        allowed_tools=[
                            "query_user_info",
                            "query_gift_info",
                            "query_pool_config",
                            "add_gift_to_backpack",
                        ]
                    ),
                },
            )
            self.seen = []

        def create_runtime(self, execution, session_id, scope):
            self.seen.append(execution)
            return {"session_id": session_id}

        def run_module(self, runtime, execution):
            del runtime, execution
            return AdapterOutput(
                intent(),
                [],
                None,
                [],
                None,
                [{"event_id": "event-intent", "event_type": "intent_requested"}],
            )

        def run_full(self, runtime, execution, scope):
            del runtime
            if scope == "link":
                call = {
                    "call_id": "call-query",
                    "name": "query_information",
                    "arguments": {
                        "resource_type": "fixture",
                        "environment": "test",
                    },
                    "status": "SUCCESS",
                    "output": {"success": True},
                    "error": None,
                    "duration_ms": 0,
                }
                return AdapterOutput(
                    None,
                    [
                        {
                            "run_id": "run-link",
                            "status": "SUCCESS",
                            "tool_calls": [call],
                            "events": [
                                {
                                    "event_id": "event-tool",
                                    "event_type": "tool_succeeded",
                                    "payload": {"call_id": "call-query"},
                                }
                            ],
                            "final_response": "done",
                        }
                    ],
                    {"value": 0},
                    [{"value": 0}],
                    {"value": 0},
                )
            del execution
            return AdapterOutput(
                None,
                [
                    {
                        "run_id": "run-confirm",
                        "status": "NEED_CONFIRMATION",
                        "tool_calls": [],
                        "events": [
                            {
                                "event_id": "event-start-1",
                                "event_type": "run_started",
                                "payload": {
                                    "tools": {"tool_names": ["add_gift_to_backpack"]}
                                },
                            },
                            {
                                "event_id": "event-confirm-request",
                                "event_type": "confirmation_requested",
                                "payload": {},
                            },
                        ],
                        "final_response": "confirm",
                    },
                    {
                        "run_id": "run-write",
                        "status": "SUCCESS",
                        "tool_calls": [],
                        "events": [
                            {
                                "event_id": "event-start-2",
                                "event_type": "run_started",
                                "payload": {
                                    "tools": {"tool_names": ["add_gift_to_backpack"]}
                                },
                            },
                            {
                                "event_id": "event-confirm-accepted",
                                "event_type": "confirmation_accepted",
                                "payload": {},
                            },
                        ],
                        "final_response": "done",
                    },
                ],
                {"mock_backpack_grant_count": 0},
                [
                    {"mock_backpack_grant_count": 0},
                    {"mock_backpack_grant_count": 1},
                ],
                {"mock_backpack_grant_count": 1},
            )

        def cleanup(self, runtime):
            runtime["cleaned"] = True

        def classify_exception(self, exc):
            return ProviderExceptionInfo(
                execution_status="AGENT_EXCEPTION",
                exception={"type": type(exc).__name__, "message": str(exc)},
            )

        def runtime_metadata(self, runtime):
            del runtime
            return {"client_type": "ThreeScopeProvider"}

        def tool_version(self, runtime):
            del runtime
            return "fixture-tools-v1"

    provider = ThreeScopeProvider()
    result = run_provider_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test"),
        provider,
    )
    assert [case.quality_conclusion for case in result.cases] == [
        "PASS",
        "PASS",
        "PASS",
    ]
    assert result.cases[0].agent_run_ids == []
    assert result.cases[0].trace_events
    assert result.cases[0].trace_events[0]["event_type"] == "intent_requested"
    assert len(result.cases[2].turn_results) == 2
    assert len(set(result.cases[2].agent_run_ids)) == 2
    assert result.cases[2].system_snapshot["mock_backpack_grant_count"] == 1
    assert all(case.cleanup_status == "CLEANED" for case in result.cases)
    assert result.cases[0].task_id == "intent-routing"
    assert result.cases[0].test_scope == "module"
    assert result.cases[0].user_input == "query fixture"
    assert len({case.session_id for case in result.cases[1:]}) == 2
    assert all("expected" not in item.model_dump_json() for item in provider.seen)
    run_started = [
        event
        for event in result.cases[2].trace_events
        if event["event_type"] == "run_started"
    ]
    assert len(run_started) == 2
    assert all(
        event["payload"]["tools"]["tool_names"] == ["add_gift_to_backpack"]
        for event in run_started
    )
    assert result.cases[2].turn_snapshots[0]["mock_backpack_grant_count"] == 0
    assert {case.trial_id for case in result.cases} == {"trial_001"}
    assert result.trials_per_case == 1


def test_legacy_factory_call_emits_deprecation_warning(dataset_path):
    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]

    with pytest.warns(DeprecationWarning):
        result = run_evaluation(
            dataset,
            RunConfig(run_mode="framework_self_test"),
            scripts,
        )

    assert result.cases[0].quality_conclusion == "PASS"


def test_wrong_module_answer_is_stable_fail(dataset_path):
    def factory(execution):
        if execution.tool_profile == "legacy":
            return ScriptedModelClient(
                [intent("unsupported", "REJECTED", "REJECT", {}, [])]
            )
        return scripts(execution)

    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    result = run_evaluation(dataset, RunConfig(run_mode="framework_self_test"), factory)
    case = result.cases[0]
    assert case.execution_status == "COMPLETED"
    assert case.quality_conclusion == "FAIL"
    assert case.first_failed_assertion.name == "intent_match"
    assert case.diagnoses[0].code == "INTENT_MISMATCH"


def test_agent_exception_does_not_stop_later_case(dataset_path):
    class BrokenClient:
        def classify_intent(self, user_input):
            raise RuntimeError("fixture interruption")

        def next_tool_step(self, request):
            raise AssertionError

    calls = 0

    def factory(execution):
        nonlocal calls
        calls += 1
        return BrokenClient() if calls == 1 else scripts(execution)

    dataset = load_dataset(dataset_path)
    dataset.cases = [
        dataset.cases[0],
        dataset.cases[0].model_copy(update={"case_id": "MODULE-2"}),
    ]
    result = run_evaluation(dataset, RunConfig(run_mode="framework_self_test"), factory)
    assert result.cases[0].execution_status == "MODEL_INVOCATION_ERROR"
    assert result.cases[1].execution_status == "COMPLETED"


def test_invalid_model_output_keeps_partial_trace_and_diagnostic(dataset_path):
    class InvalidClient:
        def classify_intent(self, user_input):
            raise InvalidModelOutputError(
                "invalid fixture",
                diagnostic={"raw_output_redacted": "{bad}", "schema_version": "v1"},
            )

        def next_tool_step(self, request):
            raise AssertionError

    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    result = run_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test"),
        lambda execution: InvalidClient(),
    )

    case = result.cases[0]
    assert case.execution_status == "MODEL_OUTPUT_ERROR"
    assert case.trace_events[0]["event_type"] == "intent_requested"
    assert case.exception["diagnostic"]["raw_output_redacted"] == "{bad}"
    assert "query_information" in result.summary.by_expected_intent
    assert "unknown" in result.summary.by_actual_intent


def test_non_frozen_benchmark_requires_explicit_override(dataset_path):
    dataset = load_dataset(dataset_path)
    dataset.lifecycle_state = "VALIDATED"

    try:
        run_evaluation(dataset, RunConfig(run_mode="agent_benchmark"), scripts)
    except ValueError as exc:
        assert "FROZEN" in str(exc)
    else:
        raise AssertionError("non-frozen benchmark should require explicit override")

    result = run_evaluation(
        dataset,
        RunConfig(run_mode="agent_benchmark", allow_non_frozen_dataset=True),
        scripts,
    )
    assert result.dataset_lifecycle_state == "VALIDATED"


def test_core_behavior_rate_treats_protocol_naming_as_separate(dataset_path):
    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    dataset.lifecycle_state = "FROZEN"
    dataset.cases[0].oracle.expected_module_output.update(
        {
            "status": "NEED_CLARIFICATION",
            "next_action": "ASK_USER",
            "parameters": {},
        }
    )
    dataset.cases[0].oracle.expected_module_output["missing_parameters"] = [
        "query_condition"
    ]

    def named_differently(execution):
        return ScriptedModelClient(
            [
                intent(
                    status="NEED_CLARIFICATION",
                    action="ASK_USER",
                    parameters={},
                    missing=["user_id"],
                )
            ]
        )

    result = run_evaluation(
        dataset,
        RunConfig(run_mode="agent_benchmark"),
        named_differently,
    )

    assert result.summary.strict_assertion_pass_rate == 0.0
    assert result.summary.core_behavior_match_rate == 100.0
    assert result.cases[0].diagnoses[0].code == "PROTOCOL_NAMING_MISMATCH"


def test_initialization_error_does_not_stop_later_case(dataset_path):
    calls = 0

    def factory(execution):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("initialization fixture")
        return scripts(execution)

    dataset = load_dataset(dataset_path)
    dataset.cases = [
        dataset.cases[0],
        dataset.cases[0].model_copy(update={"case_id": "MODULE-2"}),
    ]
    result = run_evaluation(dataset, RunConfig(run_mode="framework_self_test"), factory)
    assert result.cases[0].execution_status == "INITIALIZATION_ERROR"
    assert result.cases[1].execution_status == "COMPLETED"


def test_elapsed_budget_is_reported_as_outer_timeout(dataset_path):
    class SlowClient:
        def classify_intent(self, user_input):
            time.sleep(0.01)
            return intent()

        def next_tool_step(self, request):
            raise AssertionError

    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    dataset.cases[0].execution.timeout_seconds = 0.001
    result = run_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test"),
        lambda execution: SlowClient(),
    )
    assert result.cases[0].execution_status == "OUTER_TIMEOUT"
    assert result.cases[0].quality_conclusion == "INCONCLUSIVE"


def test_assertion_failure_invalidates_evaluation_not_agent(dataset_path, monkeypatch):
    import eval_framework.evaluation_policy as policy

    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]

    def broken_assertions(case, output, capabilities):
        raise RuntimeError("assertion fixture")

    monkeypatch.setattr(policy, "run_assertions", broken_assertions)
    result = run_evaluation(dataset, RunConfig(run_mode="framework_self_test"), scripts)
    assert result.cases[0].execution_status == "COMPLETED"
    assert result.cases[0].evaluation_validity == "INVALID"
    assert result.cases[0].score is None
    assert any(
        issue["code"] == "ASSERTION_EVALUATION_FAILED"
        for issue in result.cases[0].evaluation_issues
    )


def test_weight_rounding_threshold_critical_and_no_applicable():
    def item(weight, passed, critical=False):
        return AssertionResult(
            name="x",
            weight=weight,
            critical=critical,
            passed=passed,
        )

    assert score_assertions([item(1, True), item(2, False)], 30) == (33.33, "PASS")
    assert score_assertions([item(99, True), item(1, False, True)], 50) == (
        99.0,
        "FAIL",
    )
    assert score_assertions([], 100) == (None, "INCONCLUSIVE")
