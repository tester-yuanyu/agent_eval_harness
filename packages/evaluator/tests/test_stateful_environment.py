import sqlite3
from pathlib import Path

import pytest
from conftest import intent
from support.model_client import DeterministicModelClient

from eval_framework.mini_agent_adapter import MiniAgentAdapter
from eval_framework.runtime_factory import RuntimeFactory
from eval_framework.schemas import ExecutionSpec

ARGS = {
    "gift_id": 300101,
    "gift_ids": None,
    "gift_nums": None,
    "user_id": 10001,
    "user_ids": None,
    "num": 2,
    "duration_days": 7,
}


def environment_factory(allowed):
    from eval_framework.providers.mini_agent.state_environment import (
        GiftSQLiteEnvironment,
    )

    return GiftSQLiteEnvironment(allowed)


def script():
    return [
        intent("add_backpack_gift", "NEED_CLARIFICATION", "ASK_USER", {}, ["user_id"]),
        intent(
            "add_backpack_gift",
            "NEED_CONFIRMATION",
            "ASK_CONFIRMATION",
            {**ARGS, "environment": "qa"},
        ),
        # Deliberately faulty routing: the model uses a read intent to invoke a write.
        # This probes actual state capture, not native confirmation acceptance.
        intent(),
        {
            "type": "function_call",
            "call_id": "grant",
            "name": "add_gift_to_backpack",
            "arguments": ARGS,
        },
        {"type": "message", "content": "granted"},
    ]


def execution():
    return ExecutionSpec(
        user_input="grant gift",
        user_responses=["user 10001", "confirm"],
        tool_profile="gift",
        allowed_tools=["add_gift_to_backpack"],
    )


def test_real_sqlite_state_is_captured_each_turn_and_isolated_between_trials():
    factory = RuntimeFactory(
        lambda _: DeterministicModelClient(script()),
        environment_factory=environment_factory,
    )
    runtimes = [
        factory.create(
            execution(),
            session_id=f"s{i}",
            allowed_tools=frozenset({"add_gift_to_backpack"}),
        )
        for i in range(2)
    ]
    try:
        assert (
            runtimes[0].environment.database_path
            != runtimes[1].environment.database_path
        )
        for runtime in runtimes:
            output = MiniAgentAdapter(runtime).run_full(execution(), "end_to_end")
            assert output.before_snapshot["grant_count"] == 0
            assert [s["grant_count"] for s in output.turn_snapshots] == [0, 0, 1]
            assert output.snapshot["total_quantity"] == 2
            with sqlite3.connect(runtime.environment.database_path) as connection:
                assert connection.execute("SELECT num FROM grants").fetchall() == [(2,)]
            assert not any(
                e["event_type"] == "confirmation_accepted"
                for turn in output.turns
                for e in turn["events"]
            )
    finally:
        paths = [r.environment.database_path for r in runtimes]
        for runtime in runtimes:
            runtime.cleanup()
    assert all(not path.exists() for path in paths)


def test_duplicate_tool_invocations_remain_visible_in_state():
    env = environment_factory(frozenset({"add_gift_to_backpack"}))
    try:
        env.registry.invoke("add_gift_to_backpack", ARGS)
        env.registry.invoke("add_gift_to_backpack", ARGS)
        assert env.snapshot()["grant_count"] == 2
        assert env.snapshot()["total_quantity"] == 4
    finally:
        env.cleanup()


def test_initialization_failure_cleans_up_created_environment():
    created = []

    def create(allowed):
        env = environment_factory(allowed)
        created.append(env)
        return env

    def broken(_):
        raise RuntimeError("client failed")

    factory = RuntimeFactory(broken, environment_factory=create)
    with pytest.raises(RuntimeError, match="client failed"):
        factory.create(execution(), session_id="s", allowed_tools=frozenset())
    assert len(created) == 1
    assert not created[0].database_path.exists()


def test_later_turn_exception_retains_prior_turns_and_observed_state():
    responses = script()[:2] + [RuntimeError("model crashed")]
    runtime = RuntimeFactory(
        lambda _: DeterministicModelClient(responses),
        environment_factory=environment_factory,
    ).create(
        execution(),
        session_id="s",
        allowed_tools=frozenset({"add_gift_to_backpack"}),
    )
    try:
        with pytest.raises(Exception) as caught:
            MiniAgentAdapter(runtime).run_full(execution(), "end_to_end")
        output = caught.value.adapter_output
        assert len(output.turns) == 2
        assert output.before_snapshot["grant_count"] == 0
        assert len(output.turn_snapshots) == 2
        assert output.snapshot["grant_count"] == 0
        assert output.execution_completed is False
    finally:
        runtime.cleanup()


def test_environment_rejects_unimplemented_tools_before_allocating_state():
    with pytest.raises(ValueError, match="unsupported"):
        environment_factory(frozenset({"invented_tool"}))


def gift_dataset(tmp_path):
    from conftest import assertion, e2e_case
    from minimal_agent import build_default_intent_registry
    from minimal_agent.capabilities import export_capability_bundle

    from eval_framework.providers.mini_agent.capability_adapter import (
        load_mini_agent_capability_bundle,
    )
    from eval_framework.schemas import DatasetBundle, EvalCase, ExecutionProfile

    env = environment_factory(frozenset({"add_gift_to_backpack"}))
    root = tmp_path / "bundle"
    try:
        export_capability_bundle(root, build_default_intent_registry(), env.registry)
    finally:
        env.cleanup()
    bundle = load_mini_agent_capability_bundle(root)
    raw = e2e_case()
    raw["execution"] = execution().model_dump()
    raw["oracle"]["goal_state"] = {"grant_count": 1, "total_quantity": 2}
    raw["oracle"]["evaluation"]["checks"] = [
        assertion("final_state_match", critical=True),
        assertion(
            "turns_match",
            critical=True,
            config={
                "turns": [
                    {
                        "status": "NEED_CLARIFICATION",
                        "tool_calls": [],
                        "state": {"grant_count": 0},
                    },
                    {
                        "status": "NEED_CONFIRMATION",
                        "tool_calls": [],
                        "state": {"grant_count": 0},
                    },
                    {"status": "SUCCESS", "state": {"grant_count": 1}},
                ]
            },
        ),
    ]
    return DatasetBundle(
        path="gift-fixture",
        sha256="fixture",
        schema_versions=["1.0"],
        dataset_version="gift-test-v1",
        lifecycle_state="FROZEN",
        provider_id="mini_agent",
        capability_bundle_path=str(root),
        capability_bundle_sha256=bundle.capability_bundle_sha256,
        execution_profiles={
            "gift": ExecutionProfile(allowed_tools=["add_gift_to_backpack"])
        },
        execution_profiles_source="manifest",
        total_count=1,
        cases=[EvalCase.model_validate(raw)],
    )


def test_native_confirmation_gap_produces_failed_state_verdict_and_saved_evidence(
    tmp_path,
):
    from eval_framework.providers.mini_agent.provider import MiniAgentProvider
    from eval_framework.reporting import write_report
    from eval_framework.runner import run_provider_evaluation
    from eval_framework.schemas import RunConfig

    dataset = gift_dataset(tmp_path)
    responses = script()[:2] + [
        intent("add_backpack_gift", parameters={**ARGS, "environment": "qa"})
    ]
    provider = MiniAgentProvider.from_dataset(
        dataset,
        lambda _: DeterministicModelClient(responses),
        environment="gift_sqlite_v1",
    )
    result = run_provider_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test", trials_per_case=2),
        provider,
        output_dir=tmp_path / "runs",
    )
    for case in result.cases:
        assert case.execution_status == "COMPLETED"
        assert case.quality_conclusion == "FAIL"
        assert case.evaluation_validity == "VALID"
        assert case.before_snapshot["grant_count"] == 0
        assert case.system_snapshot["grant_count"] == 0
        assert case.turn_results[-1]["status"] == "NEED_CONFIRMATION"
        assert case.cleanup_status == "CLEANED"
    assert result.cases[0].session_id != result.cases[1].session_id
    paths = write_report(result, tmp_path / "reports", provider.capabilities)
    from eval_framework.result_loader import load_run_result

    saved = load_run_result(paths.output_dir).result
    assert saved.cases[0].before_snapshot["grant_count"] == 0
    assert saved.cases[0].turn_snapshots[-1]["grant_count"] == 0


def test_provider_preflight_requires_explicit_state_environment_and_valid_boundary(
    tmp_path,
):
    from eval_framework.providers.mini_agent.provider import MiniAgentProviderFactory

    dataset = gift_dataset(tmp_path)
    factory = MiniAgentProviderFactory()
    assert not factory.validate_dataset(dataset).valid
    assert factory.validate_dataset(dataset, environment="gift_sqlite_v1").valid
    dataset.cases[0].test_scope = "link"
    validation = factory.validate_dataset(dataset, environment="gift_sqlite_v1")
    assert any(
        "link" in issue.message and "user_responses" in issue.message
        for issue in validation.issues
    )


def test_state_read_failure_is_evaluator_error_and_preserves_cleanup(
    tmp_path, monkeypatch
):
    from eval_framework.providers.mini_agent.provider import MiniAgentProvider
    from eval_framework.providers.mini_agent.state_environment import (
        GiftSQLiteEnvironment,
    )
    from eval_framework.runner import run_provider_evaluation
    from eval_framework.schemas import RunConfig

    dataset = gift_dataset(tmp_path)
    provider = MiniAgentProvider.from_dataset(
        dataset,
        lambda _: DeterministicModelClient(script()),
        environment="gift_sqlite_v1",
    )

    def broken_snapshot(self):
        raise OSError("state reader unavailable")

    monkeypatch.setattr(GiftSQLiteEnvironment, "snapshot", broken_snapshot)
    result = run_provider_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test"),
        provider,
        output_dir=tmp_path / "runs",
    )
    case = result.cases[0]
    assert case.execution_status == "EVALUATOR_ERROR"
    assert case.evaluation_validity == "INVALID"
    assert case.score is None
    assert case.quality_conclusion == "INCONCLUSIVE"
    assert case.cleanup_status == "CLEANED"


def test_state_environment_rejects_a_different_frozen_tool_implementation(tmp_path):
    from eval_framework.capabilities import CapabilityRegistry
    from eval_framework.errors import EvaluationPreflightError
    from eval_framework.providers.mini_agent.capability_adapter import (
        load_mini_agent_capability_bundle,
    )
    from eval_framework.providers.mini_agent.provider import MiniAgentProvider

    dataset = gift_dataset(tmp_path)
    bundle = load_mini_agent_capability_bundle(Path(dataset.capability_bundle_path))
    documents = tuple(
        document.model_copy(update={"contract_version": "different-handler-v1"})
        if document.snapshot_id == "tool.add_gift_to_backpack"
        else document
        for document in bundle.documents
    )
    registry = CapabilityRegistry(bundle.model_copy(update={"documents": documents}))
    with pytest.raises(EvaluationPreflightError) as caught:
        MiniAgentProvider(
            registry,
            lambda _: DeterministicModelClient([]),
            execution_profiles=dataset.execution_profiles,
            current_capabilities=registry,
            environment="gift_sqlite_v1",
        )
    assert caught.value.code == "ENVIRONMENT_CONTRACT_MISMATCH"
