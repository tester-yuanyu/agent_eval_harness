from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.capability_snapshot_kit.test_ingestion import document


def test_prepare_request_binds_sources_and_rejects_tampering(tmp_path):
    from capability_snapshot_kit.ingestion.requests import (
        ExtractionRequest,
        check_candidate_request,
        prepare_request,
    )

    facts = document(tmp_path)
    request = prepare_request(tmp_path, ["agent.py"])
    assert request.sources["agent.py"].content.startswith("def run")
    assert "unknown" in request.instructions
    assert "FactDocument" in request.document_schema["title"]
    check_candidate_request(facts, request)
    payload = request.model_dump(mode="json")
    payload["sources"]["agent.py"]["content"] = "tampered"
    with pytest.raises(ValueError, match="hash"):
        ExtractionRequest.model_validate(payload)
    other = tmp_path / "other.py"
    other.write_text("other")
    request2 = prepare_request(tmp_path, ["other.py"])
    with pytest.raises(ValueError, match="not in request"):
        check_candidate_request(facts, request2)


def test_prepare_limits_and_duplicate_files(tmp_path):
    from capability_snapshot_kit.ingestion.requests import prepare_request
    from capability_snapshot_kit.ingestion.sources import MAX_SOURCE_BYTES

    (tmp_path / "large").write_bytes(b"a" * (MAX_SOURCE_BYTES + 1))
    with pytest.raises(ValueError, match="too large"):
        prepare_request(tmp_path, ["large"])
    document(tmp_path)
    with pytest.raises(ValueError, match="duplicate"):
        prepare_request(tmp_path, ["agent.py", "agent.py"])


def test_cli_offline_prepare_and_candidate_export(tmp_path, capsys):
    from capability_snapshot_kit.ingestion.cli import main

    facts = document(tmp_path)
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(facts.model_dump_json())
    request_path = tmp_path / "request.json"
    assert (
        main(
            [
                "prepare",
                "--source-root",
                str(tmp_path),
                "--include",
                "agent.py",
                "--spec-root",
                str(Path(__file__).resolve().parents[2] / "capability_specs"),
                "--output",
                str(request_path),
            ]
        )
        == 0
    )
    specs = Path(__file__).resolve().parents[2] / "capability_specs"
    output = tmp_path / "delivery"
    assert (
        main(
            [
                "export",
                "--candidate",
                str(candidate_path),
                "--request",
                str(request_path),
                "--source-root",
                str(tmp_path),
                "--spec-root",
                str(specs),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    provenance = json.loads((output / "provenance.json").read_text())
    assert provenance["facts"]["module.intent_router"]["basis"] == "declared"
    assert main(["validate", "--input", str(output / "bundle")]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "export",
                "--candidate",
                str(candidate_path),
                "--request",
                str(request_path),
                "--source-root",
                str(tmp_path),
                "--spec-root",
                str(specs),
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().err)["status"] == "ERROR"


def test_extractor_is_explicit_and_cannot_self_promote(tmp_path):
    from capability_snapshot_kit.ingestion.requests import (
        extract_document,
        prepare_request,
    )

    facts = document(tmp_path)

    class Extractor:
        def extract(self, request):
            assert request.request_version == "1.0"
            return facts

    result = extract_document(Extractor(), prepare_request(tmp_path, ["agent.py"]))
    assert result == facts
    # Trust is chosen only by the export service, not by the extractor response.
    assert "trust" not in result.model_dump()


def test_schema_command_and_invalid_collector(tmp_path, capsys):
    from capability_snapshot_kit.ingestion.cli import main

    assert main(["schema"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "FactDocument"
    assert (
        main(
            [
                "export",
                "--collector",
                "builtins:dict",
                "--profile",
                "conversation",
                "--output",
                str(tmp_path / "delivery"),
            ]
        )
        == 1
    )
    assert "collect" in json.loads(capsys.readouterr().err)["message"]


def test_request_includes_profile_and_export_rejects_profile_drift(tmp_path, capsys):
    from capability_snapshot_kit.ingestion.cli import main
    from capability_snapshot_kit.ingestion.requests import prepare_request

    facts = document(tmp_path)
    request = prepare_request(tmp_path, ["agent.py"])
    assert request.evaluation_spec["protocol"]["agent_capability_groups"] == {
        "agent.conversation": ["dialogue.respond", "result.final_response"]
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(request.model_dump_json())
    candidate = tmp_path / "candidate.json"
    candidate.write_text(facts.model_dump_json())
    assert (
        main(
            [
                "export",
                "--candidate",
                str(candidate),
                "--request",
                str(request_path),
                "--source-root",
                str(tmp_path),
                "--spec-root",
                "capability_specs",
                "--output",
                str(tmp_path / "wrong_profile"),
            ]
        )
        == 1
    )
    assert "profile differs" in json.loads(capsys.readouterr().err)["message"]


def test_imported_request_enforces_file_limit_before_extractor(tmp_path):
    import hashlib

    from capability_snapshot_kit.ingestion.requests import (
        ExtractionRequest,
        SourceText,
        extract_document,
        prepare_request,
    )
    from capability_snapshot_kit.ingestion.sources import MAX_SOURCE_BYTES

    document(tmp_path)
    request = prepare_request(tmp_path, ["agent.py"])
    source = request.sources["agent.py"]
    oversized = "x" * (MAX_SOURCE_BYTES + 1)
    reference = source.reference.model_copy(
        update={"sha256": hashlib.sha256(oversized.encode()).hexdigest()}
    )
    unchecked = request.model_copy(
        update={
            "sources": {
                "agent.py": SourceText.model_construct(
                    reference=reference, content=oversized
                )
            }
        }
    )
    with pytest.raises(ValueError, match="too large"):
        ExtractionRequest.model_validate_json(unchecked.model_dump_json())

    class MustNotRun:
        def extract(self, request):
            pytest.fail("Extractor must not receive oversized imported content")

    with pytest.raises(ValueError, match="too large"):
        extract_document(MustNotRun(), unchecked)


def test_candidate_cannot_relabel_documentation_as_trace(tmp_path):
    from capability_snapshot_kit.ingestion.models import FactDocument
    from capability_snapshot_kit.ingestion.requests import (
        check_candidate_request,
        prepare_request,
    )

    facts = document(tmp_path)
    request = prepare_request(tmp_path, ["agent.py"])
    payload = facts.model_dump(mode="json")
    payload["sources"]["implementation"]["kind"] = "trace"
    with pytest.raises(ValueError, match="not in request"):
        check_candidate_request(FactDocument.model_validate(payload), request)
