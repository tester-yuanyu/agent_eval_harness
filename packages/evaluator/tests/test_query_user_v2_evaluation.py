from __future__ import annotations

import ast
import hashlib
import json
from collections import deque
from pathlib import Path
from types import SimpleNamespace

from minimal_agent.contracts.agent import AgentResult, IntentResult, ToolCallRecord
from support.model_client import DeterministicModelClient

from eval_framework.cli import main
from eval_framework.dataset_loader import load_dataset
from eval_framework.mini_agent_adapter import MiniAgentAdapter
from eval_framework.providers.mini_agent import MiniAgentProvider
from eval_framework.runner import run_provider_evaluation
from eval_framework.schemas import ExecutionSpec, RunConfig

DATASET_SHA256 = "e0c74a6bae2889c8d71709d17085bdba97322eb53a4615629b78fbffc3b1b2ac"
BUNDLE_SHA256 = "99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _dataset_path() -> Path:
    return _project_root() / "datasets/mini_agent/module_query_user_intent_v2_0.jsonl"


def test_query_user_v2_frozen_inputs_are_pinned() -> None:
    dataset_path = _dataset_path()
    manifest_path = dataset_path.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert hashlib.sha256(dataset_path.read_bytes()).hexdigest() == DATASET_SHA256
    assert manifest["state"] == "FROZEN"
    assert manifest["case_count"] == 42
    assert manifest["dataset_sha256"] == DATASET_SHA256
    assert manifest["capability_bundle"]["sha256"] == BUNDLE_SHA256
    assert manifest["capability_bundle"]["path"] == (
        f"capability_bundles/{BUNDLE_SHA256}"
    )
    assert "capabilities-v3" not in manifest["capability_bundle"]["path"]
    bundle_root = dataset_path.parent / manifest["capability_bundle"]["path"]
    assert (bundle_root / "agent.json").is_file()

    dataset = load_dataset(dataset_path)
    assert len(dataset.cases) == dataset.total_count == 42
    assert {case.test_scope for case in dataset.cases} == {"module"}
    assert {case.target for case in dataset.cases} == {"intent_router"}


def test_evaluator_never_imports_versioned_mini_agent_capabilities() -> None:
    source_root = _project_root() / "src/eval_framework"
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        assert "minimal_agent.capabilities.v3" not in imported, path


class _BridgeAgent:
    def __init__(self) -> None:
        self.intent_inputs: list[str] = []
        self.run_inputs: list[tuple[str, str | None, frozenset[str] | None]] = []

    def run_intent_only(self, user_input: str) -> IntentResult:
        self.intent_inputs.append(user_input)
        return IntentResult(
            intent="query_user",
            status="READY",
            next_action="CALL_TOOL",
            parameters={"user_id": 7},
            missing_parameters=[],
            reason="ready",
        )

    def intent_trace_snapshot(self) -> list[dict[str, object]]:
        return [{"event_type": "intent_decided"}]

    def run(
        self,
        user_input: str,
        *,
        session_id: str | None,
        allowed_tools: frozenset[str] | None,
    ) -> AgentResult:
        self.run_inputs.append((user_input, session_id, allowed_tools))
        return AgentResult(
            run_id="run-1",
            status="SUCCESS",
            intent_result=self.run_intent_only(user_input),
            tool_calls=[
                ToolCallRecord(
                    call_id="call-1",
                    name="query_user_info",
                    arguments={"user_id": 7},
                    status="SUCCESS",
                    output={"code": "EMPTY"},
                    error=None,
                    duration_ms=1,
                )
            ],
            final_response="done",
            events=[{"event_type": "tool_succeeded"}],
        )


def test_existing_adapter_bridges_public_result_protocols() -> None:
    agent = _BridgeAgent()
    adapter = MiniAgentAdapter(
        SimpleNamespace(agent=agent, session_id="session-1")  # type: ignore[arg-type]
    )
    execution = ExecutionSpec(
        user_input="query user 7",
        tool_profile="full",
        allowed_tools=["query_user_info"],
    )

    module = adapter.run_module(execution)
    full = adapter.run_full(execution, "end_to_end")

    assert module.module_output == {
        "intent": "query_user",
        "status": "READY",
        "next_action": "CALL_TOOL",
        "parameters": {"user_id": 7},
        "missing_parameters": [],
        "reason": "ready",
    }
    assert module.trace_events == [{"event_type": "intent_decided"}]
    assert full.turns[0]["tool_calls"][0]["name"] == "query_user_info"
    assert full.turns[0]["events"] == [{"event_type": "tool_succeeded"}]
    assert full.turns[0]["final_response"] == "done"
    assert agent.run_inputs == [
        ("query user 7", "session-1", frozenset({"query_user_info"}))
    ]


def test_frozen_query_user_v2_dataset_validates(capsys) -> None:
    code = main(
        [
            "validate",
            "--dataset",
            str(_dataset_path()),
            "--provider",
            "mini_agent",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["valid"] is True


def test_frozen_query_user_v2_replays_all_cases_offline() -> None:
    dataset = load_dataset(_dataset_path())
    pending = deque(dataset.cases)

    def model_client_factory(execution: ExecutionSpec) -> DeterministicModelClient:
        case = pending.popleft()
        assert execution.user_input == case.execution.user_input
        return DeterministicModelClient([case.oracle.expected_module_output])

    provider = MiniAgentProvider.from_dataset(dataset, model_client_factory)
    result = run_provider_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test"),
        provider,
    )

    assert pending == deque()
    assert len(result.cases) == 42
    assert {case.execution_status for case in result.cases} == {"COMPLETED"}
    assert {case.quality_conclusion for case in result.cases} == {"PASS"}
    assert {case.score for case in result.cases} == {100.0}
