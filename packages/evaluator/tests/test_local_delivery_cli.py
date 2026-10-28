from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from test_onboarding import make_delivery
from test_onboarding_cli import _prepared, _suite
from test_suite_cli import _catalog

import eval_framework.cli as cli


@pytest.fixture(autouse=True)
def isolated_local_configuration(tmp_path, monkeypatch):
    # A developer's enabled local deployment must never affect offline CLI tests.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_EVALUATOR_LOCAL_LANGFUSE_CONFIG", raising=False)
    monkeypatch.setattr(
        "inspect_ai._util.appdirs.user_data_path",
        lambda package: tmp_path / "inspect-data" / package,
    )
    monkeypatch.setattr(
        "inspect_ai._util.appdirs.user_cache_path",
        lambda package: tmp_path / "inspect-cache" / package,
    )


def _delivery_boundary(monkeypatch, callback):
    module = ModuleType("eval_framework.local_delivery")
    module.finalize_delivery = callback
    monkeypatch.setitem(sys.modules, "eval_framework.local_delivery", module)


def _offline_suite(dataset_path, monkeypatch):
    suite = _suite(dataset_path)
    catalog, _ = _catalog()
    monkeypatch.setattr(cli, "default_plugin_catalog", lambda: catalog)
    return suite


def test_normal_run_delivers_saved_authoritative_directory(
    dataset_path, tmp_path, monkeypatch, capsys
):
    suite = _offline_suite(dataset_path, monkeypatch)
    config = tmp_path / "local.json"
    snapshots = []

    def deliver(source, *, config_path=None, retry_pending=True):
        root = Path(source)
        snapshots.append(
            (root, config_path, retry_pending, (root / "results.json").read_bytes())
        )
        assert (root / "report.md").is_file()
        assert (root / "summary.json").is_file()
        return {
            "status": "ACCEPTED",
            "dashboard_url": "http://127.0.0.1:3000/project/local/dashboards/run",
        }

    _delivery_boundary(monkeypatch, deliver)
    code = cli.main(
        [
            "run",
            "--suite",
            str(suite),
            "--output-dir",
            str(tmp_path / "runs"),
            "--local-langfuse-config",
            str(config),
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["delivery"]["status"] == "ACCEPTED"
    assert payload["delivery"]["dashboard_url"].startswith("http://127.0.0.1:3000/")
    assert len(snapshots) == 1
    root, configured, retry, results = snapshots[0]
    assert root == Path(payload["output_dir"])
    assert configured == str(config)
    assert retry is True
    assert Path(payload["results"]).read_bytes() == results


def test_disabled_delivery_preserves_cli_json_with_cloud_credentials_present(
    dataset_path, tmp_path, monkeypatch, capsys
):
    suite = _offline_suite(dataset_path, monkeypatch)
    monkeypatch.setenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "cloud-public")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "cloud-secret")

    def cloud_export(*args, **kwargs):
        pytest.fail("ordinary local runs must not use the Cloud export command")

    monkeypatch.setattr(cli, "export_run", cloud_export)
    local_delivery = importlib.import_module("eval_framework.local_delivery")
    monkeypatch.setattr(local_delivery, "export_run", cloud_export)
    monkeypatch.setattr(local_delivery.httpx, "Client", cloud_export)
    code = cli.main(
        ["run", "--suite", str(suite), "--output-dir", str(tmp_path / "runs")]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert "delivery" not in payload
    assert Path(payload["results"]).is_file()
    assert Path(payload["report"]).is_file()


@pytest.mark.parametrize("delivery_raises", [False, True])
def test_delivery_failure_preserves_successful_evaluation_exit_and_result(
    dataset_path, tmp_path, monkeypatch, capsys, delivery_raises
):
    suite = _offline_suite(dataset_path, monkeypatch)
    snapshots = []

    def unavailable(source, **kwargs):
        snapshots.append((Path(source) / "results.json").read_bytes())
        if delivery_raises:
            raise RuntimeError("secret-key-must-not-appear")
        return {"status": "PENDING", "message": "local service unavailable"}

    _delivery_boundary(monkeypatch, unavailable)
    code = cli.main(
        ["run", "--suite", str(suite), "--output-dir", str(tmp_path / "runs")]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert code == 0
    assert payload["delivery"]["status"] == "PENDING"
    assert "error_type" not in payload
    assert "secret-key-must-not-appear" not in output
    assert len(snapshots) == 1
    assert Path(payload["results"]).read_bytes() == snapshots[0]
    result = json.loads(snapshots[0])
    assert result["cases"][0]["execution_status"] == "COMPLETED"


@pytest.mark.parametrize("all_blocked", [False, True])
def test_candidate_delivery_reads_final_intake_without_fabricated_trials(
    tmp_path, monkeypatch, capsys, all_blocked
):
    source = make_delivery(tmp_path)
    if all_blocked:
        manifest_path = source / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        static_path = "datasets/schema_contract.jsonl"
        (source / static_path).unlink()
        manifest["datasets"] = [
            item for item in manifest["datasets"] if item["path"] != static_path
        ]
        manifest["files_sha256"].pop(static_path)
        manifest["counts_by_kind"].pop("schema_contract")
        manifest["case_count"] = 2
        manifest_path.write_text(json.dumps(manifest))
    snapshots = []

    def deliver(intake, **kwargs):
        snapshots.append((Path(intake), Path(intake).read_bytes()))
        return {"status": "ACCEPTED", "report_path": str(intake)}

    _delivery_boundary(monkeypatch, deliver)
    destination = tmp_path / "runs"
    code = cli.main(["run", "--input", str(source), "--output-dir", str(destination)])
    payload = json.loads(capsys.readouterr().out)

    assert code == 5
    assert payload["delivery"]["status"] == "ACCEPTED"
    assert len(snapshots) == 1
    intake_path, saved = snapshots[0]
    assert intake_path == Path(payload["intake"])
    assert intake_path.read_bytes() == saved
    intake = json.loads(saved)
    assert intake["counts"] == {
        "static": 0 if all_blocked else 1,
        "behavior": 0,
        "blocked": 2,
    }
    assert intake["runs"] == payload["runs"]
    assert "pass_rate" not in intake
    if all_blocked:
        assert intake["runs"] == []
        assert list(destination.rglob("results.json")) == []
    else:
        assert len(intake["runs"]) == 1
        assert Path(intake["runs"][0]["paths"]["results"]).is_file()


def test_candidate_partition_error_is_retained_when_final_delivery_also_raises(
    dataset_path, tmp_path, monkeypatch, capsys
):
    first = _offline_suite(dataset_path, monkeypatch)
    second = first.with_name("evaluator_behavior.suite.json")
    second.write_bytes(first.read_bytes())
    source, intake_path, _ = _prepared(monkeypatch, tmp_path, [first, second])
    execute = cli.execute_compiled_suite

    def partition_execution(suite, catalog, *, output_dir):
        if Path(output_dir).name == "behavior":
            raise RuntimeError("partition runtime unavailable")
        return execute(suite, catalog, output_dir=output_dir)

    saved_intakes = []

    def unavailable(source, **kwargs):
        saved_intakes.append(Path(source).read_bytes())
        raise RuntimeError("delivery secret must not appear")

    monkeypatch.setattr(cli, "execute_compiled_suite", partition_execution)
    _delivery_boundary(monkeypatch, unavailable)
    code = cli.main(
        ["run", "--input", str(source), "--output-dir", str(tmp_path / "runs")]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert code == 3
    assert payload["delivery"]["status"] == "PENDING"
    assert len(saved_intakes) == 1
    assert intake_path.read_bytes() == saved_intakes[0]
    runs = json.loads(saved_intakes[0])["runs"]
    assert len(runs) == 2
    assert runs == payload["runs"]
    assert Path(runs[0]["paths"]["results"]).is_file()
    assert runs[1]["error"]["message"] == "partition runtime unavailable"
    assert "delivery secret" not in output


def test_preflight_invalid_delivers_saved_invalid_record_and_keeps_exit_two(
    dataset_path, tmp_path, monkeypatch, capsys
):
    suite = _offline_suite(dataset_path, monkeypatch)
    raw = json.loads(suite.read_text())
    raw["dataset_sources"][0]["sha256"] = "0" * 64
    suite.write_text(json.dumps(raw))
    saved_records = []

    def unavailable(source, **kwargs):
        root = Path(source)
        saved_records.append((root, (root / "invalid_run.json").read_bytes()))
        assert (root / "report.md").is_file()
        raise RuntimeError("delivery secret must not appear")

    _delivery_boundary(monkeypatch, unavailable)
    code = cli.main(
        ["run", "--suite", str(suite), "--output-dir", str(tmp_path / "runs")]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert code == 2
    assert payload["delivery"]["status"] == "PENDING"
    assert len(saved_records) == 1
    root, saved = saved_records[0]
    assert root == Path(payload["output_dir"])
    assert Path(payload["record"]).read_bytes() == saved
    assert json.loads(saved)["verdict"] == "INVALID_RUN"
    assert not (root / "results.json").exists()
    assert "delivery secret" not in output


def test_validate_does_not_trigger_run_delivery(tmp_path, monkeypatch, capsys):
    source = make_delivery(tmp_path)

    def unexpected(*args, **kwargs):
        pytest.fail("validate must not trigger post-run delivery")

    _delivery_boundary(monkeypatch, unexpected)
    assert cli.main(["validate", "--input", str(source)]) == 5
    assert "delivery" not in json.loads(capsys.readouterr().out)


def test_malformed_candidate_saves_admission_failure_before_delivery(
    tmp_path, monkeypatch, capsys
):
    source = make_delivery(tmp_path)
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["case_count"] += 1
    manifest_path.write_text(json.dumps(manifest))
    saved = []

    def deliver(source, **kwargs):
        root = Path(source)
        saved.append((root / "invalid_run.json").read_bytes())
        assert (root / "report.md").is_file()
        return {"status": "ACCEPTED"}

    _delivery_boundary(monkeypatch, deliver)
    code = cli.main(
        ["run", "--input", str(source), "--output-dir", str(tmp_path / "runs")]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["error_type"] == "ValueError"
    assert payload["message"] == "manifest case count mismatch"
    assert payload["delivery"]["status"] == "ACCEPTED"
    assert len(saved) == 1
    assert Path(payload["record"]).read_bytes() == saved[0]
    record = json.loads(saved[0])
    assert record["verdict"] == "INVALID_RUN"
    assert record["error_code"] == "ADMISSION_ERROR"
    assert "cases" not in record
    assert list(Path(payload["output_dir"]).rglob("results.json")) == []


@pytest.mark.parametrize(("error_type", "exit_code"), [(RuntimeError, 3), (OSError, 2)])
def test_unhandled_run_failure_saves_execution_failure_without_preflight_claim(
    dataset_path, tmp_path, monkeypatch, capsys, error_type, exit_code
):
    suite = _offline_suite(dataset_path, monkeypatch)
    saved = []

    def execution_failure(*args, **kwargs):
        raise error_type("execution interrupted")

    def unavailable(source, **kwargs):
        root = Path(source)
        saved.append((root / "invalid_run.json").read_bytes())
        assert (root / "report.md").is_file()
        raise RuntimeError("private-delivery-secret")

    monkeypatch.setattr(cli, "execute_compiled_suite", execution_failure)
    _delivery_boundary(monkeypatch, unavailable)
    code = cli.main(
        ["run", "--suite", str(suite), "--output-dir", str(tmp_path / "runs")]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert code == exit_code
    assert payload["error_type"] == error_type.__name__
    assert payload["message"] == "execution interrupted"
    assert payload["delivery"]["status"] == "PENDING"
    assert len(saved) == 1
    assert Path(payload["record"]).read_bytes() == saved[0]
    record = json.loads(saved[0])
    assert record["verdict"] == "INVALID_RUN"
    assert record["error_code"] == "EXECUTION_ERROR"
    report = Path(payload["report"]).read_text()
    assert "执行 Agent 前" not in report
    assert "EXECUTION_ERROR" in report
    assert "private-delivery-secret" not in output


def test_failure_artifact_write_error_preserves_original_cli_error(
    dataset_path, tmp_path, monkeypatch, capsys
):
    suite = _offline_suite(dataset_path, monkeypatch)

    def execution_failure(*args, **kwargs):
        raise RuntimeError("original execution failure")

    def unexpected(*args, **kwargs):
        pytest.fail("delivery requires a saved failure record")

    destination = tmp_path / "not-a-directory"
    destination.write_text("existing user file")
    monkeypatch.setattr(cli, "execute_compiled_suite", execution_failure)
    _delivery_boundary(monkeypatch, unexpected)
    code = cli.main(["run", "--suite", str(suite), "--output-dir", str(destination)])
    payload = json.loads(capsys.readouterr().out)

    assert code == 3
    assert payload["error_type"] == "RuntimeError"
    assert payload["message"] == "original execution failure"
    assert payload["failure_artifacts"]["status"] == "UNAVAILABLE"
    assert "delivery" not in payload
    assert destination.read_text() == "existing user file"


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        ("ACCEPTED", 0),
        ("PENDING", 3),
        ("RECONCILIATION_REQUIRED", 3),
        ("CONFIG_ERROR", 3),
        ("DISABLED", 3),
        ("RAISE", 3),
    ],
)
def test_sync_local_uses_only_saved_source_and_reports_explicit_failure(
    tmp_path, monkeypatch, capsys, status, expected_code
):
    source = tmp_path / "intake.json"
    saved = b'{"counts":{"static":0,"behavior":0,"blocked":1},"runs":[]}'
    source.write_bytes(saved)
    config = tmp_path / "local.json"
    synced = []

    def deliver(source, *, config_path=None, retry_pending=True):
        synced.append((Path(source), config_path, retry_pending))
        if status == "RAISE":
            raise RuntimeError("secret-key-must-not-appear")
        return {"status": status}

    def execution_forbidden(*args, **kwargs):
        pytest.fail("saved-result sync must never execute an Agent")

    _delivery_boundary(monkeypatch, deliver)
    monkeypatch.setattr(cli, "execute_compiled_suite", execution_forbidden)
    code = cli.main(
        [
            "sync-local",
            "--source",
            str(source),
            "--local-langfuse-config",
            str(config),
        ]
    )
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert code == expected_code
    assert payload["status"] == ("PENDING" if status == "RAISE" else status)
    assert synced == [(source, str(config), True)]
    assert source.read_bytes() == saved
    assert "secret-key-must-not-appear" not in output
