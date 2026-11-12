from collections import Counter
from copy import deepcopy

from .test_agent_readiness import ROOT, request_fixture


def test_v4_projection_and_oracle_isolation():
    from eval_framework.benchmark.full_benchmark import public_task, tasks_for

    request = request_fixture()
    tasks = tasks_for(request)
    assert len(tasks) == 365
    assert Counter(t["execution_mode"] for t in tasks) == {"agent": 76, "module": 289}
    case = next(t for t in tasks if t["execution_mode"] == "agent")
    other = deepcopy(case)
    other["case"]["payload"]["oracle"] = {"private": "NEVER_SEND"}
    assert public_task(case, request) == public_task(other, request)
    assert "NEVER_SEND" not in str(public_task(other, request))


def test_real_model_is_injected_not_replaced_with_reference_candidate():
    from eval_contracts.agent_readiness import agent_plan_for, reference_context

    from eval_framework.benchmark.agent_readiness import (
        AgentReferenceExecutor,
        ReferenceModel,
    )

    request = request_fixture()
    case = next(
        c for c in request.cases if c.case_id.startswith("I-intent.query_user.")
    )
    plan = agent_plan_for(case, request)
    model = ReferenceModel(
        plan.model_copy(
            update={
                "candidate": {
                    "intent": "unsupported",
                    "status": "READY",
                    "next_action": "CALL_TOOL",
                    "parameters": {},
                    "missing_parameters": [],
                    "reason": "test",
                }
            }
        )
    )
    executor = AgentReferenceExecutor(
        reference_context(request), ROOT / "examples/mini_agent"
    )
    row = executor.execute(case.case_id, plan, model=model)
    assert row.observations["module_output"]["intent"] == "unsupported"
    assert row.observations["execution_kind"] == "real_model_agent"


def test_live_rules_reuse_frozen_oracle_and_detect_bad_intent():
    from eval_contracts.agent_readiness import agent_plan_for

    from eval_framework.benchmark.agent_readiness import ReferenceModel
    from eval_framework.benchmark.full_benchmark import (
        live_checks,
        public_task,
        tasks_for,
    )
    from eval_framework.benchmark.full_worker import execute_public

    request = request_fixture()
    task = next(
        t
        for t in tasks_for(request)
        if t["category"] == "intent_module" and t["target"] == "intent_router"
    )
    case = next(c for c in request.cases if c.case_id == task["id"])
    plan = agent_plan_for(case, request)
    model = ReferenceModel(
        plan.model_copy(
            update={
                "candidate": {
                    "intent": "unsupported",
                    "status": "READY",
                    "next_action": "CALL_TOOL",
                    "parameters": {},
                    "missing_parameters": [],
                    "reason": "test",
                }
            }
        )
    )
    from eval_contracts.full_readiness import ToolEvidence

    row = ToolEvidence.model_validate(
        execute_public(
            public_task(task, request), ROOT / "examples/mini_agent", None, model
        )
    )
    checks = live_checks(case, plan, row, request)
    assert checks["execution_complete"]
    assert not all(checks.values())


def test_deterministic_worker_never_calls_model():
    from eval_framework.benchmark.full_benchmark import public_task, tasks_for
    from eval_framework.benchmark.full_worker import execute_public

    request = request_fixture()

    class Forbidden:
        def classify_intent(self, *args):
            raise AssertionError("model must not be called")

    for category in ("schema_validation", "tool_behavior", "module_event"):
        task = next(t for t in tasks_for(request) if t["category"] == category)
        row = execute_public(
            public_task(task, request), ROOT / "examples/mini_agent", None, Forbidden()
        )
        assert row["evidence_complete"], row


def test_mixed_formal_rules_execute_all_original_definitions_without_network():
    from eval_contracts.agent_readiness import binding_for

    from eval_framework.benchmark.agent_readiness import ReferenceModel
    from eval_framework.benchmark.full_benchmark import (
        FullBenchmarkDomain,
        public_task,
        tasks_for,
    )
    from eval_framework.benchmark.full_worker import execute_public

    request = request_fixture()
    domain = FullBenchmarkDomain.__new__(FullBenchmarkDomain)
    domain.request = request
    verdicts = Counter()
    for task in tasks_for(request):
        plan = binding_for(
            next(c for c in request.cases if c.case_id == task["id"]), request
        )
        row = execute_public(
            public_task(task, request),
            ROOT / "examples/mini_agent",
            None,
            ReferenceModel(plan) if task["live"] else None,
        )
        assessment = domain.score_task(
            task,
            dict(
                status=row["status"],
                evidence_complete=row["evidence_complete"],
                row=row,
            ),
        )
        verdicts[assessment["verdict"]] += 1
    assert verdicts == {"PASS": 362, "FAIL": 3}, verdicts


def test_geval_marks_deterministic_cases_not_applicable_without_client(monkeypatch):
    from eval_framework.benchmark.scorers import trajectory_judge

    def forbidden(*args, **kwargs):
        raise AssertionError("No paid judge for deterministic checks")

    monkeypatch.setattr(trajectory_judge, "_AuditedJudge", forbidden)
    metrics = trajectory_judge.judge_observation(
        {"id": "schema", "prompt": "schema"},
        {"events": [], "execution_kind": "deterministic_reference_not_agent"},
        {
            "dimensions": [
                "action_appropriateness",
                "recovery_appropriateness",
                "response_groundedness",
            ]
        },
    )
    assert len(metrics) == 3
    assert all(m["status"] == "NOT_APPLICABLE" for m in metrics)


def test_geval_projection_has_same_turn_state_and_no_future_tool_leakage():
    from eval_framework.benchmark.full_adapter import order_events
    from eval_framework.benchmark.scorers.trajectory_judge import _candidates

    events = [
        dict(
            id="turn",
            type="turn",
            start_time="2026-01-01T00:00:00Z",
            end_time="2026-01-01T00:00:04Z",
            output={"status": "SUCCESS"},
            input={"user_input": "query"},
        ),
        dict(
            id="tool",
            type="tool",
            parent_id="turn",
            start_time="2026-01-01T00:00:02Z",
            end_time="2026-01-01T00:00:03Z",
            input={},
            output={"secret_future": "record"},
            name="query",
        ),
        dict(
            id="generation",
            type="generation",
            parent_id="turn",
            start_time="2026-01-01T00:00:01Z",
            end_time="2026-01-01T00:00:02Z",
            input="query",
            output="call query",
        ),
    ]
    ordered = order_events(events, dict(after_state={"users": {}}, observations={}))
    candidates = _candidates(
        {"id": "test", "prompt": "query"},
        {"events": ordered, "turns": []},
        ["action_appropriateness", "response_groundedness"],
    )
    action = next(e for r, e in candidates if r["name"] == "action_appropriateness")
    assert "secret_future" not in str(action)
    response = next(e for r, e in candidates if r["name"] == "response_groundedness")
    assert response["context"]["turn_snapshot"] == {"users": {}}


def test_scoring_identity_binds_existing_assertion_implementations():
    from eval_framework.benchmark.full_benchmark import FullBenchmarkDomain

    domain = FullBenchmarkDomain.__new__(FullBenchmarkDomain)
    identity = domain.identity()
    assert {"../assertions.py", "../native_scoring.py", "../turn_assertions.py"} <= set(
        identity["rule_sources"]
    )


def test_cancellation_retains_model_evidence_and_usage(monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace

    from inspect_ai import log, util

    from eval_framework.benchmark import full_adapter

    class Env:
        count = 0

        async def exec(self, *args, **kwargs):
            self.count += 1
            if self.count == 1:
                return SimpleNamespace(success=True, stdout="{}")
            raise asyncio.CancelledError()

    monkeypatch.setattr(util, "sandbox", lambda: Env())
    monkeypatch.setattr(log, "transcript", lambda: SimpleNamespace(events=[]))
    monkeypatch.setattr(full_adapter, "bind_docker_environment", lambda *args: {})

    async def evidence(*args):
        return [
            dict(
                id="generation",
                type="generation",
                usage={"input_tokens": 4, "output_tokens": 2},
                incomplete=True,
            )
        ]

    monkeypatch.setattr(full_adapter, "model_evidence", evidence)
    adapter = full_adapter.FullBenchmarkAdapter.__new__(
        full_adapter.FullBenchmarkAdapter
    )
    adapter.output = tmp_path
    monkeypatch.setattr(adapter, "runtime_identity", lambda mode: dict(mode=mode))
    with __import__("pytest").raises(asyncio.CancelledError) as caught:
        asyncio.run(
            adapter.execute(
                {"case_id": "cancel-case", "live": False},
                mode="module",
                config={"_inspect_docker_compose": "test"},
            )
        )
    assert caught.value.benchmark_observation["events"][0]["id"] == "generation"
