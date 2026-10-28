"""The review adapter exports stored evidence, never invented human labels."""

import importlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_review_material_preserves_unknowns_and_private_drafts(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "examples"))
    module = importlib.import_module("conversation_calibration_review")
    corpus = {
        "source_sha256": "corpus",
        "cases": [
            {
                "id": "C1",
                "category": "omission",
                "turns": [{"user": "q", "assistant": "a"}],
                "draft": {"status": "SUCCESS", "score_interval": [0, 0]},
            }
        ],
    }
    projection = {
        "run_id": "run",
        "started_at": "2026-10-28T10:00:00+00:00",
        "completed_at": "2026-10-28T10:00:05+00:00",
        "native_log_sha256": "log",
        "trials": [
            {
                "case_id": "C1",
                "epoch": 1,
                "diagnostic": {"status": "SUCCESS", "score": 0},
            },
            {
                "case_id": "C1",
                "epoch": 2,
                "diagnostic": {"status": "ERROR", "score": None},
            },
        ],
    }
    spans, scores, bindings = module.review_material(corpus, projection)
    assert len(spans) == 1 and len(bindings) == 1
    numeric = [s for s in scores if s.data_type == "NUMERIC"]
    assert len(numeric) == 1 and numeric[0].value == 0
    assert len(scores) == 3
    assert all(s.metadata["authority"] == "immutable_inspect_log" for s in scores)
    assert all(not s.name.startswith("calibration.review") for s in scores)
    attributes = {a.key: a.value.string_value for a in spans[0].attributes}
    assert "draft" not in attributes["langfuse.observation.input"]
    metadata = json.loads(attributes["langfuse.observation.metadata"])
    assert metadata["reference_status"] == "PENDING_HUMAN_REVIEW"
    assert metadata["gate_eligible"] is False


def test_review_rejects_modified_native_log(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "examples"))
    module = importlib.import_module("conversation_calibration_review")
    (tmp_path / "native.eval").write_text("modified")
    (tmp_path / "projection.json").write_text(
        json.dumps(
            {
                "native_log": str(tmp_path / "native.eval"),
                "native_log_sha256": "original",
            }
        )
    )
    with pytest.raises(ValueError, match="native log"):
        module.verified_inputs(
            tmp_path, ROOT / "datasets/calibration/conversation_v1.json"
        )


def test_resume_only_replays_scores_after_confirmed_observations(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "examples"))
    module = importlib.import_module("conversation_calibration_review")
    path = tmp_path / "receipt.json"
    expected = {"destination": "local", "projection_sha256": "source", "bindings": []}
    for status in ["OBSERVATIONS_INFLIGHT", "CONFIG_INFLIGHT", "QUEUE_INFLIGHT"]:
        path.write_text(json.dumps({**expected, "status": status}))
        with pytest.raises(ValueError, match="reconcile"):
            module.prepare_receipt(path, expected, resume_scores=True)
    path.write_text(json.dumps({**expected, "status": "SCORES_INFLIGHT"}))
    assert (
        module.prepare_receipt(path, expected, resume_scores=True)["status"]
        == "SCORES_INFLIGHT"
    )
    with pytest.raises(ValueError, match="identity"):
        module.prepare_receipt(
            path, {**expected, "destination": "other"}, resume_scores=True
        )
