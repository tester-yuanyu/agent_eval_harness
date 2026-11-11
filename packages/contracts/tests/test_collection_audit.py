"""来源变化只失效依赖事实，采集完整性仅限显式范围。"""

import json

import pytest
from capability_snapshot_kit.ingestion.models import FactDocument
from capability_snapshot_kit.ingestion.sources import source_reference


def document(root):
    (root / "agent.py").write_text("version = 1\n")
    (root / "intent.py").write_text("intent = 1\n")
    return FactDocument.model_validate(
        {
            "agent": {
                "agent_id": "demo",
                "agent_version": "1",
                "contract_version": "1",
                "entrypoints": [],
                "runtime_bindings": {},
                "input_schema": {},
                "output_schema": {},
                "runtime_versions": {},
            },
            "intents": [
                {
                    "intent_id": "query",
                    "contract_version": "1",
                    "module_role": "router",
                    "parameters_schema": {},
                    "parameter_semantics": {},
                    "decision_rules": {},
                    "semantic_rules": {},
                    "capabilities": [],
                }
            ],
            "sources": {
                name: source_reference(root, name).model_dump()
                for name in ("agent.py", "intent.py")
            },
            "origins": {"agent.demo": ["agent.py"], "intent.query": ["intent.py"]},
        }
    )


def test_source_change_invalidates_only_dependent_fact_and_keeps_input_bytes(tmp_path):
    from capability_snapshot_kit.ingestion.collection_audit import audit_collection

    doc = document(tmp_path)
    before = doc.model_dump_json()
    (tmp_path / "intent.py").write_text("intent = 2\n")
    report = audit_collection(doc, tmp_path)
    assert report["facts"]["agent.demo"]["validity"] == "unchanged"
    assert report["facts"]["intent.query"]["validity"] == "invalidated"
    assert report["facts"]["intent.query"]["changed_source_ids"] == ["intent.py"]
    assert report["collection_completeness"] == "unknown"
    assert report["global_completeness"] == "unknown"
    assert doc.model_dump_json() == before


def test_scope_accounts_for_exclusions_and_missing_facts_without_inventing_support(
    tmp_path,
):
    from capability_snapshot_kit.ingestion.collection_audit import audit_collection

    doc = document(tmp_path)
    scope = {
        "requested_sources": ["agent.py", "intent.py", "private.py", "missing.py"],
        "expected_fact_ids": ["agent.demo", "intent.query", "tool.absent"],
        "omissions": {"private.py": "excluded_by_owner"},
    }
    report = audit_collection(doc, tmp_path, scope=scope)
    assert report["source_omissions"] == [
        {"path": "missing.py", "reason": "unknown"},
        {"path": "private.py", "reason": "excluded_by_owner"},
    ]
    assert report["missing_fact_ids"] == ["tool.absent"]
    assert report["collection_completeness"] == "incomplete_within_declared_scope"
    assert report["global_completeness"] == "unknown"
    assert report["execution_verified"] is False
    assert "support_status" not in json.dumps(report)


def test_missing_source_and_unbound_fact_are_unknown_not_unchanged(tmp_path):
    from capability_snapshot_kit.ingestion.collection_audit import audit_collection

    doc = document(tmp_path)
    del doc.origins["agent.demo"]
    (tmp_path / "intent.py").unlink()
    report = audit_collection(doc, tmp_path)
    assert report["facts"]["agent.demo"]["validity"] == "unknown"
    assert report["facts"]["intent.query"]["validity"] == "invalidated"
    assert report["sources"]["intent.py"]["state"] == "missing"
    with pytest.raises(ValueError):
        audit_collection(doc, tmp_path, scope={"requested_sources": ["../outside"]})


def test_cli_audits_changed_sources_without_aborting(tmp_path, capsys):
    from capability_snapshot_kit.ingestion.cli import main

    doc = document(tmp_path)
    source = tmp_path / "facts.json"
    source.write_text(doc.model_dump_json())
    (tmp_path / "intent.py").write_text("changed\n")
    scope = tmp_path / "scope.json"
    scope.write_text(
        json.dumps(
            {
                "requested_sources": ["agent.py", "intent.py"],
                "expected_fact_ids": ["agent.demo", "intent.query"],
            }
        )
    )
    output = tmp_path / "audit.json"
    args = [
        "audit-collection",
        "--document",
        str(source),
        "--source-root",
        str(tmp_path),
        "--scope",
        str(scope),
        "--output",
        str(output),
    ]
    assert main(args) == 0
    report = json.loads(output.read_text())
    assert report["collection_completeness"] == "accounted_within_declared_scope"
    assert report["facts"]["intent.query"]["validity"] == "invalidated"
    assert main(args) == 1
