"""Local delivery uses the real SDK with only its HTTP transport replaced."""

import json
from pathlib import Path

import httpx
import pytest
from test_comparison import loaded

pytest.importorskip("langfuse", reason="requires agent-evaluator[langfuse]")


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "local.json"
    path.write_text(
        json.dumps(
            {
                "enabled": True,
                "base_url": "http://127.0.0.1:3000",
                "project_id": "local-project",
                "public_key": "local-public",
                "secret_key": "local-secret",
                "state_dir": str(tmp_path / "state"),
            }
        )
    )
    return path


@pytest.fixture
def run_dir(tmp_path, case_result_factory):
    root = tmp_path / "run"
    root.mkdir()
    (root / "results.json").write_text(
        loaded(case_result_factory()).result.model_dump_json()
    )
    (root / "report.md").write_text("Original formal report\n")
    return root


@pytest.fixture
def server(monkeypatch):
    requests = []
    objects = {"dashboards": {}, "dashboard-widgets": {}}
    failure = {"path": None, "mode": "timeout"}

    def handler(_transport, request):
        requests.append(request)
        assert request.url.host == "127.0.0.1"
        if failure["path"] and failure["path"] in request.url.path:
            if failure["mode"] == "redirect":
                return httpx.Response(
                    307,
                    headers={
                        "location": "https://cloud.langfuse.com/api/public/projects"
                    },
                    request=request,
                )
            if failure["mode"] == "connect":
                raise httpx.ConnectError(
                    "local-secret local-public PRIVATE", request=request
                )
            raise httpx.ReadTimeout(
                "local-secret local-public PRIVATE", request=request
            )
        if request.url.path.endswith("/projects"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "local-project",
                            "name": "Local",
                            "organization": {"id": "org", "name": "Local"},
                            "metadata": {},
                        }
                    ]
                },
                request=request,
            )
        if "otel" in request.url.path:
            return httpx.Response(200, json={}, request=request)
        if "scores" in request.url.path:
            return httpx.Response(202, json={"message": "Accepted"}, request=request)
        for kind, items in objects.items():
            if f"/{kind}" not in request.url.path:
                continue
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "data": list(items.values()),
                        "meta": {
                            "page": 1,
                            "limit": 100,
                            "totalItems": len(items),
                            "totalPages": 1,
                        },
                    },
                    request=request,
                )
            body = json.loads(request.content)
            key = (
                request.url.path.rsplit("/", 1)[-1]
                if request.method in {"PUT", "PATCH"}
                else f"{kind}-{len(items) + 1}"
            )
            value = {
                "id": key,
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-01T00:00:00Z",
                **body,
            }
            value.setdefault("filters", [])
            if kind == "dashboard-widgets":
                value["chartConfig"] = {
                    "type": body["chartType"],
                    **body.get("chartConfig", {}),
                }
            items[key] = value
            return httpx.Response(200, json=value, request=request)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handler)
    return requests, objects, failure


def test_disabled_does_not_use_cloud_or_touch_reports(tmp_path, run_dir, monkeypatch):
    from eval_framework.local_delivery import finalize_delivery

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_EVALUATOR_LOCAL_LANGFUSE_CONFIG", raising=False)
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "cloud-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "cloud-secret")
    before = list(run_dir.iterdir())
    assert finalize_delivery(run_dir) == {"status": "DISABLED"}
    assert list(run_dir.iterdir()) == before


@pytest.mark.parametrize(
    "url",
    [
        "https://cloud.langfuse.com",
        "http://127.0.0.1.evil.test",
        "http://192.168.1.2:3000",
        "http://user:pass@127.0.0.1:3000",
        "http://127.0.0.1:3000/?token=secret",
    ],
)
def test_nonloopback_or_ambiguous_config_is_rejected_before_network(
    config, run_dir, server, url
):
    from eval_framework.local_delivery import finalize_delivery

    data = json.loads(config.read_text())
    data["base_url"] = url
    config.write_text(json.dumps(data))
    result = finalize_delivery(run_dir, config_path=config)
    assert result["status"] == "CONFIG_ERROR"
    assert server[0] == []
    assert "secret" not in json.dumps(result)


def test_success_is_target_specific_immutable_scoped_and_idempotent(
    config, run_dir, server, monkeypatch
):
    from eval_framework.local_delivery import finalize_delivery

    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "cloud-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "cloud-secret")
    (run_dir / "langfuse_export.json").write_text('{"historical": "cloud"}')
    formal = {p: p.read_bytes() for p in run_dir.iterdir()}
    result = finalize_delivery(run_dir, config_path=config)
    assert result["status"] == "ACCEPTED"
    assert result["dashboard_url"].startswith(
        "http://127.0.0.1:3000/project/local-project/dashboards/"
    )
    assert Path(result["report_path"]).is_file()
    assert result["dashboard_url"] in Path(result["report_path"]).read_text()
    assert all(p.read_bytes() == value for p, value in formal.items())
    assert server[1]["dashboard-widgets"]
    for widget in server[1]["dashboard-widgets"].values():
        filters = widget["filters"]
        assert any(f["column"] == "Metadata" and f["key"] == "run_id" for f in filters)
        assert any(
            f["column"] == "Metadata" and f["key"] == "results_sha256" for f in filters
        )
        assert any(f["column"] == "Score Name" for f in filters)
    count = len(server[0])
    before_widgets = len(server[1]["dashboard-widgets"])
    repeated = finalize_delivery(run_dir, config_path=config)
    assert repeated["dashboard_url"] == result["dashboard_url"]
    assert len(server[1]["dashboards"]) == 1
    assert len(server[1]["dashboard-widgets"]) == before_widgets
    assert not any("otel" in r.url.path for r in server[0][count:])
    persisted = Path(result["receipt_path"]).read_text()
    assert "local-secret" not in persisted and "cloud-secret" not in persisted
    import os

    assert os.environ["LANGFUSE_BASE_URL"] == "https://cloud.langfuse.com"


@pytest.mark.parametrize("kind", ["intake", "invalid_run"])
def test_status_only_sources_do_not_fabricate_trials_or_quality(
    config, tmp_path, server, kind
):
    from eval_framework.local_delivery import finalize_delivery

    source = tmp_path / f"{kind}.json"
    source.write_text(
        json.dumps(
            {
                "counts": {"static": 0, "behavior": 0, "blocked": 276},
                "release_eligible": False,
                "source_state": "DRAFT",
                "runs": [],
                "cases": [
                    {
                        "disposition": "blocked",
                        "reason_code": "MISSING_EXECUTABLE_CONTRACT",
                    }
                ],
            }
            if kind == "intake"
            else {
                "verdict": "INVALID_RUN",
                "error_code": "PREFLIGHT_ERROR",
                "message": "PRIVATE secret",
            }
        )
    )
    result = finalize_delivery(source, config_path=config)
    assert result["status"] == "ACCEPTED"
    assert not any("otel" in r.url.path or "scores" in r.url.path for r in server[0])
    assert not server[1]["dashboard-widgets"]
    assert "dateRange=" not in result["dashboard_url"]
    description = next(iter(server[1]["dashboards"].values()))["description"]
    assert "not applicable" in description
    assert ("276" if kind == "intake" else "INVALID_RUN") in description
    assert "PRIVATE" not in description


def test_partial_candidate_retains_saved_partition_and_error_status(
    config, run_dir, tmp_path, server
):
    from eval_framework.local_delivery import finalize_delivery

    source = tmp_path / "intake.json"
    source.write_text(
        json.dumps(
            {
                "counts": {"static": 1, "behavior": 1, "blocked": 2},
                "source_state": "DRAFT",
                "release_eligible": False,
                "runs": [
                    {"partition": "static", "paths": {"output_dir": str(run_dir)}},
                    {
                        "partition": "behavior",
                        "error": {"error_type": "RuntimeError", "message": "PRIVATE"},
                    },
                ],
            }
        )
    )
    result = finalize_delivery(source, config_path=config)
    assert result["status"] == "ACCEPTED"
    description = next(iter(server[1]["dashboards"].values()))["description"]
    assert "static" in description and "behavior" in description
    assert "RuntimeError" in description and "PRIVATE" not in description
    assert "release_eligible=false" in description
    assert all(
        w["name"].startswith("static") for w in server[1]["dashboard-widgets"].values()
    )


def test_project_redirect_does_not_escape_loopback(config, run_dir, server):
    from eval_framework.local_delivery import finalize_delivery

    server[2].update(path="projects", mode="redirect")
    result = finalize_delivery(run_dir, config_path=config)
    assert result["status"] == "PENDING"
    assert len(server[0]) == 1
    assert not server[1]["dashboards"]


def test_pending_connection_failure_retries_without_rerunning_agent(
    config, run_dir, tmp_path, server
):
    from eval_framework.local_delivery import finalize_delivery

    server[2].update(path="projects", mode="connect")
    pending = finalize_delivery(run_dir, config_path=config)
    assert pending["status"] == "PENDING"
    assert "local-secret" not in json.dumps(pending)
    assert "PRIVATE" not in Path(pending["receipt_path"]).read_text()
    server[2]["path"] = None
    invalid = tmp_path / "invalid_run.json"
    invalid.write_text('{"verdict": "INVALID_RUN", "error_code": "PRECHECK"}')
    finalize_delivery(invalid, config_path=config)
    assert json.loads(Path(pending["receipt_path"]).read_text())["status"] == "ACCEPTED"
    assert len(server[1]["dashboards"]) == 2


def test_uncertain_ingestion_is_never_replayed(config, run_dir, server):
    from eval_framework.local_delivery import finalize_delivery

    server[2].update(path="otel", mode="timeout")
    result = finalize_delivery(run_dir, config_path=config)
    assert result["status"] == "RECONCILIATION_REQUIRED"
    count = len(server[0])
    server[2]["path"] = None
    repeated = finalize_delivery(run_dir, config_path=config)
    assert repeated["status"] == "RECONCILIATION_REQUIRED"
    assert not any("otel" in r.url.path for r in server[0][count:])


def test_uncertain_dashboard_create_does_not_duplicate(config, tmp_path, server):
    from eval_framework.local_delivery import finalize_delivery

    source = tmp_path / "invalid_run.json"
    source.write_text('{"verdict": "INVALID_RUN", "error_code": "PRECHECK"}')
    server[2].update(path="dashboards", mode="timeout")
    first = finalize_delivery(source, config_path=config)
    assert first["status"] == "RECONCILIATION_REQUIRED"
    count = len(server[0])
    server[2]["path"] = None
    second = finalize_delivery(source, config_path=config)
    assert second["status"] == "RECONCILIATION_REQUIRED"
    assert not any(r.method == "POST" for r in server[0][count:])


def test_config_precedence_and_proxy_environment_are_isolated(
    config, run_dir, server, monkeypatch, tmp_path
):
    from eval_framework.local_delivery import finalize_delivery

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.langfuse.local.json").write_text('{"enabled": false}')
    monkeypatch.setenv("AGENT_EVALUATOR_LOCAL_LANGFUSE_CONFIG", str(config))
    monkeypatch.setenv("HTTP_PROXY", "http://outside-proxy.example:8080")
    transports = []
    original = httpx.HTTPTransport.__init__

    def transport_init(self, *args, **kwargs):
        transports.append(kwargs.get("proxy"))
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.HTTPTransport, "__init__", transport_init)
    assert finalize_delivery(run_dir)["status"] == "ACCEPTED"
    assert transports and all(proxy is None for proxy in transports)
    disabled = tmp_path / "disabled.json"
    disabled.write_text('{"enabled": false}')
    count = len(server[0])
    assert finalize_delivery(run_dir, config_path=disabled) == {"status": "DISABLED"}
    assert len(server[0]) == count


def test_wrong_project_cannot_receive_observations(config, run_dir, server):
    from eval_framework.local_delivery import finalize_delivery

    values = json.loads(config.read_text())
    values["project_id"] = "wrong-project"
    config.write_text(json.dumps(values))
    result = finalize_delivery(run_dir, config_path=config)
    assert result["status"] == "PENDING"
    assert all(request.method == "GET" for request in server[0])


def test_known_connection_failure_during_create_is_retryable(config, tmp_path, server):
    from eval_framework.local_delivery import finalize_delivery

    source = tmp_path / "invalid_run.json"
    source.write_text('{"verdict":"INVALID_RUN","error_code":"PRECHECK"}')
    server[2].update(path="dashboards", mode="connect")
    first = finalize_delivery(source, config_path=config)
    assert first["status"] == "PENDING"
    server[2]["path"] = None
    assert finalize_delivery(source, config_path=config)["status"] == "ACCEPTED"
    assert len(server[1]["dashboards"]) == 1


def test_bad_pending_item_does_not_replace_current_success(
    config, run_dir, server, tmp_path
):
    from eval_framework.local_delivery import finalize_delivery

    server[2].update(path="projects", mode="connect")
    pending = finalize_delivery(run_dir, config_path=config)
    (run_dir / "results.json").unlink()
    server[2]["path"] = None
    source = tmp_path / "invalid_run.json"
    source.write_text('{"verdict":"INVALID_RUN","error_code":"PRECHECK"}')
    current = finalize_delivery(source, config_path=config)
    assert current["status"] == "ACCEPTED"
    assert current["dashboard_url"]
    assert json.loads(Path(pending["receipt_path"]).read_text())["status"] == "PENDING"


def test_pending_queue_is_bounded(config, tmp_path, server):
    from eval_framework.local_delivery import finalize_delivery

    server[2].update(path="projects", mode="connect")
    for index in range(5):
        root = tmp_path / f"failed-{index}"
        root.mkdir()
        source = root / "invalid_run.json"
        source.write_text('{"verdict":"INVALID_RUN","error_code":"PRECHECK"}')
        assert finalize_delivery(source, config_path=config)["status"] == "PENDING"
    server[2]["path"] = None
    current = tmp_path / "invalid_run.json"
    current.write_text('{"verdict":"INVALID_RUN","error_code":"PRECHECK"}')
    assert finalize_delivery(current, config_path=config)["status"] == "ACCEPTED"
    assert len(server[1]["dashboards"]) == 4
    assert len(list((tmp_path / "state").glob("*/pending-*.json"))) == 2


def test_saved_provisional_and_hash_bound_gate_are_displayed(config, run_dir, server):
    import hashlib

    from eval_framework.local_delivery import finalize_delivery

    (run_dir / "summary.json").write_text('{"provisional":true}')
    (run_dir / "gate.json").write_text(
        json.dumps(
            {
                "candidate_sha256": hashlib.sha256(
                    (run_dir / "results.json").read_bytes()
                ).hexdigest(),
                "conclusion": "FAIL",
                "checks": [{"code": "CRITICAL_FAILURE", "state": "FAIL"}],
            }
        )
    )
    result = finalize_delivery(run_dir, config_path=config)
    assert result["status"] == "ACCEPTED"
    description = next(iter(server[1]["dashboards"].values()))["description"]
    assert "provisional=true" in description
    assert "saved gate=FAIL" in description and "CRITICAL_FAILURE" in description


def test_source_change_never_reuses_accepted_observations(config, run_dir, server):
    from eval_framework.local_delivery import finalize_delivery

    first = finalize_delivery(run_dir, config_path=config)
    assert first["status"] == "ACCEPTED"
    source = run_dir / "results.json"
    source.write_text(source.read_text() + "\n")
    count = len(server[0])
    second = finalize_delivery(run_dir, config_path=config)
    assert second["status"] == "PENDING"
    assert second["source_sha256"] != first["source_sha256"]
    assert Path(first["receipt_path"]).is_file()
    assert not any("otel" in r.url.path for r in server[0][count:])


def test_recovered_delivery_drops_previous_error_type(config, run_dir, server):
    from eval_framework.local_delivery import finalize_delivery

    server[2].update(path="projects", mode="connect")
    assert finalize_delivery(run_dir, config_path=config)["status"] == "PENDING"
    server[2]["path"] = None
    accepted = finalize_delivery(run_dir, config_path=config)
    assert accepted["status"] == "ACCEPTED"
    assert "error_type" not in accepted
    assert "error_type" not in json.loads(Path(accepted["receipt_path"]).read_text())


def test_uncertain_queue_items_do_not_starve_safe_pending_items(
    config, run_dir, server, tmp_path
):
    from eval_framework.local_delivery import finalize_delivery

    server[2].update(path="projects", mode="connect")
    pending = finalize_delivery(run_dir, config_path=config)
    queued = next((tmp_path / "state").glob("*/pending-*.json"))
    for index in range(3):
        (queued.parent / f"pending-000{index}.json").write_text(
            json.dumps(
                {
                    "source": "/not/read",
                    "source_sha256": "uncertain",
                    "status": "RECONCILIATION_REQUIRED",
                }
            )
        )
    server[2]["path"] = None
    source = tmp_path / "invalid_run.json"
    source.write_text('{"verdict":"INVALID_RUN","error_code":"PRECHECK"}')
    assert finalize_delivery(source, config_path=config)["status"] == "ACCEPTED"
    assert json.loads(Path(pending["receipt_path"]).read_text())["status"] == "ACCEPTED"


def test_source_changed_during_delivery_is_not_uploaded(
    config, run_dir, server, monkeypatch
):
    from eval_framework.local_delivery import finalize_delivery

    original = httpx.HTTPTransport.handle_request

    def change_after_project_check(transport, request):
        response = original(transport, request)
        if request.url.path.endswith("/projects"):
            source = run_dir / "results.json"
            source.write_text(source.read_text() + "\n")
        return response

    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", change_after_project_check
    )
    result = finalize_delivery(run_dir, config_path=config)
    assert result["status"] == "PENDING"
    assert not any("otel" in request.url.path for request in server[0])


def test_large_run_resumes_scores_across_budgets_and_reaches_dashboard(
    config, run_dir, server, monkeypatch
):
    from types import SimpleNamespace

    from eval_framework import local_delivery

    source = run_dir / "results.json"
    data = json.loads(source.read_text())
    case = data["cases"][0]
    data["cases"] = [dict(case, case_id=f"case-{index}") for index in range(1000)]
    data["summary"].update(total_cases=1000, total_trials=1000)
    source.write_text(json.dumps(data))
    formal = source.read_bytes()
    clock = [0.0]
    original = httpx.HTTPTransport.handle_request
    accepted_scores = []

    def slow_scores(transport, request):
        response = original(transport, request)
        if "scores" in request.url.path:
            accepted_scores.extend(score["id"] for score in json.loads(request.content))
            clock[0] += 4
        return response

    monkeypatch.setattr(
        local_delivery, "time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", slow_scores)
    result = local_delivery.finalize_delivery(
        run_dir, config_path=config, retry_pending=False
    )
    assert result["status"] == "PENDING"
    for _ in range(9):
        result = local_delivery.finalize_delivery(
            run_dir, config_path=config, retry_pending=False
        )
        if result["status"] == "ACCEPTED":
            break
    assert result["status"] == "ACCEPTED"
    assert len(accepted_scores) == len(set(accepted_scores))
    assert len(server[1]["dashboards"]) == 1
    count = len(accepted_scores)
    repeated = local_delivery.finalize_delivery(
        run_dir, config_path=config, retry_pending=False
    )
    assert repeated["status"] == "ACCEPTED"
    assert len(accepted_scores) == count
    assert source.read_bytes() == formal


def test_dashboard_link_uses_saved_run_dates_instead_of_today(config, run_dir, server):
    from urllib.parse import parse_qs, urlsplit

    from eval_framework.local_delivery import finalize_delivery

    result = finalize_delivery(run_dir, config_path=config)
    assert result["status"] == "ACCEPTED"
    assert parse_qs(urlsplit(result["dashboard_url"]).query) == {
        "dateRange": ["1767225599000-1767225602000"]
    }
    assert result["dashboard_url"] in Path(result["report_path"]).read_text()


def test_candidate_dates_cover_every_partition_and_title_exposes_scope(
    config, run_dir, tmp_path, server
):
    from urllib.parse import parse_qs, urlsplit

    from eval_framework.local_delivery import finalize_delivery

    (run_dir / "summary.json").write_text('{"provisional":true}')
    second = tmp_path / "behavior"
    second.mkdir()
    data = json.loads((run_dir / "results.json").read_text())
    data.update(
        evaluator_run_id="run-later",
        started_at="2026-01-02T08:00:00+08:00",
        finished_at="2026-01-02T08:00:01+08:00",
    )
    (second / "results.json").write_text(json.dumps(data))
    source = tmp_path / "intake.json"
    source.write_text(
        json.dumps(
            {
                "agent_id": "candidate",
                "counts": {"static": 1, "behavior": 1, "blocked": 276},
                "runs": [
                    {"partition": "behavior", "paths": {"output_dir": str(second)}},
                    {"partition": "static", "paths": {"output_dir": str(run_dir)}},
                ],
            }
        )
    )
    result = finalize_delivery(source, config_path=config)
    assert result["status"] == "ACCEPTED"
    assert parse_qs(urlsplit(result["dashboard_url"]).query) == {
        "dateRange": ["1767225599000-1767312002000"]
    }
    title = next(iter(server[1]["dashboards"].values()))["name"].lower()
    assert "provisional" in title and "blocked 276" in title


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("not-a-date", "2026-01-01T00:00:01Z"),
        ("2026-01-01T00:00:00", "2026-01-01T00:00:01Z"),
        ("2026-01-02T00:00:00Z", "2026-01-01T00:00:01Z"),
    ],
)
def test_invalid_saved_time_does_not_invent_dashboard_date_range(run_dir, start, end):
    from eval_framework.local_delivery import _dashboard_date_range, _source

    source = run_dir / "results.json"
    data = json.loads(source.read_text())
    data.update(started_at=start, finished_at=end)
    source.write_text(json.dumps(data))
    assert _dashboard_date_range(_source(run_dir)) is None


def test_experiment_link_uses_native_results_route_and_replaces_old_receipt_link(
    config, run_dir, server
):
    from urllib.parse import parse_qs, urlsplit

    from eval_framework.local_delivery import finalize_delivery

    result = finalize_delivery(run_dir, config_path=config)
    assert result["status"] == "ACCEPTED"
    exported = json.loads(next(run_dir.glob("langfuse_export.*.json")).read_text())
    link = urlsplit(result["experiment_urls"][0])
    assert link.path == "/project/local-project/experiments/results"
    assert parse_qs(link.query) == {"baseline": [exported["experiment_id"]]}
    record = Path(result["receipt_path"])
    previous = json.loads(record.read_text())
    broken = "http://127.0.0.1:3000/project/local-project/experiments/old-404"
    previous["experiment_urls"] = [broken]
    record.write_text(json.dumps(previous))
    repeated = finalize_delivery(run_dir, config_path=config)
    assert repeated["status"] == "ACCEPTED"
    assert repeated["experiment_urls"] == result["experiment_urls"]
    assert broken not in record.read_text()
    assert broken not in Path(repeated["report_path"]).read_text()


def test_reference_layout_keeps_behavior_and_static_evidence_separate(
    config, run_dir, server, tmp_path
):
    from eval_framework.local_delivery import finalize_delivery

    static = tmp_path / "static-run"
    static.mkdir()
    data = json.loads((run_dir / "results.json").read_text())
    data["summary"]["strict_assertion_pass_rate"] = 100.0
    (run_dir / "results.json").write_text(json.dumps(data))
    data["evaluator_run_id"] = "static-style-fixture"
    (static / "results.json").write_text(json.dumps(data))
    source = tmp_path / "intake.json"
    source.write_text(
        json.dumps(
            {
                "counts": {"static": 1, "behavior": 1, "blocked": 276},
                "runs": [
                    {"partition": "static", "paths": {"output_dir": str(static)}},
                    {"partition": "behavior", "paths": {"output_dir": str(run_dir)}},
                ],
            }
        )
    )
    result = finalize_delivery(source, config_path=config)
    assert result["status"] == "ACCEPTED"
    board = next(iter(server[1]["dashboards"].values()))
    placements = board["definition"]["widgets"]
    top = sorted((p for p in placements if p["y"] == 0), key=lambda p: p["x"])
    assert [(p["x"], p["width"]) for p in top] == [(0, 3), (3, 3), (6, 3), (9, 3)]
    widgets = server[1]["dashboard-widgets"]
    assert "行为" in widgets[top[0]["widgetId"]]["name"]
    assert "未执行" in widgets[top[3]["widgetId"]]["name"]
    assert sum(w["chartType"] == "HORIZONTAL_BAR" for w in widgets.values()) >= 3
    assert any(w["chartType"] == "PIVOT_TABLE" for w in widgets.values())
    lower = [widgets[p["widgetId"]] for p in placements if p["y"] >= 11]
    assert any("静态" in w["name"] for w in lower)
    scores = [
        s for r in server[0] if "/scores" in r.url.path for s in json.loads(r.content)
    ]
    inventory = [s for s in scores if s["name"] == "delivery.blocked"]
    assert len(inventory) == 1 and inventory[0]["value"] == 276
    assert inventory[0]["metadata"]["authority"] == "saved_intake"
    assert inventory[0]["metadata"]["source_sha256"] == result["source_sha256"]
    scopes = [s for s in scores if s["name"] == "context.scope"]
    assert len(scopes) == 1  # Main behavior partition only; no blended static cases.
    start = len(server[0])
    finalize_delivery(source, config_path=config)
    assert not any("/scores" in r.url.path for r in server[0][start:])


def test_direct_static_run_uses_saved_partition_in_style(run_dir):
    from eval_framework.local_delivery import _source, _widgets

    data = json.loads((run_dir / "results.json").read_text())
    data["onboarding"] = {"partition": "static"}
    (run_dir / "results.json").write_text(json.dumps(data))
    tiles = _widgets(_source(run_dir))
    assert "静态" in tiles[0]["spec"]["name"]
    assert "实际行为执行" not in tiles[0]["spec"]["name"]


def test_style_rate_label_preserves_saved_trial_denominator(run_dir):
    from eval_framework.local_delivery import _source, _widgets

    data = json.loads((run_dir / "results.json").read_text())
    data["summary"]["strict_assertion_pass_rate"] = 80.0
    (run_dir / "results.json").write_text(json.dumps(data))
    tiles = _widgets(_source(run_dir))
    rate = next(t for t in tiles if t["spec"]["name"] == "严格通过率 / %")
    assert "Trial" in rate["spec"]["description"]
    assert "NOT_APPLICABLE" in rate["spec"]["description"]
