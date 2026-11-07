import pytest

pytest.importorskip("langfuse")

from .test_report_trends import source


def test_trend_annotations_are_run_summaries_and_not_trial_scores():
    from eval_framework.benchmark.langfuse_trends import trend_payload, trend_widget
    from eval_framework.benchmark.report_trends import build_trend

    trend = build_trend([source(), source("r2", "02", "PASS")])
    scores = trend_payload(trend)
    assert len(scores) == 4
    assert all(s.metadata["formal"] is False and s.trace_id is None for s in scores)
    assert all(s.dataset_run_id for s in scores)
    assert scores[1].value == 0 and scores[3].value == 100
    assert [s.id for s in scores] == [s.id for s in trend_payload(trend)]
    w = trend_widget(trend)
    assert w["chart_type"] == "LINE_TIME_SERIES"
    assert "show_value_labels" not in w["chart_config"]
    assert not any(f["column"] == "traceId" for f in w["filters"])
    assert any(
        f.get("key") == "cohort_id" and f["value"] == trend["cohort_id"]
        for f in w["filters"]
    )
    assert "等权平均" in w["description"]


def test_run_summary_sync_reconciles_uncertain_write_without_duplicates(
    tmp_path, monkeypatch
):
    import json
    from types import SimpleNamespace

    from eval_framework.benchmark import langfuse_trends as module
    from eval_framework.benchmark.report_trends import build_trend
    from eval_framework.observability import destination_fingerprint

    trend = build_trend([source()])
    monkeypatch.setattr(module, "load_trend", lambda _: trend)
    (tmp_path / "langfuse_export.json").write_text(
        json.dumps({"destination": destination_fingerprint()})
    )
    store, calls = {}, []
    visible = [False]
    monkeypatch.setattr(
        module, "_remote_scores", lambda *_: store if visible[0] else {}
    )

    def create(request, **kwargs):
        calls.append(request)
        for score in request:
            store[score.id] = {
                "name": score.name,
                "value": score.value,
                "metadata": score.metadata,
                "subject": {"kind": "experiment", "id": score.dataset_run_id},
            }
        return SimpleNamespace()

    client = SimpleNamespace(scores=SimpleNamespace(create=create))
    assert (
        module.sync_trends(tmp_path, [tmp_path], client=client)["status"]
        == "AWAITING_READBACK"
    )
    assert (
        module.sync_trends(tmp_path, [tmp_path], client=client)["status"]
        == "AWAITING_READBACK"
    )
    assert len(calls) == 1
    visible[0] = True
    assert (
        module.sync_trends(tmp_path, [tmp_path], client=client)["status"] == "VERIFIED"
    )
    assert (
        module.sync_trends(tmp_path, [tmp_path], client=client)["status"] == "VERIFIED"
    )
    assert len(calls) == 1
    next(iter(store.values()))["value"] = 123
    assert (
        module.sync_trends(tmp_path, [tmp_path], client=client)["status"]
        == "AWAITING_READBACK"
    )
    assert len(calls) == 1
