"""实际 MiniAgent fixture 经 native Harness 的离线验证。"""

import json
from pathlib import Path

import pytest
from eval_contracts.full_readiness import FullCase, FullRequest, reference_checks
from eval_contracts.readiness import digest_bytes

ROOT = Path(__file__).resolve().parents[4]


def test_native_full_delivery_reference(tmp_path):
    pytest.importorskip("minimal_agent")
    from eval_framework.benchmark.full_readiness import run

    delivery = (
        ROOT
        / "packages/dataset-builder/tests/fixtures"
        / "full_tools_fixture_v1_full_eval_20261020"
    )
    manifest_bytes = (delivery / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    cases = []
    for ds in manifest["datasets"]:
        if ds["definition_kind"] == "behavior_case":
            for line in (delivery / ds["path"]).read_text().splitlines():
                row = json.loads(line)
                cases.append(
                    FullCase(
                        case_id=row["case_id"], source_path=ds["path"], payload=row
                    )
                )
    parsed = FullRequest(
        source_manifest_sha256=digest_bytes(manifest_bytes),
        bundle_sha256=manifest["bundle_sha256"],
        source_files=manifest["files_sha256"],
        definition_counts=manifest["definition_counts"],
        tool_schema=json.loads(
            (delivery / "source_delivery/bundle/tools/query_user_info.json").read_text()
        )["function_schema"],
        cases=cases,
    )
    request = tmp_path / "request.json"
    # Deliberately incorrect private oracle cannot become the observed result.
    selected = next(
        c
        for c in parsed.cases
        if c.payload.get("oracle", {}).get("checks", [{}])[0].get("expected") == "OK"
        and c.payload.get("input", {}).get("operation") == "invoke_tool"
        and c.payload.get("target_id") == "tool.query_user_info"
    )
    selected.payload["oracle"]["checks"][0]["expected"] = "PRIVATE_ORACLE_SENTINEL"
    request.write_text(parsed.model_dump_json())
    evidence = run(request, tmp_path / "logs", ROOT / "examples/mini_agent")
    assert len(evidence.results) == 2
    assert {r.tool_result["code"] for r in evidence.results} == {"OK", "EMPTY"}
    assert all(r.evidence_complete and not r.errors for r in evidence.results)
    row = next(r for r in evidence.results if r.case_id == selected.case_id)
    assert not reference_checks(selected, row)["oracle_0"]
    assert evidence.dataset_sha256 == parsed.sha256()
    from inspect_ai.log import read_eval_log

    for path in (tmp_path / "logs").glob("*.eval"):
        log = read_eval_log(path)
        for sample in log.samples:
            assert "PRIVATE_ORACLE_SENTINEL" not in sample.model_dump_json()


def test_schema_projection_retains_integer_boundary():
    from eval_framework.benchmark.full_readiness import function_schema
    from jsonschema import Draft202012Validator

    original = {
        "name": "query",
        "parameters": {
            "type": "object",
            "properties": {
                "value": {"type": "integer", "title": "Value", "exclusiveMinimum": 0}
            },
            "required": ["value"],
        },
    }
    projected = function_schema(original)
    for value in [-1, 0, 0.5, 1, 2, None, "1"]:
        assert Draft202012Validator(original["parameters"]).is_valid(
            {"value": value}
        ) == Draft202012Validator(projected["parameters"]).is_valid({"value": value})
