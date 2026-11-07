import copy
import json

import pytest

pytest.importorskip("langfuse")


def example():
    analysis = {
        "analysis_id": "a" * 64,
        "source_hash": "s",
        "run_id": "run",
        "rules_version": "v",
        "profile": None,
        "trials": [
            {
                "case_id": "case",
                "trial": 1,
                "operation": "write",
                "category": "gift",
                "verdict": "FAIL",
                "findings": [
                    {
                        "kind": "schema_mismatch",
                        "description": "evidence",
                        "evidence": ["event"],
                        "aliases": {"count": "num"},
                    }
                ],
            }
        ],
    }
    receipt = {
        "source_hash": "s",
        "traces": [{"case_id": "case", "trial": 1, "trace_id": "t", "root_id": "r"}],
    }
    run = {
        "run_id": "run",
        "identity": {"dataset": {"dataset_id": "dataset"}},
        "trials": [
            {"case_id": "case", "trial": 1, "finished_at": "2026-11-07T00:00:00Z"}
        ],
    }
    return run, analysis, receipt


def test_diagnostic_annotations_are_categorical_nonformal_and_deterministic():
    from eval_framework.benchmark.langfuse_presentation import annotation_payload

    run, analysis, receipt = example()
    before = copy.deepcopy((run, analysis, receipt))
    a = annotation_payload(run, analysis, receipt)
    b = annotation_payload(run, analysis, receipt)
    assert [s.model_dump() for s in a] == [s.model_dump() for s in b]
    assert (run, analysis, receipt) == before
    assert len(a) == 2
    assert all(
        s.data_type == "CATEGORICAL" and s.metadata["formal"] is False for s in a
    )
    assert all(s.name.startswith("diagnostic.") and s.observation_id == "r" for s in a)
    analysis["source_hash"] = "changed"
    with pytest.raises(ValueError, match="source"):
        annotation_payload(run, analysis, receipt)


def test_future_tags_propagate_without_modifying_original_metrics():
    from eval_framework.benchmark.langfuse_presentation import enrich_spans
    from eval_framework.observability import _span

    run, analysis, receipt = example()
    spans = [
        _span(
            "t",
            "r",
            "case",
            "2026-11-07T00:00:00Z",
            "2026-11-07T00:00:01Z",
            {"langfuse.observation.metadata": {"original": True}},
        )
    ]
    enriched = enrich_spans(spans, run, analysis, receipt["traces"])
    assert spans[0].name == "case"
    assert enriched[0].name == "dataset / gift / case"
    attributes = {
        a.key: a.value.model_dump(by_alias=True, exclude_none=True)
        for a in enriched[0].attributes
    }
    assert "diagnosis:schema_mismatch" in str(attributes["langfuse.trace.tags"])
    assert (
        json.loads(attributes["langfuse.observation.metadata"]["string_value"])[
            "original"
        ]
        is True
    )


def test_dashboard_uses_formal_verdict_and_scoped_diagnostic_annotations():
    from eval_framework.benchmark.langfuse_presentation import dashboard_widgets

    run, analysis, receipt = example()
    widgets = dashboard_widgets(run, analysis, receipt)
    assert len(widgets) == 3
    assert widgets[0]["view"] == "scores-categorical"
    assert any(f["value"] == "verdict" for f in widgets[0]["filters"])
    for i, w in enumerate(widgets):
        assert any(
            f["column"] == "metadata"
            and f["key"] == ("results_sha256" if i == 0 else "source_hash")
            and f["value"] == "s"
            for f in w["filters"]
        )
    assert any(
        analysis["analysis_id"][:12] in f.get("value", "")
        for f in widgets[2]["filters"]
        if isinstance(f.get("value"), str)
    )


def test_sync_is_idempotent_and_never_resends_unconfirmed_annotations(
    tmp_path, monkeypatch
):
    from hashlib import sha256
    from types import SimpleNamespace

    from eval_framework.benchmark.langfuse_presentation import sync_diagnostics
    from eval_framework.observability import destination_fingerprint

    from .test_report_insights import failure_run, render

    run = failure_run(tmp_path)
    run["trials"][0]["finished_at"] = "2026-11-07T00:00:00Z"
    render(tmp_path, run)
    digest = sha256((tmp_path / "results.json").read_bytes()).hexdigest()
    receipt = {
        "source_hash": digest,
        "destination": destination_fingerprint(),
        "traces": [
            {"case_id": "case-one", "trial": 1, "trace_id": "t", "root_id": "r"}
        ],
    }
    (tmp_path / "langfuse_export.json").write_text(json.dumps(receipt))
    (tmp_path / "langfuse_verification.json").write_text(
        json.dumps({"status": "VERIFIED", "source_hash": digest})
    )
    store = {}
    calls = []
    visible = [False]

    class Scores:
        def get_many(self, **kwargs):
            assert set(kwargs["fields"].split(",")) <= {
                "core",
                "details",
                "subject",
                "annotation",
            }
            return SimpleNamespace(
                data=[SimpleNamespace(model_dump=lambda d=d: d) for d in store.values()]
                if visible[0]
                else [],
                meta=None,
            )

        def create(self, request, **kwargs):
            calls.append(request)
            for score in request:
                store[score.id] = {
                    "id": score.id,
                    "name": score.name,
                    "value": score.value,
                    "subject": {"id": score.observation_id, "trace_id": score.trace_id},
                    "metadata": score.metadata,
                }
            from langfuse.api.scores.types.create_score_batch_response import (
                CreateScoreBatchResponse,
            )

            return CreateScoreBatchResponse()

    client = SimpleNamespace(
        scores=Scores(),
        projects=SimpleNamespace(
            get=lambda: SimpleNamespace(data=[SimpleNamespace(id="p")])
        ),
    )
    assert (
        sync_diagnostics(tmp_path, base_url="https://example.test", client=client)[
            "status"
        ]
        == "AWAITING_READBACK"
    )
    assert (
        sync_diagnostics(tmp_path, base_url="https://example.test", client=client)[
            "status"
        ]
        == "AWAITING_READBACK"
    )
    assert len(calls) == 1
    visible[0] = True
    assert (
        sync_diagnostics(tmp_path, base_url="https://example.test", client=client)[
            "status"
        ]
        == "VERIFIED"
    )
    assert (
        sync_diagnostics(tmp_path, base_url="https://example.test", client=client)[
            "status"
        ]
        == "VERIFIED"
    )
    assert len(calls) == 1


def test_dashboard_sdk_definition_and_resume_do_not_duplicate_widgets(tmp_path):
    from types import SimpleNamespace

    from eval_framework.benchmark.langfuse_presentation import create_dashboard
    from eval_framework.observability import destination_fingerprint

    run, analysis, receipt = example()
    for name, value in (
        ("results.json", run),
        ("diagnostics.json", analysis),
        ("langfuse_export.json", receipt),
        (
            "langfuse_diagnostics_export.json",
            {
                "status": "VERIFIED",
                "analysis_id": analysis["analysis_id"],
                "destination": destination_fingerprint(),
                "project_id": "p",
            },
        ),
    ):
        (tmp_path / name).write_text(json.dumps(value))
    dashboards, widgets = [], []
    definitions = {}

    def create_dash(**kwargs):
        row = SimpleNamespace(id="d", name=kwargs["name"])
        dashboards.append(row)
        return row

    def create_widget(**kwargs):
        row = SimpleNamespace(id="w" + str(len(widgets)), name=kwargs["name"])
        widgets.append(row)
        return row

    def update(did, definition, **kwargs):
        assert len(definition.widgets) == 3
        assert [w.widget_id for w in definition.widgets] == ["w0", "w1", "w2"]
        definitions[did] = definition

    client = SimpleNamespace(
        unstable=SimpleNamespace(
            dashboards=SimpleNamespace(
                list=lambda **k: SimpleNamespace(data=dashboards),
                create=create_dash,
                update=update,
                get=lambda did: SimpleNamespace(definition=definitions[did]),
            ),
            dashboard_widgets=SimpleNamespace(
                list=lambda **k: SimpleNamespace(data=widgets), create=create_widget
            ),
        )
    )
    assert (
        create_dashboard(tmp_path, base_url="https://example.test", client=client)[
            "status"
        ]
        == "VERIFIED"
    )
    assert (
        create_dashboard(tmp_path, base_url="https://example.test", client=client)[
            "status"
        ]
        == "VERIFIED"
    )
    assert len(dashboards) == 1 and len(widgets) == 3
