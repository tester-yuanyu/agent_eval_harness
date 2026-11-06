import copy
import importlib.util
from dataclasses import asdict
from pathlib import Path

import pytest

from eval_framework.provider import AdapterOutput

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("minimal_agent") is None,
    reason="optional mini_agent integration",
)

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def dataset(tmp_path):
    from eval_framework.benchmark.mini_dataset import build_dataset

    path = tmp_path / "dataset"
    build_dataset(path, ROOT)
    return path


def test_dataset_has_layered_coverage_and_no_private_execution_input(dataset):
    from eval_framework.benchmark.mini_scoring import MiniAgentDomain
    from eval_framework.benchmark.provider_tasks import load_provider_tasks

    tasks = load_provider_tasks(dataset)
    assert len(tasks) == 105
    assert sum(t["evaluation_level"] == "module" for t in tasks) == 93
    assert sum(t["evaluation_level"] == "chain" for t in tasks) == 6
    assert sum(t["evaluation_level"] == "e2e" for t in tasks) == 6
    domain = MiniAgentDomain(dataset)
    for task in tasks:
        public = domain.execution_task(task)
        assert set(public) == {"execution", "scope", "environment"}
        assert "oracle" not in public
    with pytest.raises(ValueError, match="hash"):
        (dataset / "tasks.jsonl").write_text(
            (dataset / "tasks.jsonl").read_text() + "\n"
        )
        load_provider_tasks(dataset)


def test_deepeval_preserves_pass_fail_and_missing_evidence(dataset):
    from eval_framework.benchmark.mini_scoring import MiniAgentDomain
    from eval_framework.benchmark.provider_tasks import load_provider_tasks

    task = load_provider_tasks(dataset)[0]
    domain = MiniAgentDomain(dataset)
    raw_event = dict(
        event_id="intent",
        event_type="intent_decided",
        validation_status="VALID",
        run_id="r",
        payload={},
    )
    output = AdapterOutput(
        copy.deepcopy(task["oracle"]["expected_module_output"]),
        [],
        None,
        [],
        None,
        trace_events=[raw_event],
        evidence_status="COMPLETE",
        evidence_manifest={"status": "COMPLETE"},
    )
    observation = dict(
        status="completed",
        evidence_complete=True,
        adapter_output=asdict(output),
        errors=[],
        events=[dict(id="generation", type="generation", incomplete=False)],
    )
    result = domain.score_task(task, observation)
    assert result["verdict"] == "PASS"
    assert all(m["backend"] == "deepeval" for m in result["metrics"])
    assert all(not m["native_scores"] for m in result["metrics"])
    observation["adapter_output"]["module_output"]["intent"] = "unsupported"
    assert domain.score_task(task, observation)["verdict"] == "FAIL"
    observation["evidence_complete"] = False
    assert domain.score_task(task, observation)["verdict"] == "INCONCLUSIVE"
    observation["status"] = "error"
    assert domain.score_task(task, observation)["verdict"] == "INVALID"
