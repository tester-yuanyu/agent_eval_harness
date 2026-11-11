"""Offline checks for explicit targets, rate limits and persisted writes."""

import json
from types import SimpleNamespace

import httpx
import pytest


class Reply(SimpleNamespace):
    def model_dump(self, **_kwargs):
        return vars(self)


class Clock:
    def __init__(self):
        self.value = 0
        self.waits = []

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.value += seconds


def delivery_module():
    from eval_framework.benchmark import langfuse_delivery

    return langfuse_delivery


def profile_file(tmp_path, **overrides):
    values = dict(
        profile="local",
        base_url="http://127.0.0.1:3000",
        project_id="p",
        public_key_env="TEST_LF_PUBLIC",
        secret_key_env="TEST_LF_SECRET",
        intervals={"dataset": 0, "tracing": 0, "read": 0},
    )
    values.update(overrides)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(values))
    return path


def test_profile_never_falls_back_to_cloud_environment(tmp_path, monkeypatch):
    module = delivery_module()
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    profile = module.load_profile(profile_file(tmp_path))
    assert profile.base_url == "http://127.0.0.1:3000"
    with pytest.raises(ValueError, match="TEST_LF_PUBLIC"):
        profile.client()
    with pytest.raises(ValueError, match="local"):
        module.load_profile(
            profile_file(tmp_path, base_url="https://cloud.langfuse.com")
        )
    with pytest.raises(ValueError, match="unknown"):
        module.load_profile(profile_file(tmp_path, secret_key="never-store"))


def test_rate_buckets_are_independent_and_retry_after_is_respected(tmp_path):
    module = delivery_module()
    clock = Clock()
    limiter = module.RateLimiter(
        {"dataset": 3, "tracing": 2, "read": 1}, clock=clock.now, sleep=clock.sleep
    )
    limiter.wait("dataset")
    limiter.wait("read")
    assert clock.waits == []
    limiter.wait("dataset")
    assert clock.waits == [3]
    limiter.defer("read", {"Retry-After": "7"})
    limiter.wait("tracing")
    limiter.wait("read")
    assert clock.waits == [3, 7]


def test_429_is_retried_without_replaying_ambiguous_write(tmp_path):
    module = delivery_module()
    pytest.importorskip("langfuse")
    from langfuse.api.core.api_error import ApiError

    clock = Clock()
    writes = []

    def create(**kwargs):
        writes.append((clock.now(), kwargs["name"]))
        if len(writes) == 1:
            raise ApiError(status_code=429, headers={"retry-after": "8"})
        return Reply(id="dataset", name=kwargs["name"])

    client = module.DeliveryClient(
        SimpleNamespace(datasets=SimpleNamespace(create=create)),
        tmp_path / "journal.json",
        destination="d",
        limiter=module.RateLimiter({}, clock=clock.now, sleep=clock.sleep),
    )
    assert client.datasets.create(name="cases").id == "dataset"
    assert writes == [(0, "cases"), (8, "cases")]


def test_uncertain_dataset_write_is_read_back_on_resume_without_replay(tmp_path):
    module = delivery_module()
    writes, reads = [], []

    def create(**kwargs):
        writes.append(kwargs)
        raise httpx.ReadTimeout("possibly accepted")

    def get(**kwargs):
        reads.append(kwargs)
        return Reply(id="existing", name="cases")

    raw = SimpleNamespace(datasets=SimpleNamespace(create=create, get=get))
    path = tmp_path / "journal.json"
    client = module.DeliveryClient(raw, path, destination="d")
    with pytest.raises(httpx.ReadTimeout):
        client.datasets.create(name="cases")
    resumed = module.DeliveryClient(raw, path, destination="d")
    assert resumed.datasets.create(name="cases").id == "existing"
    assert len(writes) == 1 and len(reads) == 1
    with pytest.raises(ValueError, match="destination"):
        module.DeliveryClient(raw, path, destination="another")


def test_missing_index_after_uncertain_write_never_replays(tmp_path):
    module = delivery_module()
    pytest.importorskip("langfuse")
    from langfuse.api.core.api_error import ApiError

    writes = []

    def create(**kwargs):
        writes.append(kwargs)
        raise httpx.ReadTimeout("possibly accepted")

    def get(**_kwargs):
        raise ApiError(status_code=404)

    client = module.DeliveryClient(
        SimpleNamespace(dataset_items=SimpleNamespace(create=create, get=get)),
        tmp_path / "journal.json",
        destination="d",
    )
    with pytest.raises(httpx.ReadTimeout):
        client.dataset_items.create(id="item", dataset_name="cases")
    with pytest.raises(module.NeedsReconciliation):
        client.dataset_items.create(id="item", dataset_name="cases")
    assert len(writes) == 1


def test_sync_reuses_export_and_waits_for_index_with_bounded_verification(
    tmp_path, monkeypatch
):
    module = delivery_module()
    pytest.importorskip("langfuse")
    import eval_framework.benchmark.langfuse_export as exporter

    (tmp_path / "results.json").write_text("{}")
    profile = module.load_profile(profile_file(tmp_path))
    calls = []
    monkeypatch.setattr(exporter, "export_run", lambda *a, **k: calls.append("export"))
    monkeypatch.setattr(
        exporter, "export_metadata_evidence", lambda *a, **k: calls.append("evidence")
    )

    def verify(*a, **k):
        calls.append("verify")
        return {"status": "VERIFIED" if calls.count("verify") == 2 else "MISMATCH"}

    monkeypatch.setattr(exporter, "verify_run", verify)
    clock = Clock()
    result = module.sync_run(
        tmp_path,
        tmp_path / "tasks",
        profile=profile,
        client=SimpleNamespace(),
        destination="test",
        verification_attempts=3,
        index_wait=2,
        sleep=clock.sleep,
    )
    assert calls == ["export", "evidence", "verify", "verify"]
    assert clock.waits == [2, 2]
    assert result["local_status"] == "COMPLETE"
    assert result["sync_status"] == "VERIFIED"
    assert json.loads((tmp_path / "langfuse_delivery.json").read_text()) == result


def test_sync_failure_preserves_local_completion_and_records_no_secrets(
    tmp_path, monkeypatch
):
    module = delivery_module()
    pytest.importorskip("langfuse")
    import eval_framework.benchmark.langfuse_export as exporter

    (tmp_path / "results.json").write_text("{}")
    profile = module.load_profile(profile_file(tmp_path))

    def fail(*a, **k):
        raise httpx.ReadTimeout("secret must never be copied")

    monkeypatch.setattr(exporter, "export_run", fail)
    result = module.sync_run(
        tmp_path,
        tmp_path / "tasks",
        profile=profile,
        client=SimpleNamespace(),
        destination="test",
    )
    assert result["local_status"] == "COMPLETE"
    assert result["sync_status"] == "NEEDS_RECONCILIATION"
    assert "secret must" not in (tmp_path / "langfuse_delivery.json").read_text()


def test_exporter_uses_explicit_destination_and_recovers_inflight(
    tmp_path, monkeypatch
):
    module = delivery_module()
    pytest.importorskip("langfuse")
    from pathlib import Path

    from eval_framework.benchmark import langfuse_export as exporter
    from eval_framework.benchmark.tasks import dataset_identity
    from langfuse.api.client import LangfuseAPI

    DATASET = (
        Path(__file__).resolve().parents[4]
        / "data/benchmarks/file-tools-v1/tasks.jsonl"
    )
    root = tmp_path
    (root / "results.json").write_text(
        json.dumps(
            {
                "run_id": "delivery",
                "identity": {"dataset": dataset_identity(DATASET)},
                "mode": "real_agent",
                "planned_case_ids": [],
                "trials": [],
            }
        )
    )
    wire = []

    def handler(request):
        wire.append(request.url.path)
        if request.url.path == "/api/public/v2/datasets":
            return httpx.Response(
                200,
                json=dict(
                    id="dataset-id",
                    name="cases",
                    description=None,
                    metadata={},
                    projectId="p",
                    createdAt="2026-11-01T00:00:00Z",
                    updatedAt="2026-11-01T00:00:00Z",
                ),
            )
        return httpx.Response(200, json={"id": "unused"})

    raw = LangfuseAPI(
        base_url="https://test.invalid",
        username="p",
        password="s",
        httpx_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    wrapped = module.DeliveryClient(raw, root / "journal.json", destination="explicit")
    # Empty selection keeps this a transport/receipt integration test.
    saved = json.loads((root / "results.json").read_text())
    saved["planned_case_ids"] = []
    (root / "results.json").write_text(json.dumps(saved))
    result = exporter.export_run(root, DATASET, client=wrapped)
    assert result["destination"] == "explicit"
    assert wire == ["/api/public/v2/datasets"]
    receipt_path = root / "langfuse_export.json"
    receipt = json.loads(receipt_path.read_text())
    receipt.update(status="PENDING", inflight=["span"])
    receipt_path.write_text(json.dumps(receipt))
    wrapped.state["operations"]["known"] = {
        "resource": "opentelemetry",
        "status": "ACCEPTED",
        "ids": ["span"],
        "response": {},
    }
    exporter.export_run(root, DATASET, client=wrapped)
    receipt = json.loads(receipt_path.read_text())
    assert receipt["accepted_observation_ids"] == ["span"]
    assert receipt["inflight"] == []
    assert len(wire) == 1


def test_run_links_bind_verified_dataset_and_experiments(tmp_path):
    from hashlib import sha256

    from eval_framework.benchmark import report_links

    (tmp_path / "results.json").write_text("{}")
    source = sha256(b"{}").hexdigest()
    receipt = {
        "source_hash": source,
        "destination": "dest",
        "dataset_id": "dataset/id",
        "dataset_name": "all-cases",
        "traces": [
            {
                "case_id": "case",
                "trial": 1,
                "trace_id": "trace",
                "experiment_id": "experiment",
            }
        ],
    }
    (tmp_path / "langfuse_export.json").write_text(json.dumps(receipt))
    verification = {
        "source_hash": source,
        "status": "VERIFIED",
        "experiments": [{"experiment_id": "experiment", "items": 1, "expected": 1}],
    }
    (tmp_path / "langfuse_verification.json").write_text(json.dumps(verification))
    report_links.write_links(
        tmp_path,
        base_url="https://cloud.langfuse.com",
        project_id="project",
        destination="dest",
    )
    links = report_links.load_run_links(tmp_path)
    assert (
        links["dataset"]["url"]
        == "https://cloud.langfuse.com/project/project/datasets/dataset%2Fid"
    )
    assert links["experiments"] == [
        dict(
            experiment_id="experiment",
            trial=1,
            items=1,
            url="https://cloud.langfuse.com/project/project/experiments/results?baseline=experiment",
        )
    ]
    assert report_links.load_links(tmp_path) == {
        ("case", 1): "https://cloud.langfuse.com/project/project/traces/trace"
    }
    stored = json.loads((tmp_path / "report-links.json").read_text())
    stored["experiments"][0]["url"] = "https://unverified.invalid"
    (tmp_path / "report-links.json").write_text(json.dumps(stored))
    assert report_links.load_run_links(tmp_path) == {}


@pytest.mark.parametrize("resource", ["opentelemetry", "scores"])
def test_uncertain_batch_reads_ids_then_resumes_without_new_write(tmp_path, resource):
    module = delivery_module()
    writes, reads = [], []

    def send(**kwargs):
        writes.append(kwargs)
        raise httpx.ReadTimeout("accepted but response lost")

    def read(**kwargs):
        reads.append(kwargs)
        return Reply(data=[{"id": "one"}], meta={})

    raw = SimpleNamespace(
        opentelemetry=SimpleNamespace(export_traces=send),
        observations=SimpleNamespace(get_many=read),
        scores=SimpleNamespace(create=send, get_many=read),
    )
    client = module.DeliveryClient(raw, tmp_path / "journal.json", destination="d")
    if resource == "scores":
        args = {"request": [Reply(id="one", trace_id="trace")]}
        call = client.scores.create
    else:
        args = {
            "resource_spans": [
                Reply(
                    scope_spans=[Reply(spans=[Reply(span_id="one", trace_id="trace")])]
                )
            ]
        }
        call = client.opentelemetry.export_traces
    with pytest.raises(httpx.ReadTimeout):
        call(**args)
    call(**args)
    assert len(writes) == 1
    assert reads[0]["trace_id"] == "trace"
    assert len(reads) == 1


def test_sync_bounds_missing_index_reads_without_reexporting(tmp_path, monkeypatch):
    module = delivery_module()
    pytest.importorskip("langfuse")
    from eval_framework.benchmark import langfuse_export as exporter

    (tmp_path / "results.json").write_text("{}")
    calls = []
    monkeypatch.setattr(exporter, "export_run", lambda *a, **k: calls.append("export"))
    monkeypatch.setattr(
        exporter, "export_metadata_evidence", lambda *a, **k: calls.append("evidence")
    )

    def verify(*a, **k):
        calls.append("verify")
        return {"status": "MISMATCH"}

    monkeypatch.setattr(exporter, "verify_run", verify)
    state = module.sync_run(
        tmp_path,
        tmp_path / "tasks",
        profile=module.load_profile(profile_file(tmp_path)),
        client=SimpleNamespace(),
        destination="d",
        verification_attempts=2,
        index_wait=0,
        sleep=lambda _: None,
    )
    assert calls == ["export", "evidence", "verify", "verify"]
    assert state["sync_status"] == "PENDING_INDEX"
    assert state["verification_attempts"] == 2


def test_uncertain_server_error_is_not_reported_as_definite_failure(
    tmp_path, monkeypatch
):
    module = delivery_module()
    pytest.importorskip("langfuse")
    from eval_framework.benchmark import langfuse_export as exporter
    from langfuse.api.core.api_error import ApiError

    (tmp_path / "results.json").write_text("{}")

    def export(*a, client, **k):
        return client.datasets.create(name="cases")

    def send(**_kwargs):
        raise ApiError(status_code=503)

    monkeypatch.setattr(exporter, "export_run", export)
    state = module.sync_run(
        tmp_path,
        tmp_path / "tasks",
        profile=module.load_profile(profile_file(tmp_path)),
        client=SimpleNamespace(datasets=SimpleNamespace(create=send)),
        destination="d",
    )
    assert state["sync_status"] == "NEEDS_RECONCILIATION"


def test_sleeping_dataset_bucket_does_not_block_reads():
    import threading
    from concurrent.futures import ThreadPoolExecutor

    module = delivery_module()
    sleeping, release = threading.Event(), threading.Event()

    def sleep(_seconds):
        sleeping.set()
        release.wait(timeout=2)

    limiter = module.RateLimiter({"dataset": 10}, clock=lambda: 0, sleep=sleep)
    limiter.wait("dataset")
    with ThreadPoolExecutor(2) as pool:
        blocked = pool.submit(limiter.wait, "dataset")
        assert sleeping.wait(timeout=1)
        read = pool.submit(limiter.wait, "read")
        try:
            assert read.result(timeout=0.2) is None
        finally:
            release.set()
        blocked.result(timeout=1)


def test_successful_otlp_empty_partial_response_is_accepted(tmp_path):
    module = delivery_module()
    sends = []

    def send(**kwargs):
        sends.append(kwargs)
        return Reply(partial_success={"rejected_spans": 0, "error_message": ""})

    client = module.DeliveryClient(
        SimpleNamespace(opentelemetry=SimpleNamespace(export_traces=send)),
        tmp_path / "journal.json",
        destination="d",
    )
    args = {
        "resource_spans": [
            Reply(scope_spans=[Reply(spans=[Reply(span_id="one", trace_id="trace")])])
        ]
    }
    client.opentelemetry.export_traces(**args)
    client.opentelemetry.export_traces(**args)
    assert len(sends) == 1


def test_sync_refuses_concurrent_delivery_for_same_run(tmp_path):
    import fcntl

    module = delivery_module()
    (tmp_path / "results.json").write_text("{}")
    profile = module.load_profile(profile_file(tmp_path))
    with (tmp_path / ".langfuse_delivery.lock").open("w") as locked:
        fcntl.flock(locked.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="already active"):
            module.sync_run(
                tmp_path,
                tmp_path / "tasks",
                profile=profile,
                client=SimpleNamespace(),
                destination="d",
            )
    assert not (tmp_path / "langfuse_delivery.json").exists()


def test_legacy_links_derive_run_entries_without_rewriting_receipts(tmp_path):
    from hashlib import sha256

    from eval_framework.benchmark import report_links

    (tmp_path / "results.json").write_text("{}")
    source = sha256(b"{}").hexdigest()
    receipt = {
        "source_hash": source,
        "destination": "dest",
        "dataset_id": "dataset",
        "traces": [{"case_id": "c", "trial": 1, "trace_id": "t", "experiment_id": "e"}],
    }
    verification = {
        "source_hash": source,
        "status": "VERIFIED",
        "experiments": [{"experiment_id": "e", "items": 1, "expected": 1}],
    }
    (tmp_path / "langfuse_export.json").write_text(json.dumps(receipt))
    (tmp_path / "langfuse_verification.json").write_text(json.dumps(verification))
    report_links.write_links(
        tmp_path,
        base_url="https://cloud.langfuse.com",
        project_id="p",
        destination="dest",
    )
    path = tmp_path / "report-links.json"
    stored = json.loads(path.read_text())
    del stored["dataset"], stored["experiments"]
    path.write_text(json.dumps(stored))
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    links = report_links.load_run_links(tmp_path)
    assert links["dataset"]["dataset_id"] == "dataset"
    assert links["experiments"][0]["experiment_id"] == "e"
    assert all(p.read_bytes() == data for p, data in before.items())


def test_sync_records_each_delivery_phase_without_changing_results(
    tmp_path, monkeypatch
):
    module = delivery_module()
    pytest.importorskip("langfuse")
    from eval_framework.benchmark import langfuse_export as exporter

    (tmp_path / "results.json").write_bytes(b"{}")
    profile = module.load_profile(profile_file(tmp_path))
    monkeypatch.setattr(exporter, "export_run", lambda *a, **k: {})
    monkeypatch.setattr(exporter, "export_metadata_evidence", lambda *a, **k: {})
    monkeypatch.setattr(exporter, "verify_run", lambda *a, **k: {"status": "MISMATCH"})
    module.sync_run(
        tmp_path,
        tmp_path / "tasks",
        profile=profile,
        client=SimpleNamespace(),
        destination="d",
        verification_attempts=2,
        index_wait=0,
        sleep=lambda _: None,
    )
    assert (tmp_path / "results.json").read_bytes() == b"{}"
    phases = json.loads((tmp_path / "phase-timings.json").read_text())["events"]
    assert [event["phase"] for event in phases] == [
        "langfuse_export",
        "langfuse_metadata_export",
        "langfuse_index_wait",
        "langfuse_verify",
        "langfuse_index_wait",
        "langfuse_verify",
    ]
    assert all(event["seconds"] >= 0 for event in phases)
    assert all(
        event["source_hash"]
        == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
        for event in phases
    )


def test_final_429_defers_next_call_in_same_bucket(tmp_path):
    module = delivery_module()
    pytest.importorskip("langfuse")
    from langfuse.api.core.api_error import ApiError

    clock, calls = Clock(), []

    def create(**kwargs):
        calls.append(clock.now())
        if len(calls) <= 3:
            raise ApiError(status_code=429, headers={"Retry-After": "2"})
        return Reply(id="dataset", name=kwargs["name"])

    client = module.DeliveryClient(
        SimpleNamespace(datasets=SimpleNamespace(create=create)),
        tmp_path / "journal.json",
        destination="d",
        limiter=module.RateLimiter({}, clock=clock.now, sleep=clock.sleep),
    )
    with pytest.raises(ApiError):
        client.datasets.create(name="cases")
    client.datasets.create(name="cases")
    assert calls == [0, 2, 4, 6]
