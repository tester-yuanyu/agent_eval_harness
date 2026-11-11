from copy import deepcopy

from eval_framework.benchmark.report_evaluation import evaluation_summary


def partitions():
    from .test_evaluation_views import event, row

    a, b = row(), row("b", "module")
    a["assessment"]["metrics"] = [
        {
            "name": "response_groundedness",
            "status": "SCORED",
            "score": 0.75,
            "judge_repeat": 1,
        }
    ]
    a["observation"]["events"] = [event(), event(True)]
    return evaluation_summary({"trials": [a, b]}, {})


def test_partition_summary_shared_with_dashboard():
    from eval_framework.benchmark.dashboard_evaluation import display_statistics

    result = display_statistics(partitions())
    assert result["agent.pass_rate_percent"] == 100
    assert result["deterministic.trials"] == 1
    assert result["agent.calls"] == 1
    assert result["judge.calls"] == 1
    assert result["geval.response_groundedness.mean"] == 0.75
    assert result["geval.scored"] == 1


def test_v4_reuses_widgets_without_mixed_rate_or_fake_trend():
    from eval_framework.benchmark.dashboard_evaluation import display_statistics
    from eval_framework.benchmark.langfuse_explorer import (
        arrange_widgets,
        explorer_widgets,
        summary_payload,
    )

    from .test_langfuse_explorer import example

    x = example()
    x["evaluation"] = partitions()
    x["stats"].update(
        {"evaluation." + k: v for k, v in display_statistics(x["evaluation"]).items()}
    )
    original = deepcopy(x)
    widgets = explorer_widgets(x, "cohort")
    keys = {w["key"] for w in widgets}
    assert "evaluation:agent.pass_rate_percent" in keys
    assert "evaluation:geval.response_groundedness.mean" in keys
    assert "health:pass_rate_percent" not in keys
    assert not any(k.startswith("trend:") for k in keys)
    payload = summary_payload(x, "cohort")
    score = next(s for s in payload if s.name == "display.v1.evaluation.agent.calls")
    assert score.value == 1 and score.metadata["formal"] is False
    ids = {w["key"]: str(i) for i, w in enumerate(widgets)}
    layout = arrange_widgets("dashboard", ["old0", "old1", "old2"], widgets, ids)
    assert ids["evaluation:geval.response_groundedness.mean"] in {
        w["widget_id"] for w in layout
    }
    assert x == original
    for a in layout:
        for b in layout:
            if a is not b:
                assert (
                    a["x"] + a["width"] <= b["x"]
                    or b["x"] + b["width"] <= a["x"]
                    or a["y"] + a["height"] <= b["y"]
                    or b["y"] + b["height"] <= a["y"]
                )


def test_large_category_filter_has_bounded_url_and_exact_scope():
    import json
    from urllib.parse import quote

    from eval_framework.benchmark.langfuse_explorer import explorer_widgets

    from .test_langfuse_explorer import example

    x = example()
    name = next(iter(x["categories"]))
    d = {"kind": "category", "name": name, "case_ids": []}
    x["drilldowns"] = [d]
    d["root_names"] = ["dataset / schema / " + str(i) * 50 for i in range(233)]
    widget = next(
        w for w in explorer_widgets(x, "cohort") if w["key"] == "category:" + d["name"]
    )
    filters = widget["spec"]["filters"]
    assert len(quote(json.dumps(filters))) < 2000
    assert any(f.get("key") == "category" and f["value"] == d["name"] for f in filters)
    assert any(f.get("key") == "results_sha256" for f in filters)
    assert any(f["column"] == "type" and f["value"] == ["AGENT"] for f in filters)


def test_dashboard_delivery_preserves_source_and_reports_partial_failure(
    tmp_path, monkeypatch
):
    import hashlib
    import json
    from types import SimpleNamespace

    from eval_framework.benchmark import dashboard_delivery as module
    from eval_framework.benchmark import langfuse_explorer as explorer
    from eval_framework.benchmark import langfuse_presentation as presentation

    source = tmp_path / "source"
    source.mkdir()
    raw = json.dumps(
        {"run_id": "saved", "trials": [{"case_id": "a", "trial": 1}]}
    ).encode()
    (source / "results.json").write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    for name, data in [
        ("langfuse_export.json", {"source_hash": sha, "destination": "target"}),
        ("langfuse_verification.json", {"source_hash": sha, "status": "VERIFIED"}),
    ]:
        (source / name).write_text(json.dumps(data))
    monkeypatch.setattr(module, "load_links", lambda root: {("a", 1): "link"})
    monkeypatch.setattr(module, "write_report", lambda *a, **k: None)
    monkeypatch.setattr(
        explorer, "verify_display_metrics", lambda *a, **k: {"status": "VERIFIED"}
    )
    calls = []

    def diagnostics(root, **kwargs):
        assert root != source and kwargs["destination"] == "target"
        calls.append("diagnostics")
        return {"status": "VERIFIED"}

    monkeypatch.setattr(presentation, "sync_diagnostics", diagnostics)
    monkeypatch.setattr(
        presentation,
        "create_dashboard",
        lambda *a, **k: calls.append("dashboard") or {"status": "VERIFIED"},
    )
    monkeypatch.setattr(
        explorer, "sync_explorer", lambda *a, **k: {"status": "AWAITING_READBACK"}
    )
    profile = SimpleNamespace(
        destination=lambda: "target", base_url="https://example.test", project_id="p"
    )
    state = module.deliver_dashboard(source, profile=profile, client=object())
    assert state["data_status"] == "VERIFIED"
    assert state["dashboard_status"] == "AWAITING_READBACK"
    assert state["delivery_status"] != "COMPLETE"
    monkeypatch.setattr(
        explorer,
        "sync_explorer",
        lambda *a, **k: {
            "status": "VERIFIED",
            "dashboard_status": "VERIFIED",
            "dashboard_url": "https://example.test/dashboard",
        },
    )
    state = module.deliver_dashboard(source, profile=profile, client=object())
    assert state["delivery_status"] == "COMPLETE"
    assert state["dashboard_url"] == "https://example.test/dashboard"
    assert (source / "results.json").read_bytes() == raw
    assert not (source / "langfuse_dashboard.json").exists()


def test_root_filter_verification_reads_every_page():
    from types import SimpleNamespace

    from eval_framework.benchmark.langfuse_explorer import observation_ids

    seen = []

    def read(**kwargs):
        seen.append(kwargs.get("cursor"))
        return SimpleNamespace(
            data=[SimpleNamespace(id="a" if len(seen) == 1 else "b")],
            meta=SimpleNamespace(cursor="next" if len(seen) == 1 else None),
        )

    client = SimpleNamespace(observations=SimpleNamespace(get_many=read))
    assert observation_ids(client, []) == {"a", "b"}
    assert seen == [None, "next"]


def test_formal_sync_keeps_data_and_dashboard_status_separate(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from eval_framework.benchmark import dashboard_delivery as presentation
    from eval_framework.benchmark import langfuse_delivery as delivery
    from eval_framework.benchmark import langfuse_export as exporter

    (tmp_path / "results.json").write_text("{}")
    monkeypatch.setattr(exporter, "export_run", lambda *a, **k: None)
    monkeypatch.setattr(exporter, "export_metadata_evidence", lambda *a, **k: None)
    monkeypatch.setattr(exporter, "verify_run", lambda *a, **k: {"status": "VERIFIED"})
    monkeypatch.setattr(
        presentation,
        "deliver_dashboard",
        lambda *a, **k: {
            "dashboard_status": "FAILED",
            "delivery_status": "PENDING_DASHBOARD",
        },
    )
    result = delivery.sync_run(
        tmp_path,
        tmp_path,
        profile=SimpleNamespace(profile="cloud", intervals={}),
        client=SimpleNamespace(),
        destination="d",
        sleep=lambda _: None,
        dashboard=True,
    )
    assert result["sync_status"] == "VERIFIED"
    assert result["dashboard_status"] == "FAILED"
    assert result["delivery_status"] == "PENDING_DASHBOARD"
    assert json.loads((tmp_path / "langfuse_delivery.json").read_text()) == result


def test_explicit_destination_survives_global_environment_changes(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from eval_framework.benchmark import langfuse_explorer as module

    from .test_langfuse_explorer import example

    store = {}
    writes = []
    monkeypatch.setattr(module, "_remote_scores", lambda *_: store)

    def create(request, **kwargs):
        writes.append(request)
        for s in request:
            store[s.id] = {
                "name": s.name,
                "value": s.value,
                "metadata": s.metadata,
                "subject": {"kind": "experiment", "id": s.dataset_run_id},
            }
        return SimpleNamespace()

    client = SimpleNamespace(scores=SimpleNamespace(create=create))
    for default in ["global-one", "global-two"]:
        monkeypatch.setattr(
            module, "destination_fingerprint", lambda default=default: default
        )
        result = module.sync_summaries(
            tmp_path, [example()], "cohort", client, destination="explicit"
        )
        assert result["status"] == "VERIFIED" and result["destination"] == "explicit"
    assert len(writes) == 1


def test_metrics_readback_requires_actual_aggregates_not_just_widget_definitions(
    tmp_path, monkeypatch
):
    import json
    from types import SimpleNamespace

    from eval_framework.benchmark import langfuse_explorer as module

    from .test_langfuse_explorer import example

    x = example()
    x["date_range"] = [1794000000000, 1794100000000]
    monkeypatch.setattr(module, "build_explorer", lambda _: x)
    state = {"cohort_id": "cohort", "view_id": "view", "status": "VERIFIED"}
    (tmp_path / "langfuse_explorer_export.json").write_text(json.dumps(state))
    scores = module.summary_payload(x, "cohort", "view")
    rows = [{"name": s.name, "avg_value": s.value, "count_count": 1} for s in scores]
    client = SimpleNamespace(
        metrics=SimpleNamespace(metrics=lambda **kwargs: SimpleNamespace(data=rows))
    )
    assert (
        module.verify_display_metrics(tmp_path, client=client)["status"] == "VERIFIED"
    )
    rows[0]["count_count"] = 2
    assert (
        module.verify_display_metrics(tmp_path, client=client)["status"] == "MISMATCH"
    )
