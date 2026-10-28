"""Judge calibration keeps proposed labels private and repetitions complete."""

import importlib.util
from pathlib import Path

import pytest

from eval_framework.diagnostic_metrics import DiagnosticMetricResult

ROOT = Path(__file__).resolve().parents[1]


def example():
    spec = importlib.util.spec_from_file_location(
        "conversation_calibration", ROOT / "examples/conversation_calibration.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_corpus_has_24_private_unreviewed_labels():
    module = example()
    corpus = module.load_corpus(ROOT / "datasets/calibration/conversation_v1.json")
    assert len(corpus["cases"]) == 24
    assert len({c["id"] for c in corpus["cases"]}) == 24
    assert all(c["review_state"] == "PENDING_HUMAN_REVIEW" for c in corpus["cases"])
    assert {c["category"] for c in corpus["cases"]} == {
        "fulfilled",
        "omission",
        "cancellation",
        "correction",
        "business_evidence",
        "prompt_injection",
        "unavailable",
    }
    for sample in module.calibration_task(corpus, object(), epochs=3).dataset:
        assert sample.target == ""
        assert "draft" not in sample.metadata


def test_real_inspect_epochs_keep_unknowns_and_no_oracle(tmp_path, monkeypatch):
    from inspect_ai import eval as inspect_eval

    module = example()
    corpus = module.load_corpus(ROOT / "datasets/calibration/conversation_v1.json")
    corpus["cases"] = [corpus["cases"][0], corpus["cases"][-3]]
    calls = []
    aggregates = []
    original = module.native_mean

    def mean(values):
        aggregates.append(True)
        return original(values)

    monkeypatch.setattr(module, "native_mean", mean)

    class Client:
        async def evaluate(self, messages):
            calls.append(messages)
            assert "PENDING_HUMAN_REVIEW" not in str(messages)
            return DiagnosticMetricResult(status="SUCCESS", score=0)

    logs = inspect_eval(
        module.calibration_task(corpus, Client(), epochs=3),
        model="mockllm/model",
        display="none",
        ctl_server=False,
        log_dir=str(tmp_path),
        max_samples=2,
    )
    log = logs[0]
    assert log.status == "success"
    assert len(log.samples) == 6 and len(calls) == 3
    projection = module.project_log(log, corpus)
    assert projection["planned_trials"] == 6
    assert len(projection["trials"]) == 6
    analysis = module.analyze(projection, corpus)
    assert analysis["human_approved_cases"] == 0
    assert analysis["gate_eligible"] is False
    assert analysis["cases"][1]["numeric_repeats"] == 0
    assert analysis["cases"][1]["score_range"] is None
    assert analysis["cases"][0]["score_range"] == 0
    assert aggregates == [True]
    changed = {**corpus, "source_sha256": "different"}
    with pytest.raises(ValueError, match="corpus"):
        module.project_log(log, changed)
    with pytest.raises(ValueError, match="corpus"):
        module.analyze(projection, changed)


def test_incomplete_repeat_set_cannot_be_claimed_complete():
    module = example()
    corpus = {
        "cases": [
            {"id": "C1", "draft": {"status": "SUCCESS", "score_interval": [0, 1]}}
        ]
    }
    with pytest.raises(ValueError, match="incomplete"):
        module.analyze({"epochs": 3, "trials": []}, corpus)
