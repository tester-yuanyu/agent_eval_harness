import json

import httpx
import pytest
from test_langfuse_export import saved_run as saved_run_fixture
from test_langfuse_export import sdk

saved_run = saved_run_fixture


def prepare(run_dir):
    from eval_framework.observability import export_run

    client = sdk(
        lambda r: httpx.Response(
            202 if "scores" in r.url.path else 200,
            json={"message": "Accepted"} if "scores" in r.url.path else {},
        )
    )
    return export_run(run_dir, client=client)


def review(trace_id, **updates):
    data = {
        "id": "review-1",
        "projectId": "project",
        "name": "review.decision.v1",
        "source": "ANNOTATION",
        "dataType": "CATEGORICAL",
        "value": "UPHOLD",
        "timestamp": "2026-01-01T01:00:00Z",
        "environment": "default",
        "createdAt": "2026-01-01T01:00:00Z",
        "updatedAt": "2026-01-01T01:00:00Z",
        "authorUserId": "reviewer-1",
        "subject": {"kind": "trace", "id": trace_id},
        "comment": json.dumps(
            {
                "reason": "Observed evidence supports the result.",
                "primary_cause": None,
                "secondary_causes": [],
                "optimization_direction": "none",
            }
        ),
    }
    data.update(updates)
    return data


def test_import_is_revision_aware_and_cannot_mutate_automatic_results(saved_run):
    from eval_framework.adjudication import import_reviews

    receipt = prepare(saved_run)
    row = review(receipt["trials"][0]["trace_id"])

    def handler(request):
        assert set(request.url.params["fields"].split(",")) == {
            "details",
            "subject",
            "annotation",
        }
        return httpx.Response(
            200,
            json={
                "data": [row],
                "meta": {"limit": 100, "cursor": None},
            },
        )

    client = sdk(handler)
    before = (saved_run / "results.json").read_bytes()
    assert import_reviews(saved_run, client=client)["imported"] == 1
    assert import_reviews(saved_run, client=client)["imported"] == 0
    row["value"] = "CONTRACT_DISPUTE"
    row["updatedAt"] = "2026-01-01T02:00:00Z"
    assert import_reviews(saved_run, client=client)["imported"] == 1
    rows = [
        json.loads(x)
        for x in (saved_run / "langfuse_reviews.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 2
    assert rows[1]["source_score_id"] == rows[0]["source_score_id"]
    assert rows[1]["result_sha256"] == receipt["results_sha256"]
    assert rows[1]["manual_conclusion"] == "CONTRACT_DISPUTE"
    assert (saved_run / "results.json").read_bytes() == before


@pytest.mark.parametrize(
    "updates",
    [
        {"source": "API"},
        {"subject": {"kind": "trace", "id": "unrelated"}},
        {"value": "invented_decision"},
        {
            "comment": '{"reason":"x","primary_cause":"invented_label",'
            '"optimization_direction":"none"}'
        },
    ],
)
def test_invalid_cloud_review_cannot_enter_structured_store(saved_run, updates):
    from eval_framework.adjudication import import_reviews

    receipt = prepare(saved_run)
    client = sdk(
        lambda r: httpx.Response(
            200,
            json={
                "data": [review(receipt["trials"][0]["trace_id"], **updates)],
                "meta": {"limit": 100},
            },
        )
    )
    with pytest.raises(ValueError):
        import_reviews(saved_run, client=client)
    assert not (saved_run / "langfuse_reviews.jsonl").exists()


def test_cloud_deletion_updates_active_snapshot_without_erasing_audit(saved_run):
    from eval_framework.adjudication import import_reviews

    receipt = prepare(saved_run)
    rows = [review(receipt["trials"][0]["trace_id"])]
    client = sdk(
        lambda r: httpx.Response(
            200,
            json={
                "data": rows,
                "meta": {"limit": 100},
            },
        )
    )
    import_reviews(saved_run, client=client)
    rows.clear()
    result = import_reviews(saved_run, client=client)
    assert result["active_revisions"] == []
    assert (saved_run / "langfuse_reviews.jsonl").exists()


@pytest.mark.parametrize(
    "label",
    [
        "PROTOCOL_NAMING_MISMATCH",
        "ASSERTION_TURNS_MATCH",
    ],
)
def test_reviewer_can_correct_to_a_known_label_not_automatically_detected(
    saved_run,
    label,
):
    from eval_framework.adjudication import import_reviews

    receipt = prepare(saved_run)
    row = review(
        receipt["trials"][0]["trace_id"],
        comment=json.dumps(
            {
                "reason": "Naming mismatch identified by human review",
                "primary_cause": label,
                "optimization_direction": "dataset_contract",
            }
        ),
    )
    client = sdk(
        lambda r: httpx.Response(
            200,
            json={
                "data": [row],
                "meta": {"limit": 100},
            },
        )
    )
    assert import_reviews(saved_run, client=client)["imported"] == 1
    saved = json.loads((saved_run / "langfuse_reviews.jsonl").read_text())
    assert saved["taxonomy_version"] == "error-taxonomy-v1"
    assert len(saved["taxonomy_sha256"]) == 64


def test_import_fetches_all_pages_and_deduplicates_repeated_scores(saved_run):
    from eval_framework.adjudication import import_reviews

    receipt = prepare(saved_run)
    first = review(receipt["trials"][0]["trace_id"])
    second = {**first, "id": "review-2"}
    cursors = []

    def handler(request):
        cursor = request.url.params.get("cursor")
        cursors.append(cursor)
        return httpx.Response(
            200,
            json={
                "data": [first] if cursor is None else [first, second],
                "meta": {"limit": 100, "cursor": "page-2" if cursor is None else None},
            },
        )

    assert import_reviews(saved_run, client=sdk(handler))["imported"] == 2
    assert cursors == [None, "page-2"]
