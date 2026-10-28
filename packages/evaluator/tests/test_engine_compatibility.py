"""Domain and historical-format compatibility after the Inspect migration."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_execution_scoring import scripts

from eval_framework import RunConfig, load_dataset, run_evaluation


def test_engine_fingerprint_prevents_legacy_and_backend_version_comparisons(
    case_result_factory,
):
    from test_comparison import loaded

    from eval_framework.comparison import check_comparability
    from eval_framework.inspect_engine import backend_metadata

    baseline = loaded(case_result_factory())
    candidate = loaded(case_result_factory(), evaluation_backend=backend_metadata())
    report = check_comparability(baseline, candidate)
    assert report.status == "INVALID_COMPARISON"
    assert any(i.code == "EVALUATION_BACKEND_MISMATCH" for i in report.issues)
    other = loaded(
        case_result_factory(),
        evaluation_backend={**backend_metadata(), "version": "other"},
    )
    assert check_comparability(candidate, other).status == "INVALID_COMPARISON"


@pytest.mark.parametrize(
    "critical,missing,invalid,score,conclusion",
    [
        (False, False, False, 90, "PASS"),
        (True, False, False, 90, "FAIL"),
        (False, True, False, None, "INCONCLUSIVE"),
        (False, False, True, None, "FAIL"),
    ],
)
def test_native_metric_preserves_domain_weighting_and_unknowns(
    case_result_factory,
    tmp_path,
    critical,
    missing,
    invalid,
    score,
    conclusion,
):
    from conftest import assertion, intent, module_case

    from eval_framework.diagnostics import DiagnosticRegistry
    from eval_framework.evaluation_policy import TrialEvaluation, assess_trial
    from eval_framework.inspect_engine import domain_score
    from eval_framework.provider import AdapterOutput
    from eval_framework.schemas import EvalCase

    raw = module_case()
    raw["oracle"]["evaluation"]["checks"] = [
        assertion("status_match", weight=9),
        assertion("next_action_match", weight=1, critical=critical),
    ]
    case = EvalCase.model_validate(raw)
    output = AdapterOutput(
        None if missing else intent(action="ASK_USER"),
        [],
        None,
        [],
        None,
        evidence_status="COMPLETE",
    )
    trial = TrialEvaluation(
        case,
        case_result_factory(
            assertion_results=[],
            score=None,
            evaluation_validity="INVALID" if invalid else "VALID",
        ),
        output,
        True,
    )
    provider = SimpleNamespace(capabilities=None, diagnostics=DiagnosticRegistry())
    result = assess_trial(trial, RunConfig(pass_threshold=80), provider)
    assert result.score == score
    assert result.quality_conclusion == conclusion
    native = domain_score(result)
    assert native.metadata["score"] == score
    assert (native.value == "C") == (conclusion == "PASS")
    assert native.metadata["evaluation_validity"] == result.evaluation_validity


def test_trace_failure_prevents_judge_invocation(dataset_path, tmp_path, monkeypatch):
    from support.judge_client import ScriptedJudgeClient
    from test_judge import judged_case, rubric_file

    from eval_framework.phase2_schemas import JudgeRunConfig

    dataset = load_dataset(dataset_path)
    dataset.cases = [judged_case()]

    def broken(*args):
        raise ValueError("invalid trace analysis")

    monkeypatch.setattr("eval_framework.evaluation_policy.analyze_case_trace", broken)
    client = ScriptedJudgeClient([])
    result = run_evaluation(
        dataset,
        RunConfig(
            run_mode="framework_self_test",
            judge=JudgeRunConfig(rubric_path=str(rubric_file(tmp_path))),
        ),
        scripts,
        judge_client=client,
        output_dir=tmp_path,
    )
    assert result.cases[0].evaluation_validity == "INVALID"
    assert result.cases[0].judge_result is None
    assert not client.requests


def test_cleanup_cannot_mutate_pending_observations(
    dataset_path, tmp_path, monkeypatch
):
    from eval_framework.providers.mini_agent import MiniAgentProvider

    dataset = load_dataset(dataset_path)
    dataset.cases = dataset.cases[:1]
    original_run = MiniAgentProvider.run_module
    original_cleanup = MiniAgentProvider.cleanup
    outputs = []

    def run(*args):
        output = original_run(*args)
        outputs.append(output)
        return output

    def cleanup(*args):
        original_cleanup(*args)
        outputs[-1].module_output.clear()

    monkeypatch.setattr(MiniAgentProvider, "run_module", run)
    monkeypatch.setattr(MiniAgentProvider, "cleanup", cleanup)
    result = run_evaluation(
        dataset,
        RunConfig(run_mode="framework_self_test"),
        scripts,
        output_dir=tmp_path,
    )
    assert result.cases[0].quality_conclusion == "PASS"
    assert result.cases[0].module_output["intent"] == "query_information"


def test_native_engine_is_local_even_with_cloud_credentials(dataset_path, tmp_path):
    import os
    import subprocess
    import sys

    script = """
import socket, sys
from pathlib import Path
attempts = []
def forbidden(*args, **kwargs):
    attempts.append(True)
    raise AssertionError('unexpected network')
socket.socket.connect = forbidden
socket.create_connection = forbidden
sys.path.insert(0, sys.argv[1])
from test_execution_scoring import scripts
from eval_framework import load_dataset, run_evaluation, RunConfig
dataset = load_dataset(sys.argv[2])
dataset.cases = dataset.cases[:1]
for _ in range(2):
    result = run_evaluation(dataset, RunConfig(run_mode='framework_self_test'),
                            scripts, output_dir=Path.cwd() / 'runs')
    assert result.cases[0].quality_conclusion == 'PASS'
    assert (Path(result.run_directory) / result.native_artifacts['test_run']).is_file()
assert not attempts
assert sorted(p.name for p in Path.cwd().iterdir()) == ['runs']
"""
    sandbox = tmp_path / "isolated"
    sandbox.mkdir()
    completed = subprocess.run(
        [sys.executable, "-c", script, str(Path(__file__).parent), str(dataset_path)],
        cwd=sandbox,
        capture_output=True,
        text=True,
        env={**os.environ, "CONFIDENT_API_KEY": "offline-fake-cloud-key"},
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
