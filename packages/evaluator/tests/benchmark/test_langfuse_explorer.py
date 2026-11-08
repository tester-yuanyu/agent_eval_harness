import pytest

pytest.importorskip("langfuse")


def example():
    return {
        "explorer_id": "e",
        "source_hash": "s",
        "destination": "d",
        "run_id": "r",
        "experiment_id": "exp",
        "finished_at": "2026-11-07T00:00:00Z",
        "stats": {
            "trial_count": 30,
            "latency_mean_seconds": 25,
            "latency_p50_seconds": 24,
            "latency_p95_seconds": 81,
            "total_tokens": 100,
            "tool_calls_mean": 0.5,
            "actual_cost_usd": None,
            "input_tokens": 80,
            "output_tokens": 20,
            "cached_input_tokens": 30,
        },
        "estimate": {
            "low": 0.1,
            "high": 0.2,
            "pricing": {"kind": "subscription_allowance"},
        },
        "categories": {"write": {"passed": 0, "total": 3, "pass_rate_percent": 0}},
        "formal_metrics": {"status_match": {"count": 3, "values": [0, 1, 1]}},
        "drilldowns": [
            {
                "kind": "issue",
                "name": "schema_mismatch",
                "root_ids": ["a", "b"],
                "case_ids": ["case-a", "case-b"],
                "count": 2,
                "url": "https://example.test/list",
            }
        ],
    }


def test_health_summaries_are_nonformal_and_do_not_invent_actual_cost():
    from eval_framework.benchmark.langfuse_explorer import (
        explorer_widgets,
        summary_payload,
    )

    x = example()
    scores = summary_payload(x, "cohort")
    assert all(
        s.metadata["formal"] is False
        and s.dataset_run_id == "exp"
        and s.trace_id is None
        for s in scores
    )
    assert not any(s.name.endswith("actual_cost_usd") for s in scores)
    assert any(s.name.endswith("estimate_low_usd") and s.value == 0.1 for s in scores)
    widgets = explorer_widgets(x, "cohort")
    issue = next(w for w in widgets if w["key"] == "issue:schema_mismatch")["spec"]
    assert issue["view"] == "observations"
    assert issue["filters"][0]["value"] == ["case-a", "case-b"]
    assert issue["filters"][1]["key"] == "results_sha256"
    assert issue["filters"][2]["value"] == ["AGENT"]
    assert issue["chart_type"] == "NUMBER"
    for w in widgets:
        if w["key"].startswith("trend:"):
            assert not any(f.get("key") == "source_hash" for f in w["spec"]["filters"])
    histogram = next(w for w in widgets if w["key"] == "scores:status_match")["spec"]
    assert histogram["metrics"] == [{"measure": "count", "agg": "count"}]
    assert histogram["dimensions"] == [{"field": "value"}]
    assert histogram["chart_type"] == "HORIZONTAL_BAR"
    assert any(
        f.get("key") == "results_sha256" and f["value"] == "s"
        for f in histogram["filters"]
    )


def test_layout_keeps_existing_widgets_and_places_cards_first_without_overlap():
    from eval_framework.benchmark.langfuse_explorer import (
        arrange_widgets,
        explorer_widgets,
    )

    x = example()
    extras = explorer_widgets(x, "cohort")
    ids = {e["key"]: "id" + str(i) for i, e in enumerate(extras)}
    items = arrange_widgets("d", ["old0", "old1", "old2", "old3"], extras, ids)
    assert len({i["widget_id"] for i in items}) == len(items)
    assert {i["widget_id"] for i in items} >= {"old1", "old2", "old3"}
    for a in items:
        for b in items:
            if a is not b:
                assert (
                    a["x"] + a["width"] <= b["x"]
                    or b["x"] + b["width"] <= a["x"]
                    or a["y"] + a["height"] <= b["y"]
                    or b["y"] + b["height"] <= a["y"]
                )


def test_summary_sync_does_not_resend_unconfirmed_writes(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from eval_framework.benchmark import langfuse_explorer as module

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
    for _ in range(2):
        assert (
            module.sync_summaries(tmp_path, [example()], "cohort", client)["status"]
            == "AWAITING_READBACK"
        )
    assert len(calls) == 1
    visible[0] = True
    assert (
        module.sync_summaries(tmp_path, [example()], "cohort", client)["status"]
        == "VERIFIED"
    )
    assert len(calls) == 1
    changed = example()
    changed["explorer_id"] = "new snapshot"
    old_ids = set(store)
    assert (
        module.sync_summaries(tmp_path, [changed], "cohort", client)["status"]
        == "VERIFIED"
    )
    assert len(calls) == 2 and set(store) > old_ids
    for row in store.values():
        row["value"] = 999
    with pytest.raises(ValueError, match="content mismatch"):
        module.sync_summaries(tmp_path, [changed], "cohort", client)


def test_refresh_preserves_user_widgets_and_text():
    from eval_framework.benchmark.langfuse_explorer import preserve_unmanaged

    current = {
        "widgets": [
            {"widget_id": "owned", "y": 0, "height": 2},
            {"widget_id": "user", "y": 2, "height": 3},
            {"type": "text", "y": 5, "height": 1, "text": "note"},
        ]
    }
    new = [{"widget_id": "owned", "y": 0, "height": 8}]
    result = preserve_unmanaged(current, new, {"owned"})
    assert [w["y"] for w in result["widgets"]] == [0, 8, 11]
    assert result["widgets"][-1]["text"] == "note"
    assert current["widgets"][1]["y"] == 2


def test_score_readback_follows_current_sdk_cursor():
    from types import SimpleNamespace

    from eval_framework.benchmark.langfuse_presentation import _remote_scores

    class Row:
        def __init__(self, **data):
            self.data = data

        def model_dump(self):
            return self.data

    calls = []

    def get_many(**kwargs):
        calls.append(kwargs)
        if not kwargs.get("cursor"):
            return SimpleNamespace(data=[Row(id="a")], meta=Row(cursor="next"))
        return SimpleNamespace(data=[Row(id="b")], meta=Row(cursor=None))

    client = SimpleNamespace(scores=SimpleNamespace(get_many=get_many))
    assert set(_remote_scores(client, ["a", "b"])) == {"a", "b"}
    assert calls[1]["cursor"] == "next"


def test_sdk_pacing_is_shared_across_endpoints(monkeypatch):
    from types import SimpleNamespace

    from eval_framework.benchmark import langfuse_explorer as module

    now, waits, calls = [100.0], [], []
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])

    def sleep(delay):
        waits.append(delay)
        now[0] += delay

    monkeypatch.setattr(module.time, "sleep", sleep)
    client = module._PacedClient(
        SimpleNamespace(
            scores=SimpleNamespace(get=lambda: calls.append("scores")),
            observations=SimpleNamespace(get=lambda: calls.append("observations")),
        )
    )
    client.scores.get()
    client.observations.get()
    assert calls == ["scores", "observations"]
    assert waits == pytest.approx([2.1])


def test_reading_order_layout_keeps_six_groups_and_hides_redundant_cards():
    from eval_framework.benchmark.langfuse_explorer import arrange_widgets

    groups = ["chain", "user", "gift", "read", "confirmation", "write"]
    keys = [
        "health:trial_count",
        "health:pass_rate_percent",
        "health:latency_mean_seconds",
        "health:latency_p95_seconds",
        "health:total_tokens",
        "health:estimate",
        "trend:latency",
        "trend:tokens",
        "trend:cost",
        "families",
        "issue:schema_mismatch",
        "issue:missing_confirmation_context",
        "issue:business_failure_status",
        "issue:restricted_response",
        *["category:" + g for g in groups],
        "scores:status_match",
        "scores:intent_match",
        "scores:tool_args_match",
    ]
    ids = {k: k for k in keys} | {"health:tool_calls_mean": "old-tool-card"}
    rows = arrange_widgets(
        "d",
        ["donut", "readwrite", "diagnosis", "pass_trend"],
        [{"key": k} for k in keys],
        ids,
        groups,
    )
    by_id = {r["widget_id"]: r for r in rows}
    assert len(rows) == 25
    assert "families" not in by_id and "old-tool-card" not in by_id
    assert {by_id[k]["y"] for k in keys[:6]} == {0}
    assert [by_id[k]["x"] for k in keys[:6]] == [0, 2, 4, 6, 8, 10]
    assert "donut" not in by_id
    assert by_id["readwrite"]["y"] == 2
    assert by_id["readwrite"]["width"] == 12
    assert {
        by_id[k]["y"]
        for k in ["pass_trend", "trend:latency", "trend:tokens", "trend:cost"]
    } == {7}
    assert by_id["diagnosis"]["width"] == 8
    assert [by_id["category:" + g]["x"] for g in groups] == [0, 2, 4, 6, 8, 10]
    assert {by_id["category:" + g]["y"] for g in groups} == {19}
    assert [
        by_id[k]["x"]
        for k in [
            "scores:status_match",
            "scores:intent_match",
            "scores:tool_args_match",
        ]
    ] == [0, 4, 8]


def test_pass_rate_card_uses_saved_verdict_denominator():
    from eval_framework.benchmark.langfuse_explorer import (
        explorer_widgets,
        summary_payload,
    )

    x = example()
    x["categories"] = {
        "read": {"passed": 18, "total": 20, "pass_rate_percent": 90},
        "write": {"passed": 1, "total": 10, "pass_rate_percent": 10},
    }
    cards = {w["key"]: w for w in explorer_widgets(x, "c")}
    assert "health:tool_calls_mean" not in cards
    assert "19/30 PASS" in cards["health:pass_rate_percent"]["spec"]["description"]
    score = next(
        s for s in summary_payload(x, "c") if s.name.endswith("pass_rate_percent")
    )
    assert score.value == pytest.approx(100 * 19 / 30)
    assert score.metadata["formal"] is False
