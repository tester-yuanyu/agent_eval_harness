"""Contract tests through the real Langfuse SDK and an HTTP boundary."""

import json

import httpx
import pytest
from langfuse.api.client import LangfuseAPI
from test_comparison import loaded


def sdk(handler):
    return LangfuseAPI(
        base_url="https://langfuse.example",
        username="test-public",
        password="test-secret",
        headers={"x-langfuse-ingestion-version": "4"},
        httpx_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.fixture
def saved_run(tmp_path, case_result_factory):
    case = case_result_factory(
        user_input="PRIVATE user input",
        trace_events=[
            {
                "event_id": "event-a",
                "event_type": "confirmation_requested",
                "timestamp": "2026-01-01T00:00:00.250Z",
                "payload": {"secret": "DO NOT EXPORT"},
            }
        ],
    )
    run = loaded(case).result
    (tmp_path / "results.json").write_text(run.model_dump_json())
    return tmp_path


def test_export_preserves_results_ids_time_and_precomputed_metrics(saved_run):
    from eval_framework.observability import export_run

    calls = []

    def handler(request):
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(
            202 if "scores" in request.url.path else 200,
            json={"message": "Accepted"} if "scores" in request.url.path else {},
        )

    before = (saved_run / "results.json").read_bytes()
    receipt = export_run(saved_run, client=sdk(handler))
    assert receipt["status"] == "ACCEPTED"
    assert len(receipt["trials"]) == 1
    assert (saved_run / "results.json").read_bytes() == before
    assert "PRIVATE" not in json.dumps(calls)
    assert "DO NOT EXPORT" not in json.dumps(calls)
    spans = calls[0][1]["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert spans[0]["startTimeUnixNano"] == "1767225600000000000"
    event = next(s for s in spans if s["name"] == "confirmation_requested")
    assert event["startTimeUnixNano"] == "1767225600250000000"
    assert event["parentSpanId"] == receipt["trials"][0]["observation_id"]
    attributes = {a["key"]: a["value"]["stringValue"] for a in spans[0]["attributes"]}
    assert attributes["langfuse.experiment.id"]
    scores = next(body for path, body in calls if "scores" in path)
    assert any(
        s["name"] == "run.framework_completion_rate" and s["value"] == 100
        for s in scores
    )
    first_ids = [s["id"] for s in scores]
    calls.clear()
    repeated = export_run(saved_run, client=sdk(handler))
    assert repeated["trials"] == receipt["trials"]
    assert all("scores" in path for path, _ in calls)
    assert first_ids == [
        s["id"] for path, body in calls if "scores" in path for s in body
    ]


def test_score_retry_does_not_resend_accepted_observations(saved_run):
    from eval_framework.observability import export_run

    calls = []
    reject_scores = True

    def handler(request):
        calls.append(request.url.path)
        if "scores" in request.url.path:
            if reject_scores:
                return httpx.Response(
                    207, json={"accepted": 0, "rejected": 1, "errors": []}
                )
            return httpx.Response(202, json={"message": "Accepted"})
        return httpx.Response(200, json={})

    with pytest.raises(ValueError, match="rejected scores"):
        export_run(saved_run, client=sdk(handler))
    calls.clear()
    reject_scores = False
    assert export_run(saved_run, client=sdk(handler))["status"] == "ACCEPTED"
    assert calls and all("scores" in path for path in calls)


def test_uncertain_observation_upload_is_not_blindly_replayed(saved_run):
    from eval_framework.observability import export_run

    def handler(request):
        raise httpx.ReadTimeout("Response lost after upload", request=request)

    with pytest.raises(httpx.ReadTimeout):
        export_run(saved_run, client=sdk(handler))
    calls = []
    with pytest.raises(ValueError, match="reconcile"):
        export_run(
            saved_run,
            client=sdk(lambda request: calls.append(request.url.path)),
        )
    assert calls == []


def test_partial_acceptance_does_not_claim_success(saved_run):
    from eval_framework.observability import export_run

    def handler(request):
        if "scores" in request.url.path:
            return httpx.Response(
                207,
                json={
                    "accepted": 0,
                    "rejected": 1,
                    "errors": [{"index": 0, "message": "invalid"}],
                },
            )
        return httpx.Response(200, json={})

    with pytest.raises(ValueError, match="rejected"):
        export_run(saved_run, client=sdk(handler))
    receipt = json.loads((saved_run / "langfuse_export.json").read_text())
    assert receipt["status"] == "PENDING"


@pytest.mark.parametrize("scenario", ["normal", "invalid_parameter"])
def test_case_scenario_is_available_for_native_coverage_breakdown(saved_run, scenario):
    from eval_framework.observability import export_run

    path = saved_run / "results.json"
    data = json.loads(path.read_text())
    data["cases"][0]["scenario_type"] = scenario
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    scores = []

    def handler(request):
        if "scores" in request.url.path:
            scores.extend(json.loads(request.content))
            return httpx.Response(202, json={"message": "Accepted"})
        return httpx.Response(200, json={})

    receipt = export_run(saved_run, client=sdk(handler))
    classifications = [s for s in scores if s["name"] == "context.scenario_type"]
    assert len(classifications) == 1
    assert classifications[0]["value"] == scenario
    assert classifications[0]["dataType"] == "CATEGORICAL"
    assert classifications[0]["observationId"] == receipt["trials"][0]["observation_id"]
    assert classifications[0]["metadata"]["authority"] == "immutable_results"
    assert path.read_bytes() == before


def test_changed_source_cannot_reuse_export_identity(saved_run):
    from eval_framework.observability import export_run

    client = sdk(
        lambda r: httpx.Response(
            202 if "scores" in r.url.path else 200,
            json={"message": "Accepted"} if "scores" in r.url.path else {},
        )
    )
    export_run(saved_run, client=client)
    path = saved_run / "results.json"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="immutable"):
        export_run(saved_run, client=client)


def test_partial_trace_rejection_never_sends_scores(saved_run):
    from eval_framework.observability import export_run

    requests = []

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "partialSuccess": {"rejectedSpans": 1, "errorMessage": "invalid"},
            },
        )

    with pytest.raises(ValueError, match="rejected observations"):
        export_run(saved_run, client=sdk(handler))
    assert not any("scores" in path for path in requests)


def test_invalid_and_unknown_are_not_exported_as_numeric_quality(saved_run):
    from eval_framework.observability import export_run

    path = saved_run / "results.json"
    data = json.loads(path.read_text())
    data["cases"][0].update(
        evaluation_validity="INVALID",
        quality_conclusion="INCONCLUSIVE",
        score=None,
    )
    path.write_text(json.dumps(data))
    scores = []

    def handler(request):
        if "scores" in request.url.path:
            scores.extend(json.loads(request.content))
            return httpx.Response(202, json={"message": "Accepted"})
        return httpx.Response(200, json={})

    export_run(saved_run, client=sdk(handler))
    assert not any(s["name"] == "quality.deterministic_score" for s in scores)
    quality = next(s for s in scores if s["name"] == "quality.conclusion")
    assert quality["value"] == "INCONCLUSIVE"
    assert quality["dataType"] == "CATEGORICAL"


def test_export_refuses_destination_switch_before_request(saved_run, monkeypatch):
    from eval_framework.observability import export_run

    calls = []

    def handler(request):
        calls.append(True)
        return httpx.Response(
            202 if "scores" in request.url.path else 200,
            json={"message": "Accepted"} if "scores" in request.url.path else {},
        )

    client = sdk(handler)
    export_run(saved_run, client=client)
    calls.clear()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "different-project")
    with pytest.raises(ValueError, match="destination"):
        export_run(saved_run, client=client)
    assert calls == []


def test_missing_credentials_is_actionable_and_does_not_modify_results(
    saved_run,
    monkeypatch,
    capsys,
):
    from eval_framework.cli import main

    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    before = (saved_run / "results.json").read_bytes()
    assert main(["export-langfuse", "--run-dir", str(saved_run)]) == 2
    assert "LANGFUSE_SECRET_KEY" in capsys.readouterr().out
    assert (saved_run / "results.json").read_bytes() == before


def test_explicit_target_receipt_preserves_legacy_cloud_receipt(saved_run):
    from eval_framework.observability import export_run

    legacy = saved_run / "langfuse_export.json"
    legacy.write_text('{"destination":"historical-cloud"}')
    target = saved_run / "local-export.json"
    result = export_run(
        saved_run,
        client=sdk(
            lambda r: httpx.Response(
                202 if "scores" in r.url.path else 200,
                json={"message": "Accepted"} if "scores" in r.url.path else {},
            )
        ),
        target_identity="local-target",
        receipt_path=target,
    )
    assert result["destination"] == "local-target"
    assert json.loads(target.read_text())["status"] == "ACCEPTED"
    assert legacy.read_text() == '{"destination":"historical-cloud"}'


def test_connection_failure_before_ingestion_can_retry(saved_run):
    from eval_framework.observability import export_run

    def unavailable(request):
        raise httpx.ConnectError("No connection", request=request)

    with pytest.raises(httpx.ConnectError):
        export_run(saved_run, client=sdk(unavailable))
    receipt = json.loads((saved_run / "langfuse_export.json").read_text())
    assert receipt["inflight_observation_ids"] == []
    assert (
        export_run(
            saved_run,
            client=sdk(
                lambda request: httpx.Response(
                    202 if "scores" in request.url.path else 200,
                    json={"message": "Accepted"}
                    if "scores" in request.url.path
                    else {},
                )
            ),
        )["status"]
        == "ACCEPTED"
    )


@pytest.mark.parametrize("failure", ["timeout", "partial207"])
def test_score_retry_resumes_confirmed_batches_and_replays_only_uncertain_batch(
    saved_run,
    failure,
):
    from eval_framework.observability import export_run

    path = saved_run / "results.json"
    data = json.loads(path.read_text())
    template = data["cases"][0]
    data["cases"] = [dict(template, case_id=f"case-{i}") for i in range(60)]
    path.write_text(json.dumps(data))
    first_batches = []

    def interrupted(request):
        if "scores" not in request.url.path:
            return httpx.Response(200, json={})
        first_batches.append([score["id"] for score in json.loads(request.content)])
        if len(first_batches) == 2:
            if failure == "partial207":
                return httpx.Response(
                    207,
                    json={
                        "accepted": 99,
                        "rejected": 1,
                        "errors": [],
                    },
                )
            raise httpx.ReadTimeout("score response lost", request=request)
        return httpx.Response(202, json={"message": "Accepted"})

    with pytest.raises(httpx.ReadTimeout if failure == "timeout" else ValueError):
        export_run(saved_run, client=sdk(interrupted))
    checkpoint = json.loads((saved_run / "langfuse_export.json").read_text())
    assert checkpoint["accepted_score_ids"] == first_batches[0]
    resumed_batches = []
    paths = []

    def resumed(request):
        paths.append(request.url.path)
        if "scores" in request.url.path:
            resumed_batches.append(
                [score["id"] for score in json.loads(request.content)]
            )
            return httpx.Response(202, json={"message": "Accepted"})
        return httpx.Response(200, json={})

    receipt = export_run(saved_run, client=sdk(resumed))
    assert receipt["status"] == "ACCEPTED"
    assert resumed_batches[0] == first_batches[1]
    assert not set(first_batches[0]).intersection(
        score_id for batch in resumed_batches for score_id in batch
    )
    assert receipt["accepted_score_ids"] == receipt["score_ids"]
    assert all("scores" in path for path in paths)


def test_accepted_legacy_scores_need_no_refresh_for_local_delivery(saved_run):
    from eval_framework.observability import export_run

    receipt = export_run(
        saved_run,
        client=sdk(
            lambda request: httpx.Response(
                202 if "scores" in request.url.path else 200,
                json={"message": "Accepted"} if "scores" in request.url.path else {},
            )
        ),
    )
    receipt.pop("accepted_score_ids", None)
    (saved_run / "langfuse_export.json").write_text(json.dumps(receipt))
    requests = []
    repeated = export_run(
        saved_run,
        client=sdk(lambda request: requests.append(request)),
        refresh_scores=False,
    )
    assert repeated["status"] == "ACCEPTED"
    assert repeated["accepted_score_ids"] == repeated["score_ids"]
    assert requests == []
