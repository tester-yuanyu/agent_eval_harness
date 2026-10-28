from __future__ import annotations

from pathlib import Path

from conftest import intent

from eval_framework.capabilities import CapabilityBundle, CapabilityRegistry
from eval_framework.cli import _parser
from eval_framework.diagnostics import DiagnosticRegistry
from eval_framework.provider import AdapterOutput, ProviderExceptionInfo
from eval_framework.reporting import write_report
from eval_framework.runner import run_provider_evaluation
from eval_framework.schemas import RunConfig
from eval_framework.stability import aggregate_stability, nearest_rank
from eval_framework.tool_catalog import ToolCatalog


class CountingProvider:
    provider_id = "mini_agent"
    provider_version = "counting-v1"
    diagnostics = DiagnosticRegistry()

    def __init__(self, dataset, *, fail_first: bool = False):
        self.capabilities = CapabilityRegistry(
            CapabilityBundle.load(Path(dataset.capability_bundle_path))
        )
        self.tools = ToolCatalog.from_registry(
            self.capabilities,
            profiles=dataset.execution_profiles,
        )
        self.sessions: list[str] = []
        self.runtimes: list[object] = []
        self.fail_first = fail_first
        self.run_count = 0

    def create_runtime(self, execution, session_id, scope):
        del execution, scope
        runtime = object()
        self.sessions.append(session_id)
        self.runtimes.append(runtime)
        return runtime

    def run_module(self, runtime, execution):
        del runtime, execution
        self.run_count += 1
        if self.fail_first and self.run_count == 1:
            raise RuntimeError("first trial fails")
        return AdapterOutput(intent(), [], None, [], None, [])

    def run_full(self, runtime, execution, scope):
        raise AssertionError((runtime, execution, scope))

    def cleanup(self, runtime):
        del runtime

    def classify_exception(self, exc):
        return ProviderExceptionInfo(
            execution_status="AGENT_EXCEPTION",
            exception={"type": type(exc).__name__, "message": str(exc)},
        )

    def runtime_metadata(self, runtime):
        del runtime
        return {"model": "counting"}

    def tool_version(self, runtime):
        del runtime
        return "fixture-tools"


def test_each_trial_gets_new_runtime_and_session(dataset_path):
    from eval_framework import load_dataset

    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    provider = CountingProvider(dataset)

    result = run_provider_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test", trials_per_case=3),
        provider,
    )

    assert [case.trial_id for case in result.cases] == [
        "trial_001",
        "trial_002",
        "trial_003",
    ]
    assert len({id(runtime) for runtime in provider.runtimes}) == 3
    assert len(set(provider.sessions)) == 3
    assert result.summary.total_cases == 1
    assert result.summary.total_trials == 3
    assert result.trials_per_case == 3


def test_failed_trial_is_not_overwritten_by_later_pass(dataset_path):
    from eval_framework import load_dataset

    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    provider = CountingProvider(dataset, fail_first=True)

    result = run_provider_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test", trials_per_case=3),
        provider,
    )

    assert [case.execution_status for case in result.cases] == [
        "AGENT_EXCEPTION",
        "COMPLETED",
        "COMPLETED",
    ]
    assert [case.quality_conclusion for case in result.cases] == [
        "INCONCLUSIVE",
        "PASS",
        "PASS",
    ]
    assert result.stability.cases[0].pass_at_k is True
    assert result.stability.cases[0].pass_power_k is False


def test_stability_metrics_and_nearest_rank_are_hand_derived(dataset_path):
    from eval_framework import load_dataset

    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    result = run_provider_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test", trials_per_case=3),
        CountingProvider(dataset),
    )
    cases = [
        result.cases[0].model_copy(update={"latency_ms": 10}),
        result.cases[1].model_copy(
            update={"latency_ms": 20, "quality_conclusion": "FAIL"}
        ),
        result.cases[2].model_copy(update={"latency_ms": 30}),
    ]

    stability = aggregate_stability(cases, planned_trials=3)
    case = stability.cases[0]
    assert case.pass_count == 2
    assert case.fail_count == 1
    assert case.trial_pass_rate == 66.67
    assert case.pass_at_k is True
    assert case.pass_power_k is False
    assert case.latency_p50_ms == 20
    assert case.latency_p95_ms == 30
    assert nearest_rank([], 0.95) is None
    assert nearest_rank([9], 0.95) == 9
    assert nearest_rank([10, 20, 30, 40, 50], 0.95) == 50


def test_report_writes_distinct_case_files_per_trial(dataset_path, tmp_path):
    from eval_framework import load_dataset

    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    provider = CountingProvider(dataset)
    result = run_provider_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test", trials_per_case=2),
        provider,
    )

    paths = write_report(result, tmp_path, provider.capabilities)

    relative = [
        Path(path).relative_to(paths.output_dir).as_posix() for path in paths.case_files
    ]
    assert relative == [
        "cases/MODULE-1/trial_001.json",
        "cases/MODULE-1/trial_002.json",
    ]


def test_run_cli_accepts_trial_count():
    args = _parser().parse_args(
        [
            "run",
            "--dataset",
            "cases.jsonl",
            "--output-dir",
            "artifacts",
            "--trials",
            "3",
        ]
    )

    assert args.trials == 3


def test_generic_observation_changes_are_output_volatile(case_result_factory):
    first = case_result_factory(
        case_id="generic",
        trial_id="trial_001",
        module_output=None,
        observations={"result": {"text": "first"}},
    )
    second = first.model_copy(
        update={
            "trial_id": "trial_002",
            "observations": {"result": {"text": "second"}},
        }
    )
    stability = aggregate_stability([first, second], planned_trials=2)
    assert stability.cases[0].output_volatile is True
    assert len(set(stability.cases[0].output_hashes)) == 2


def test_repeated_generic_observations_preserve_existing_normalization(
    case_result_factory,
):
    first = case_result_factory(
        case_id="generic",
        trial_id="trial_001",
        module_output=None,
        observations={"result": {"text": "same", "run_id": "run-one"}},
    )
    second = first.model_copy(
        update={
            "trial_id": "trial_002",
            "observations": {"result": {"text": "same", "run_id": "run-two"}},
        }
    )
    stability = aggregate_stability([first, second], planned_trials=2)
    assert stability.cases[0].output_volatile is False
    assert len(set(stability.cases[0].output_hashes)) == 1


def test_absent_observations_preserve_historical_output_hash(case_result_factory):
    import hashlib
    import json

    from eval_framework.stability import (
        canonical_observed_output,
        observed_output_sha256,
    )

    case = case_result_factory(
        module_output=None,
        turn_results=[],
        system_snapshot=None,
        observations=None,
    )
    legacy = {"module_output": None, "turns": [], "system_snapshot": None}
    assert canonical_observed_output(case) == legacy
    digest = hashlib.sha256(
        json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert observed_output_sha256(case) == digest
    empty = case.model_copy(update={"observations": {}})
    assert canonical_observed_output(empty)["observations"] == {}
    assert observed_output_sha256(empty) != digest


def test_generic_observations_keep_explicit_output_normalizer(case_result_factory):
    first = case_result_factory(
        case_id="generic",
        trial_id="trial_001",
        observations={"text": "first"},
    )
    second = first.model_copy(
        update={
            "trial_id": "trial_002",
            "observations": {"text": "second"},
        }
    )
    stability = aggregate_stability(
        [first, second],
        planned_trials=2,
        normalizer=lambda result: {"custom": result.quality_conclusion},
    )
    assert stability.cases[0].output_volatile is False
