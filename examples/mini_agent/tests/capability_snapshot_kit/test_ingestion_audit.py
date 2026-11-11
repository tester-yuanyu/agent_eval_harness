from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_audit_distinguishes_absence_omission_conflict_and_missing_source():
    from capability_snapshot_kit.ingestion.audit import audit_documents
    from capability_snapshot_kit.ingestion.models import FactDocument
    from capability_snapshot_kit.ingestion.reconcile import reconcile
    from examples.full_tool_fixture.collector import create

    runtime = create().collect(ROOT)
    absent = audit_documents(runtime, None)
    assert absent["inputs"]["candidate"] == "not_provided"
    assert absent["runtime_only"] == []
    assert absent["comparison_performed"] is False
    payload = runtime.model_dump(mode="json")
    removed = payload["tools"].pop()
    removed_id = "tool." + removed["tool_name"]
    payload["origins"].pop(removed_id)
    conflict_id = "module." + payload["modules"][0]["module_id"]
    payload["modules"][0]["responsibility"] += " changed"
    payload["origins"][conflict_id] = []
    candidate = FactDocument.model_validate(payload)
    report = audit_documents(runtime, candidate)
    assert report["runtime_only"] == [removed_id]
    assert report["conflicts"] == [conflict_id]
    assert report["missing_sources"]["candidate"] == [conflict_id]
    assert report["execution_verified"] is False
    with pytest.raises(ValueError, match="conflicting fact"):
        reconcile(runtime, candidate)
    reverse = audit_documents(candidate, runtime)
    assert reverse["candidate_only"] == [removed_id]


def test_collector_binds_fact_specific_sources():
    from examples.full_tool_fixture.collector import create

    document = create().collect(ROOT)
    assert set(document.origins) == set(document.fact_index())
    assert all(document.origins.values())
    tool = document.origins["tool.query_user_info"]
    intent = next(v for k, v in document.origins.items() if k.startswith("intent."))
    assert "examples/full_tool_fixture/environment.py" in tool
    assert "examples/full_tool_fixture/environment.py" not in intent
    assert "src/minimal_agent/capability_facts/tools.py" in tool
    assert "src/minimal_agent/capability_facts/intents.py" in intent
    assert (
        document.origins["module.model_gateway"]
        != document.origins["module.tool_registry"]
    )


def test_audit_cli_reports_before_reconcile_and_checks_source_integrity(tmp_path):
    import json

    from capability_snapshot_kit.ingestion.cli import main
    from examples.full_tool_fixture.collector import create

    document = create().collect(ROOT)
    runtime = tmp_path / "runtime.json"
    runtime.write_text(document.model_dump_json())
    candidate = tmp_path / "candidate.json"
    payload = document.model_dump(mode="json")
    payload["modules"][0]["responsibility"] += " conflict"
    candidate.write_text(json.dumps(payload))
    output = tmp_path / "audit.json"
    argv = [
        "audit",
        "--runtime",
        str(runtime),
        "--candidate",
        str(candidate),
        "--source-root",
        str(ROOT),
        "--output",
        str(output),
    ]
    assert main(argv) == 0
    assert json.loads(output.read_text())["conflicts"]
    assert main(argv) == 1  # exclusive output, no overwrite
    next(iter(payload["sources"].values()))["sha256"] = "0" * 64
    candidate.write_text(json.dumps(payload))
    assert main([*argv[:-1], str(tmp_path / "bad.json")]) == 1
    assert not (tmp_path / "bad.json").exists()
