from __future__ import annotations

import ast
import json
from collections import Counter, deque
from copy import deepcopy
from pathlib import Path

import pytest
from support.model_client import DeterministicModelClient

from eval_framework import EvaluationRunResult, RunConfig, load_dataset
from eval_framework.capabilities import (
    CapabilityBundle,
    CapabilityRegistry,
)
from eval_framework.diagnostics import DiagnosticRegistry
from eval_framework.provider import (
    AdapterOutput,
    EvaluationPreflightError,
    ProviderExceptionInfo,
    ensure_capability_compatibility,
)
from eval_framework.provider_registry import ProviderRegistry
from eval_framework.providers.mini_agent import MiniAgentProvider
from eval_framework.runner import run_provider_evaluation
from eval_framework.runtime_factory import RuntimeFactory
from eval_framework.schemas import ExecutionProfile, ExecutionSpec
from eval_framework.tool_catalog import ToolCatalog

FIXTURE_PROFILES = {
    "legacy": frozenset({"query_information", "prepare_resource"}),
    "shadow_read": frozenset(
        {"query_user_info", "query_gift_info", "query_pool_config"}
    ),
    "shadow_full": frozenset(
        {
            "query_user_info",
            "query_gift_info",
            "query_pool_config",
            "add_gift_to_backpack",
        }
    ),
}


class FakeProvider:
    provider_id = "mini_agent"
    provider_version = "fixture-v1"
    diagnostics = DiagnosticRegistry()

    def __init__(self, capabilities):
        self.capabilities = capabilities
        self.tools = ToolCatalog.from_registry(
            capabilities,
            profiles={
                name: ExecutionProfile(allowed_tools=sorted(tools))
                for name, tools in FIXTURE_PROFILES.items()
            },
        )

    def create_runtime(self, execution, session_id, scope):
        return {"session_id": session_id}

    def run_module(self, runtime, execution):
        return AdapterOutput(
            module_output={
                "intent": "query_information",
                "status": "READY",
                "next_action": "CALL_TOOL",
                "parameters": {"resource_type": "fixture", "environment": "test"},
                "missing_parameters": [],
                "reason": "fixture",
            },
            turns=[],
            before_snapshot=None,
            turn_snapshots=[],
            snapshot=None,
            trace_events=[],
        )

    def run_full(self, runtime, execution, scope):
        raise AssertionError("module-only fixture")

    def cleanup(self, runtime):
        runtime["cleaned"] = True

    def classify_exception(self, exc):
        return ProviderExceptionInfo(
            execution_status="AGENT_EXCEPTION",
            exception={"type": type(exc).__name__, "message": str(exc)},
        )

    def runtime_metadata(self, runtime):
        return {"client_type": "FakeProvider"}

    def tool_version(self, runtime):
        return "fixture-tools-v1"


class FakeProviderFactory:
    def __init__(self, provider_id="mini_agent"):
        self.calls = []
        self.provider_id = provider_id

    def create(self, dataset, model_client_factory, **kwargs):
        self.calls.append((dataset, model_client_factory, kwargs))
        registry = CapabilityRegistry(
            CapabilityBundle.load(Path(dataset.capability_bundle_path))
        )
        provider = FakeProvider(registry)
        provider.provider_id = self.provider_id
        return provider


def test_provider_registry_registers_second_provider_without_core_changes(
    dataset_path,
):
    dataset = load_dataset(dataset_path).model_copy(update={"provider_id": "fixture"})
    factory = FakeProviderFactory("fixture")
    registry = ProviderRegistry()
    registry.register("fixture", factory)

    provider = registry.create(
        "fixture",
        dataset=dataset,
        model_client_factory=lambda execution: None,
        verify_current=False,
    )

    assert isinstance(provider, FakeProvider)
    assert len(factory.calls) == 1


def test_provider_registry_rejects_dataset_mismatch_before_factory_creation(
    dataset_path,
):
    dataset = load_dataset(dataset_path)
    factory = FakeProviderFactory("fixture")
    registry = ProviderRegistry()
    registry.register("fixture", factory)

    with pytest.raises(EvaluationPreflightError) as error:
        registry.create(
            "fixture",
            dataset=dataset,
            model_client_factory=lambda execution: None,
        )

    assert error.value.code == "CAPABILITY_CONTRACT_MISMATCH"
    assert factory.calls == []


def test_provider_registry_rejects_factory_with_wrong_provider_id(dataset_path):
    dataset = load_dataset(dataset_path).model_copy(update={"provider_id": "fixture"})
    registry = ProviderRegistry()
    registry.register("fixture", FakeProviderFactory("mini_agent"))

    with pytest.raises(EvaluationPreflightError) as error:
        registry.create(
            "fixture",
            dataset=dataset,
            model_client_factory=lambda execution: None,
        )

    assert error.value.code == "CAPABILITY_CONTRACT_MISMATCH"


def test_provider_registry_rejects_duplicate_id():
    registry = ProviderRegistry()
    registry.register("fixture", FakeProviderFactory())

    with pytest.raises(ValueError, match="already registered"):
        registry.register("fixture", FakeProviderFactory())


def test_unknown_provider_has_stable_error(dataset_path):
    dataset = load_dataset(dataset_path)

    with pytest.raises(EvaluationPreflightError) as error:
        ProviderRegistry().create(
            "missing",
            dataset=dataset,
            model_client_factory=lambda execution: None,
        )

    assert error.value.code == "UNKNOWN_PROVIDER"
    assert error.value.evidence_refs == [dataset.manifest_path]


@pytest.mark.parametrize(
    ("dataset_name", "archived_result"),
    [
        (
            "module_query_user_intent_v1_6.jsonl",
            "tests/fixtures/archived_module_results/query_user_v1_6.json",
        ),
        (
            "module_query_gift_intent_v1_0.jsonl",
            "tests/fixtures/archived_module_results/query_gift_v1_0.json",
        ),
    ],
)
def test_frozen_module_benchmarks_replay_without_network(
    dataset_name,
    archived_result,
):
    project_root = Path(__file__).resolve().parents[1]
    dataset = load_dataset(project_root / "datasets/mini_agent" / dataset_name)
    expected = EvaluationRunResult.model_validate_json(
        (project_root / archived_result).read_text(encoding="utf-8")
    )
    responses = deque(case.module_output for case in expected.cases)
    factory_calls = []

    def offline_factory(execution):
        factory_calls.append(execution.user_input)
        return DeterministicModelClient([responses.popleft()])

    provider = MiniAgentProvider.from_dataset(
        dataset,
        offline_factory,
        verify_current=False,
    )
    actual = run_provider_evaluation(dataset, RunConfig(), provider)

    assert expected.dataset_hash == dataset.sha256
    assert responses == deque()
    assert len(factory_calls) == len(dataset.cases) == len(expected.cases)
    assert Counter(case.execution_status for case in actual.cases) == Counter(
        case.execution_status for case in expected.cases
    )
    assert Counter(case.quality_conclusion for case in actual.cases) == Counter(
        case.quality_conclusion for case in expected.cases
    )
    assert {
        case.case_id: [(item.name, item.passed) for item in case.assertion_results]
        for case in actual.cases
    } == {
        case.case_id: [(item.name, item.passed) for item in case.assertion_results]
        for case in expected.cases
    }
    assert {
        case.case_id: [item.code for item in case.diagnoses]
        for case in actual.cases
    } == {
        case.case_id: [item.code for item in case.diagnoses]
        for case in expected.cases
    }


def test_cli_has_no_mini_agent_provider_branch():
    source = (
        Path(__file__).resolve().parents[1] / "src/eval_framework/cli.py"
    ).read_text()

    assert "providers.mini_agent" not in source
    assert 'args.provider != "mini_agent"' not in source


def test_runner_works_with_fake_provider_without_mini_agent(dataset_path):
    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    registry = CapabilityRegistry(
        CapabilityBundle.load(Path(dataset.capability_bundle_path))
    )

    result = run_provider_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test"),
        FakeProvider(registry),
    )

    assert result.cases[0].quality_conclusion == "PASS"
    assert result.model_metadata["client_type"] == "FakeProvider"
    assert result.cases[0].trace_analysis is not None


def _replace_document(
    registry: CapabilityRegistry,
    snapshot_id: str,
    mutate,
) -> CapabilityRegistry:
    documents = []
    for document in registry.bundle.documents:
        if document.snapshot_id != snapshot_id:
            documents.append(document)
            continue
        payload = deepcopy(document.payload)
        mutate(payload)
        documents.append(document.model_copy(update={"payload": payload}))
    return CapabilityRegistry(
        registry.bundle.model_copy(update={"documents": tuple(documents)})
    )


def test_incompatible_current_and_frozen_schema_is_blocked(capability_registry):
    current = _replace_document(
        capability_registry,
        "intent.query_user",
        lambda payload: payload["parameters_schema"].update(
            {"additionalProperties": True}
        ),
    )

    with pytest.raises(EvaluationPreflightError) as error:
        ensure_capability_compatibility(
            capability_registry,
            current,
            expected_provider_id="mini_agent",
        )

    assert error.value.code == "CAPABILITY_CONTRACT_MISMATCH"


def test_prompt_and_display_changes_do_not_block(capability_registry):
    current = _replace_document(
        capability_registry,
        "intent.query_user",
        lambda payload: payload.update(
            {"display": {"name": "changed", "field_labels": {}}}
        ),
    )

    ensure_capability_compatibility(
        capability_registry,
        current,
        expected_provider_id="mini_agent",
    )


def test_core_modules_do_not_import_mini_agent_or_business_models():
    root = Path(__file__).resolve().parents[1] / "src" / "eval_framework"
    core = [
        root / "runner.py",
        root / "assertions.py",
        root / "diagnostics.py",
        root / "dataset_validator.py",
        root / "provider.py",
    ]
    forbidden_names = {"QueryUserInfoArguments", "INTENT_PARAMETER_MODELS"}
    for path in core:
        tree = ast.parse(path.read_text())
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        assert not any(name.startswith("minimal_agent") for name in imports), path
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert not names & forbidden_names, path

    diagnostics_source = (root / "diagnostics.py").read_text()
    assert '"query_user"' not in diagnostics_source
    assert '"query_gift"' not in diagnostics_source


def test_legacy_missing_snapshot_requires_explicit_matching_override(dataset_path):
    original = load_dataset(dataset_path)
    bundle_path = Path(original.capability_bundle_path)
    bundle = CapabilityBundle.load(bundle_path)
    manifest_path = dataset_path.with_suffix(".manifest.json")
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("capability_bundle")
    manifest["capability_bundle_sha256"] = "legacy-semantic-hash"
    manifest["capability_snapshots"] = [
        {
            "snapshot_id": item.snapshot_id,
            "snapshot_sha256": item.snapshot_sha256,
        }
        for item in bundle.documents
    ]
    manifest_path.write_text(json.dumps(manifest))
    legacy = load_dataset(dataset_path)

    with pytest.raises(EvaluationPreflightError) as error:
        MiniAgentProvider.from_dataset(legacy, lambda execution: None)
    assert error.value.code == "CAPABILITY_BUNDLE_REQUIRED"

    with pytest.raises(EvaluationPreflightError) as mismatch:
        MiniAgentProvider.from_dataset(
            legacy,
            lambda execution: None,
            bundle_override=bundle_path,
        )
    assert mismatch.value.code == "CAPABILITY_CONTRACT_MISMATCH"


def test_mini_agent_provider_rejects_stale_v2_frozen_contract():
    root = Path(__file__).resolve().parents[1]
    dataset = load_dataset(
        root / "datasets/mini_agent/module_query_user_intent_v1_5.jsonl"
    )
    with pytest.raises(EvaluationPreflightError) as error:
        MiniAgentProvider.from_dataset(dataset, lambda execution: None)

    assert error.value.code == "CAPABILITY_CONTRACT_MISMATCH"


def test_mini_agent_provider_accepts_current_native_capabilities_without_tools():
    current = CapabilityRegistry(
        CapabilityBundle.load_v2_directory(
            Path(__file__).resolve().parents[3] / "examples/mini_agent/capabilities"
        )
    )
    created = []

    provider = MiniAgentProvider(
        current,
        lambda execution: created.append(execution),
        execution_profiles={
            "shadow_read": ExecutionProfile(allowed_tools=[]),
        },
        current_capabilities=current,
    )

    assert created == []
    assert provider.tools.tools_for_profile("shadow_read") == frozenset()


def test_runtime_factory_has_no_named_profile_constants():
    source = (
        Path(__file__).resolve().parents[1]
        / "src/eval_framework/runtime_factory.py"
    ).read_text()

    assert "MINI_AGENT_TOOL_PROFILES" not in source
    assert "shadow_read" not in source
    assert "shadow_full" not in source


def test_runtime_factory_rejects_nonempty_tools_before_model_creation():
    created = []
    factory = RuntimeFactory(lambda execution: created.append(execution))
    execution = ExecutionSpec(
        user_input="query fixture",
        tool_profile="future_tools",
    )

    with pytest.raises(EvaluationPreflightError) as error:
        factory.create(
            execution,
            session_id="session",
            allowed_tools=frozenset({"query_user_info"}),
        )

    assert error.value.code == "NATIVE_TOOL_HANDLER_REQUIRED"
    assert created == []
