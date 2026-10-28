from __future__ import annotations

from pathlib import Path

import pytest
from minimal_agent.capabilities import export_capability_bundle
from minimal_agent.contracts.intents import build_default_intent_registry
from minimal_agent.contracts.tools import ToolResult
from minimal_agent.runtime import ToolRegistry
from minimal_agent.testing import query_user_evaluation_definition

from eval_framework.capabilities import CapabilityRegistry
from eval_framework.dataset_loader import load_dataset
from eval_framework.errors import EvaluationPreflightError
from eval_framework.providers.mini_agent.capability_adapter import (
    load_mini_agent_capability_bundle,
)
from eval_framework.providers.mini_agent.provider import MiniAgentProvider
from eval_framework.providers.mini_agent.runtime_binding import (
    MiniAgentRuntimeBindingFactory,
)
from eval_framework.schemas import ExecutionProfile, ExecutionSpec


def _handler(**arguments) -> ToolResult:
    return ToolResult(
        success=True,
        code="EMPTY",
        message="no matching fixture",
        data={"query": arguments},
    )


def _exported_registry(tmp_path: Path) -> CapabilityRegistry:
    registry = ToolRegistry()
    registry.register(query_user_evaluation_definition(_handler))
    root = tmp_path / "frozen"
    export_capability_bundle(root, build_default_intent_registry(), registry)
    return CapabilityRegistry(load_mini_agent_capability_bundle(root))


def test_query_user_runtime_export_uses_injected_registry_object(
    tmp_path: Path, monkeypatch
) -> None:
    frozen = _exported_registry(tmp_path)
    observed: list[ToolRegistry] = []
    real_export = export_capability_bundle

    def recording_export(output_root, intent_registry, tool_registry):
        observed.append(tool_registry)
        return real_export(output_root, intent_registry, tool_registry)

    monkeypatch.setattr(
        "eval_framework.providers.mini_agent.runtime_binding.export_capability_bundle",
        recording_export,
    )
    factory = MiniAgentRuntimeBindingFactory(
        frozen,
        query_user_handler_factory=lambda: _handler,
    )

    registry = factory(frozenset({"query_user_info"}))

    assert observed == [registry]
    arguments = {
        "user_id": 7,
        "room_id": None,
        "email": None,
        "phone": None,
    }
    result = registry.invoke("query_user_info", arguments)
    assert result.code == "EMPTY"
    assert result.data == {"query": arguments}


def test_runtime_registry_is_isolated_per_trial(tmp_path: Path) -> None:
    factory = MiniAgentRuntimeBindingFactory(
        _exported_registry(tmp_path),
        query_user_handler_factory=lambda: _handler,
    )

    first = factory(frozenset({"query_user_info"}))
    second = factory(frozenset({"query_user_info"}))

    assert first is not second


def test_zero_tool_runtime_exports_empty_registry(tmp_path: Path) -> None:
    root = (
        Path(__file__).resolve().parents[1]
        / "datasets/mini_agent/capability_bundles"
        / "99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8"
    )
    frozen = CapabilityRegistry(load_mini_agent_capability_bundle(root))
    factory = MiniAgentRuntimeBindingFactory(frozen)

    registry = factory(frozenset())

    assert registry.definitions == ()


def test_runtime_projection_does_not_hide_missing_non_tool_contract(
    tmp_path: Path, monkeypatch
) -> None:
    frozen = _exported_registry(tmp_path)
    current = frozen.bundle.model_copy(
        update={
            "documents": tuple(
                document
                for document in frozen.bundle.documents
                if document.snapshot_id != "intent.query_user"
            )
        }
    )
    monkeypatch.setattr(
        "eval_framework.providers.mini_agent.runtime_binding."
        "load_mini_agent_capability_bundle",
        lambda root: current,
    )
    factory = MiniAgentRuntimeBindingFactory(frozen)

    with pytest.raises(
        EvaluationPreflightError,
        match="capability snapshot IDs differ",
    ):
        factory(frozenset())


def test_provider_builds_query_user_runtime_from_matching_tool_bundle(
    tmp_path: Path,
) -> None:
    frozen = _exported_registry(tmp_path)
    dataset_path = (
        Path(__file__).resolve().parents[1]
        / "datasets/mini_agent/module_query_user_intent_v2_0.jsonl"
    )
    dataset = load_dataset(dataset_path).model_copy(
        update={
            "capability_bundle_path": frozen.bundle.root,
            "capability_bundle_sha256": frozen.bundle.capability_bundle_sha256,
            "execution_profiles": {
                "full": ExecutionProfile(allowed_tools=["query_user_info"]),
                "module": ExecutionProfile(allowed_tools=[]),
            },
        },
        deep=True,
    )
    provider = MiniAgentProvider.from_dataset(dataset, lambda execution: object())

    runtime = provider.create_runtime(
        ExecutionSpec(
            user_input="query user 7",
            tool_profile="full",
            allowed_tools=["query_user_info"],
        ),
        session_id="session-1",
        scope="end_to_end",
    )

    assert [item.name for item in runtime.registry.definitions] == [
        "query_user_info"
    ]

    module_runtime = provider.create_runtime(
        ExecutionSpec(user_input="query user 7", tool_profile="module"),
        session_id="session-2",
        scope="module",
    )
    assert module_runtime.registry.definitions == ()
