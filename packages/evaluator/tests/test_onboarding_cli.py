from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from test_suite_cli import _catalog, _suite_file

from eval_framework.cli import main
from eval_framework.contracts.store import sha256_bytes


def _prepared(monkeypatch, root, suites, *, blocked=1):
    calls = []
    report = {
        "counts": {"static": 1, "behavior": 0, "blocked": blocked},
        "release_eligible": False,
    }
    destination = root / "prepared"
    destination.mkdir()
    report_path = destination / "intake.json"
    report_path.write_text(json.dumps(report))

    def prepare(source, output_dir, *, binding=None, agent_root=None):
        calls.append((source, output_dir, binding, agent_root))
        return SimpleNamespace(
            root=destination, suite_paths=suites, report=report, report_path=report_path
        )

    module = ModuleType("eval_framework.onboarding")
    module.prepare_input = prepare
    monkeypatch.setitem(sys.modules, "eval_framework.onboarding", module)
    source = root / "delivery"
    source.mkdir()
    (source / "manifest.json").write_text('{"dataset_format":"agent_candidate"}')
    return source, report_path, calls


def _suite(dataset_path, name="evaluator_static.suite.json"):
    path = _suite_file(
        dataset_path.parent,
        dataset_name=dataset_path.name,
        dataset_hash=sha256_bytes(dataset_path.read_bytes()),
        loader_id="legacy_jsonl_eval_case_v1",
    )
    target = path.with_name(name)
    path.rename(target)
    return target


def test_input_suite_alias_uses_existing_compiler(dataset_path, monkeypatch, capsys):
    path = _suite(dataset_path)
    catalog, factory = _catalog()
    monkeypatch.setattr("eval_framework.cli.default_plugin_catalog", lambda: catalog)
    assert main(["validate", "--input", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert factory.calls == []


def test_input_suite_directory_rejects_ambiguous_roots(
    dataset_path,
    monkeypatch,
    capsys,
):
    path = _suite(dataset_path)
    path.with_name("second.suite.json").write_bytes(path.read_bytes())
    catalog, factory = _catalog()
    monkeypatch.setattr("eval_framework.cli.default_plugin_catalog", lambda: catalog)
    assert main(["validate", "--input", str(path.parent)]) == 2
    assert "ambiguous" in json.loads(capsys.readouterr().out)["message"].lower()
    assert factory.calls == []


def test_input_jsonl_alias_preserves_legacy_validation(dataset_path, capsys):
    assert main(["validate", "--input", str(dataset_path)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True


@pytest.mark.parametrize("other", ["--suite", "--dataset"])
def test_input_is_exclusive_with_old_source_flags(other, capsys):
    assert main(["validate", "--input", "delivery", other, "old"]) == 2
    assert "cannot be combined" in json.loads(capsys.readouterr().out)["message"]


def test_binding_cannot_be_used_with_authored_suite(dataset_path, tmp_path, capsys):
    suite = _suite(dataset_path)
    binding = tmp_path / "binding.json"
    binding.write_text("{}")
    assert main(["validate", "--input", str(suite), "--binding", str(binding)]) == 2
    assert "candidate" in json.loads(capsys.readouterr().out)["message"].lower()


def test_validate_candidate_compiles_without_runtime_and_preserves_blocked(
    dataset_path,
    tmp_path,
    monkeypatch,
    capsys,
):
    suite = _suite(dataset_path)
    catalog, factory = _catalog()
    monkeypatch.setattr("eval_framework.cli.default_plugin_catalog", lambda: catalog)
    source, report_path, calls = _prepared(monkeypatch, tmp_path, [suite])
    output = tmp_path / "intake-output"
    assert main(["validate", "--input", str(source), "--output-dir", str(output)]) == 5
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["intake"] == str(report_path)
    assert calls[0][1] == output
    assert factory.calls == []


def test_run_candidate_compiles_all_partitions_before_any_runtime(
    dataset_path,
    tmp_path,
    monkeypatch,
    capsys,
):
    first = _suite(dataset_path)
    second = first.with_name("evaluator_behavior.suite.json")
    raw = json.loads(first.read_text())
    raw["dataset_sources"][0]["sha256"] = "0" * 64
    second.write_text(json.dumps(raw))
    catalog, factory = _catalog()
    monkeypatch.setattr("eval_framework.cli.default_plugin_catalog", lambda: catalog)
    source, _, _ = _prepared(monkeypatch, tmp_path, [first, second])
    assert (
        main(["run", "--input", str(source), "--output-dir", str(tmp_path / "out")])
        == 2
    )
    assert factory.calls == []
    assert json.loads(capsys.readouterr().out)


def test_run_candidate_links_authoritative_reports_without_new_metrics(
    dataset_path,
    tmp_path,
    monkeypatch,
    capsys,
):
    suite = _suite(dataset_path)
    catalog, factory = _catalog()
    monkeypatch.setattr("eval_framework.cli.default_plugin_catalog", lambda: catalog)
    source, report_path, _ = _prepared(monkeypatch, tmp_path, [suite])
    destination = tmp_path / "out"
    assert main(["run", "--input", str(source), "--output-dir", str(destination)]) == 5
    payload = json.loads(capsys.readouterr().out)
    assert payload["intake"] == str(report_path)
    report = json.loads(report_path.read_text())
    assert report["counts"]["blocked"] == 1
    assert "summary" not in report
    assert "pass_rate" not in report
    assert len(report["runs"]) == 1
    run = report["runs"][0]
    assert run["partition"] == "static"
    assert Path(run["paths"]["results"]).is_file()
    assert Path(run["paths"]["results"]).is_relative_to(destination / "runs/static")
    assert len(factory.calls) == 1


def test_blocked_only_candidate_has_no_fake_run(tmp_path, monkeypatch, capsys):
    source, report_path, _ = _prepared(monkeypatch, tmp_path, [])
    assert (
        main(["run", "--input", str(source), "--output-dir", str(tmp_path / "out")])
        == 5
    )
    assert json.loads(capsys.readouterr().out)["intake"] == str(report_path)
    assert json.loads(report_path.read_text())["runs"] == []


def test_candidate_runtime_error_takes_precedence_over_blocked(
    dataset_path,
    tmp_path,
    monkeypatch,
    capsys,
):
    suite = _suite(dataset_path)
    catalog, _ = _catalog()
    monkeypatch.setattr("eval_framework.cli.default_plugin_catalog", lambda: catalog)
    source, report_path, _ = _prepared(monkeypatch, tmp_path, [suite])

    def unavailable(*args, **kwargs):
        raise RuntimeError("runtime unavailable")

    monkeypatch.setattr("eval_framework.cli.execute_compiled_suite", unavailable)
    assert (
        main(["run", "--input", str(source), "--output-dir", str(tmp_path / "out")])
        == 3
    )
    assert json.loads(capsys.readouterr().out)["intake"] == str(report_path)
    assert json.loads(report_path.read_text())["runs"][0]["error"]["message"] == (
        "runtime unavailable"
    )


def test_candidate_binding_is_explicit_and_agent_root_is_exclusive(
    tmp_path,
    monkeypatch,
    capsys,
):
    source, _, calls = _prepared(monkeypatch, tmp_path, [])
    binding = tmp_path / "trusted-binding.json"
    binding.write_text('{"agent_id":"other","adapter":"stdio"}')
    assert main(["validate", "--input", str(source), "--binding", str(binding)]) == 5
    assert calls[0][2] == {"agent_id": "other", "adapter": "stdio"}
    capsys.readouterr()
    assert (
        main(
            [
                "validate",
                "--input",
                str(source),
                "--binding",
                str(binding),
                "--agent-root",
                str(tmp_path),
            ]
        )
        == 2
    )
    assert len(calls) == 1


def test_malformed_candidate_binding_is_structured_input_failure(tmp_path, capsys):
    source = tmp_path / "delivery"
    source.mkdir()
    binding = tmp_path / "bad.json"
    binding.write_text("[]")
    assert main(["validate", "--input", str(source), "--binding", str(binding)]) == 2
    assert json.loads(capsys.readouterr().out)["error_type"] == "ValueError"


@pytest.mark.parametrize("archive", [False, True])
def test_second_agent_stdio_cli_runs_real_pipeline_without_oracle_leak(
    tmp_path,
    capsys,
    archive,
):
    import zipfile

    from test_onboarding import make_delivery

    source = make_delivery(tmp_path, agent_id="another_agent")
    if archive:
        zipped = tmp_path / "delivery.zip"
        with zipfile.ZipFile(zipped, "w") as stream:
            for path in source.rglob("*"):
                if path.is_file():
                    stream.write(path, "package/" + str(path.relative_to(source)))
        source = zipped
    request_file = tmp_path / "request.json"
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "request = json.load(sys.stdin)\n"
        "Path(sys.argv[1]).write_text(json.dumps(request))\n"
        "value = request['execution']['adapter_input']['input']['value']\n"
        "print(json.dumps({'protocol_version': '1.0', "
        "'observations': {'result': {'text': value}}}))\n"
    )
    binding = tmp_path / "trusted-binding.json"
    binding.write_text(
        json.dumps(
            {
                "version": "1.0",
                "agent_id": "another_agent",
                "adapter": "stdio",
                "argv": [sys.executable, str(worker), str(request_file)],
            }
        )
    )
    assert (
        main(
            [
                "run",
                "--input",
                str(source),
                "--binding",
                str(binding),
                "--output-dir",
                str(tmp_path / "runs"),
            ]
        )
        == 5
    )
    response = json.loads(capsys.readouterr().out)
    intake = json.loads(Path(response["intake"]).read_text())
    assert intake["counts"] == {"static": 1, "behavior": 1, "blocked": 1}
    assert {item["partition"] for item in intake["runs"]} == {"static", "behavior"}
    request = request_file.read_text()
    assert "private expected value" not in request
    assert '"oracle"' not in request
    assert '"checks"' not in request
    assert json.loads(request)["execution"]["adapter_input"]["input"]["value"] == (
        "actual input"
    )
    for item in intake["runs"]:
        result = json.loads(Path(item["paths"]["results"]).read_text())
        assert result["onboarding"]["release_eligible"] is False
        assert result["cases"][0]["execution_status"] == "COMPLETED"
        if item["partition"] == "static":
            assert result["run_config"]["run_mode"] == "framework_self_test"
            assert result["summary"]["agent_case_pass_rate"] is None
        else:
            assert result["run_config"]["run_mode"] == "agent_benchmark"
            assert result["cases"][0]["quality_conclusion"] == "FAIL"


def test_real_candidate_without_binding_executes_static_and_retains_blocked(
    tmp_path,
    capsys,
):
    from test_onboarding import make_delivery

    source = make_delivery(tmp_path)
    assert (
        main(["run", "--input", str(source), "--output-dir", str(tmp_path / "runs")])
        == 5
    )
    response = json.loads(capsys.readouterr().out)
    intake = json.loads(Path(response["intake"]).read_text())
    assert intake["counts"] == {"static": 1, "behavior": 0, "blocked": 2}
    assert [item["partition"] for item in intake["runs"]] == ["static"]


def test_corrupt_zip_returns_structured_input_error(tmp_path, capsys):
    source = tmp_path / "invalid.zip"
    source.write_bytes(b"not a zip")
    assert (
        main(["run", "--input", str(source), "--output-dir", str(tmp_path / "out")])
        == 2
    )
    assert json.loads(capsys.readouterr().out)["error_type"] in {
        "ValueError",
        "BadZipFile",
    }
