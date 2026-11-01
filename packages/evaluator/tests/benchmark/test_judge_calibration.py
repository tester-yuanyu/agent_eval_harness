"""Calibration statistics require independent completed labels and exact joins."""

from copy import deepcopy

import pytest
from eval_framework.benchmark import judge_calibration as calibration


def records():
    return [
        {
            "record_id": "a",
            "metric_id": "m1",
            "name": "response_groundedness",
            "version": "trajectory-geval-v1",
            "scope": "turn",
            "event_id": "t1",
            "status": "SCORED",
            "score": 0.9,
            "reason": "MODEL_REASON",
            "evidence_ids": ["t1"],
            "events": [{"input": "evidence a", "output": "MODEL_SCORE"}],
        },
        {
            "record_id": "b",
            "metric_id": "m2",
            "name": "action_appropriateness",
            "version": "trajectory-geval-v1",
            "scope": "generation",
            "event_id": "g1",
            "status": "ERROR",
            "score": None,
            "evidence_ids": ["g1"],
            "events": [],
        },
        {
            "record_id": "c",
            "metric_id": "m3",
            "name": "response_groundedness",
            "version": "trajectory-geval-v1",
            "scope": "turn",
            "event_id": "t2",
            "status": "SCORED",
            "score": 0.4,
            "evidence_ids": ["t2"],
            "events": [],
        },
    ]


def label(identity, score):
    return {
        "record_id": identity,
        "human_score": score,
        "annotator": "independent-reviewer",
        "annotation_source": "human",
        "independent": True,
    }


def test_blank_worksheet_has_no_human_claim_or_model_score_anchoring():
    worksheet = calibration.create_calibration_worksheet(records())
    assert worksheet["status"] == "awaiting_independent_human_labels"
    assert len(worksheet["rows"]) == 3
    assert all(
        row["human_score"] is None and row["annotator"] is None
        for row in worksheet["rows"]
    )
    assert "MODEL_REASON" not in str(worksheet)
    assert "MODEL_SCORE" not in str(worksheet)
    assert "score" not in worksheet["rows"][0]


def test_missing_human_labels_cannot_be_called_calibrated():
    result = calibration.compare_human_labels(
        records(), [], threshold=0.7, threshold_version="candidate-v1"
    )
    assert result["status"] == "awaiting_independent_human_labels"
    assert result["agreement"] is None
    assert result["labeled"] == 0
    assert result["missing_label_ids"] == ["a", "b", "c"]
    assert result["threshold_status"] == "requires_independent_validation"


def test_human_labels_join_exactly_and_report_missing_judge_score():
    result = calibration.compare_human_labels(
        records(),
        [label("a", 0.2), label("b", 0.8), label("c", 0.9)],
        threshold=0.7,
        threshold_version="candidate-v1",
    )
    assert result["paired"] == 2
    assert result["judge_unscored_ids"] == ["b"]
    assert result["agreement"] == 0
    assert result["false_accept_rate"] == 1
    assert result["false_reject_rate"] == 1
    assert result["mean_absolute_error"] == pytest.approx(0.6)
    assert result["status"] == "diagnostic_agreement_only"


@pytest.mark.parametrize(
    "labels", [[label("unknown", 0.8)], [label("a", 0.2), label("a", 0.8)]]
)
def test_unknown_or_duplicate_label_ids_fail_strict_join(labels):
    with pytest.raises(ValueError):
        calibration.compare_human_labels(
            records(), labels, threshold=0.7, threshold_version="candidate-v1"
        )


@pytest.mark.parametrize(
    "patch",
    [
        {"annotation_source": "model"},
        {"independent": False},
        {"annotator": ""},
        {"human_score": 1.1},
        {"human_score": True},
    ],
)
def test_invalid_or_nonindependent_labels_cannot_enter_agreement(patch):
    row = {**label("a", 0.8), **patch}
    with pytest.raises(ValueError):
        calibration.compare_human_labels(
            records(), [row], threshold=0.7, threshold_version="candidate-v1"
        )


def test_run_records_disambiguate_same_metric_across_trials():
    metric = records()[0]
    metric.pop("record_id")
    run = {
        "run_id": "run",
        "trials": [
            {
                "case_id": "case",
                "trial": trial,
                "assessment": {"metrics": [deepcopy(metric)]},
            }
            for trial in (1, 2)
        ],
    }
    worksheet = calibration.create_calibration_worksheet(run)
    assert len({row["record_id"] for row in worksheet["rows"]}) == 2


def test_not_applicable_metrics_are_excluded_from_calibration_population():
    rows = records() + [
        {**records()[0], "record_id": "na", "status": "NOT_APPLICABLE", "score": None}
    ]
    worksheet = calibration.create_calibration_worksheet(rows)
    assert {row["record_id"] for row in worksheet["rows"]} == {"a", "b", "c"}


def test_agreement_is_also_reported_per_dimension():
    result = calibration.compare_human_labels(
        records(),
        [label("a", 0.9), label("b", 0.8), label("c", 0.2)],
        threshold=0.7,
        threshold_version="candidate-v1",
    )
    assert result["by_dimension"]["response_groundedness"]["paired"] == 2
    assert result["by_dimension"]["response_groundedness"]["agreement"] == 1
    assert result["by_dimension"]["action_appropriateness"]["paired"] == 0
    assert result["by_dimension"]["action_appropriateness"]["agreement"] is None
