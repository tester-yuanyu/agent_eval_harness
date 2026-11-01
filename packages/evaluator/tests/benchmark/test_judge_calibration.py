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


def test_dimension_denominators_and_confusion_do_not_use_population_as_rate_base():
    rows = records() + [
        {**records()[0], "record_id": "d", "score": 0.2},
        {**records()[0], "record_id": "e", "score": 0.9},
    ]
    result = calibration.compare_human_labels(
        rows,
        [label("a", 0.1), label("b", 0.8), label("c", 0.2), label("d", 0.9)],
        threshold=0.7,
        threshold_version="candidate-v1",
    )
    group = result["by_dimension"]["response_groundedness"]
    assert (group["total"], group["labeled"], group["paired"]) == (4, 3, 3)
    assert group["label_coverage"] == 0.75
    assert group["human_negative"] == 2
    assert group["human_positive"] == 1
    assert group["false_accept_rate"] == 0.5
    assert group["false_reject_rate"] == 1
    assert group["confusion_matrix"] == {
        "true_accept": 0,
        "false_accept": 1,
        "true_reject": 1,
        "false_reject": 1,
    }
    assert group["missing_label_ids"] == ["e"]
    missing = result["by_dimension"]["action_appropriateness"]
    assert (missing["total"], missing["labeled"], missing["paired"]) == (1, 1, 0)
    assert missing["judge_unscored_ids"] == ["b"]
    assert missing["false_accept_rate"] is None
    assert {case["record_id"] for case in result["disagreements"]} == {"a", "d"}
    assert {case["classification"] for case in result["disagreements"]} == {
        "false_accept",
        "false_reject",
    }
    assert result["disagreements"][0]["evidence_ids"] == ["t1"]


def test_blank_labels_preserve_all_dimensions_and_machine_verifiable_inputs():
    import hashlib
    import json

    rows, labels = records(), [label("a", None)]
    result = calibration.compare_human_labels(
        rows,
        labels,
        threshold=0.7,
        threshold_version="candidate-v1",
    )
    assert result["by_dimension"]["action_appropriateness"]["total"] == 1
    assert result["by_dimension"]["response_groundedness"]["labeled"] == 0
    assert result["disagreements"] == []
    for key, value in (("source_summary", rows), ("labels_summary", labels)):
        expected = hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        assert result[key]["sha256"] == expected
    assert result["labels_summary"]["completed_count"] == 0
    assert result["labels_summary"]["submitted_count"] == 1


def test_completed_labels_with_no_judge_scores_remain_diagnostic_not_unlabeled():
    result = calibration.compare_human_labels(
        records(),
        [label("b", 0)],
        threshold=0.7,
        threshold_version="candidate-v1",
    )
    assert result["status"] == "diagnostic_agreement_only"
    assert result["agreement"] is None
    assert result["threshold_status"] == "requires_independent_validation"


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_judge_score_remains_unscored_when_hashing_source(score):
    rows = [{**records()[0], "score": score}]
    result = calibration.compare_human_labels(
        rows, [label("a", 0.5)], threshold=0.7, threshold_version="candidate-v1"
    )
    assert result["judge_unscored_ids"] == ["a"]
    assert result["paired"] == 0
    assert result["agreement"] is None
    assert len(result["source_summary"]["sha256"]) == 64
