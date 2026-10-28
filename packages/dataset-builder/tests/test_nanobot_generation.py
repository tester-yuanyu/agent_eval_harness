import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SOURCE = Path(__file__).resolve().parent / "fixtures/nanobot_snapshot_handoff_v2"
HASH = "b5dbc1184326a2d3edd641b046b6cba7029bd6f71ef7f561ac9367a787d6655f"


def load():
    from dataset_builder.nanobot_generation.inputs import load_input

    return load_input(SOURCE, HASH)


def test_nanobot_input_preserves_unknown_and_normalizes_without_mutation():
    data = load()
    assert len(data["artifacts"]) == 35
    assert len(data["primary_targets"]) == 31
    assert len(data["gaps"]) == 30
    assert len(data["files_sha256"]) == 112  # includes external manifest itself
    tool = data["artifacts"]["tool.read_file"]
    assert tool["payload"]["capabilities"][0]["support_status"] == "unknown"
    assert (
        tool["parameter_schema"]
        == tool["payload"]["function_schema"]["function"]["parameters"]
    )
    assert tool["parameter_schema_pointer"] == "/function_schema/function/parameters"
    assert data["capability_ir"]["support_status"] == "unknown"
    assert data["agent_id"] == "nanobot"


def test_source_hash_and_wrong_agent_are_rejected(tmp_path):
    from dataset_builder.nanobot_generation.inputs import load_input

    with pytest.raises(ValueError, match="hash"):
        load_input(SOURCE, "0" * 64)
    p = tmp_path / "source"
    p.mkdir()
    (p / "manifest.json").write_text(
        json.dumps({"files_sha256": {"../escape": "0" * 64}})
    )
    with pytest.raises(ValueError, match="unsafe"):
        load_input(p, HASH)


def test_all_tools_have_valid_invalid_schema_cases_including_empty_objects():
    from dataset_builder.nanobot_generation.schema_cases import schema_examples

    for name, artifact in load()["artifacts"].items():
        if not name.startswith("tool."):
            continue
        schema = artifact["parameter_schema"]
        cases = schema_examples(schema)
        assert {c["expected_valid"] for c in cases} == {True, False}, name
        assert len({json.dumps(c["instance"], sort_keys=True) for c in cases}) == len(
            cases
        )
        for case in cases:
            assert (
                Draft202012Validator(schema).is_valid(case["instance"])
                == case["expected_valid"]
            )


def test_nested_boundaries_nullable_enums_required_and_additional():
    from dataset_builder.nanobot_generation.schema_cases import schema_examples

    artifacts = load()["artifacts"]
    cases = schema_examples(artifacts["tool.apply_patch"]["parameter_schema"])
    instances = [c["instance"] for c in cases if isinstance(c["instance"], dict)]
    assert any(
        len(i.get("edits", [])) == 20
        for i in instances
        if isinstance(i.get("edits"), list)
    )
    assert any(
        len(i.get("edits", [])) == 21
        for i in instances
        if isinstance(i.get("edits"), list)
    )
    assert any(
        i.get("edits")
        and isinstance(i["edits"], list)
        and isinstance(i["edits"][0], dict)
        and i["edits"][0].get("action") == "add"
        for i in instances
    )
    assert any(
        i.get("edits")
        and isinstance(i["edits"], list)
        and isinstance(i["edits"][0], dict)
        and "path" not in i["edits"][0]
        for i in instances
    )
    cases = schema_examples(artifacts["tool.exec"]["parameter_schema"])
    assert any(
        isinstance(c["instance"], dict)
        and c["instance"].get("yield_time_ms") == 30001
        and not c["expected_valid"]
        for c in cases
    )
    assert any(
        isinstance(c["instance"], dict)
        and "yield_time_ms" in c["instance"]
        and c["instance"]["yield_time_ms"] is None
        and c["expected_valid"]
        for c in cases
    )


def test_unknown_keyword_never_silently_generates_unsupported_samples():
    from dataset_builder.nanobot_generation.schema_cases import schema_examples

    with pytest.raises(ValueError, match="unsupported"):
        schema_examples({"type": "string", "pattern": "^specific$"})


def test_generation_covers_every_snapshot_and_preserves_boundaries():
    from dataset_builder.nanobot_generation.cases import build_cases

    data = load()
    cases, blockers = build_cases(data)
    assert {c["target_id"] for c in cases} == set(data["artifacts"])
    assert any(b["code"] == "CRITICAL_CHAIN_NOT_DECLARED" for b in blockers)
    assert any(
        b["code"] == "CONVERSATION_BOUNDARY_IMPLEMENTATION_MISMATCH" for b in blockers
    )
    behavior = [c for c in cases if c["kind"] == "behavior_candidate"]
    assert {c["target_id"] for c in behavior if c["layer"] == "modules"} >= {
        k for k in data["artifacts"] if k.startswith("module.")
    }
    assert all(
        c["execution_readiness"] == "blocked"
        for c in cases
        if c["target_id"].startswith("tool.") and c["kind"] == "behavior_candidate"
    )
    assert all(
        c["input"].get("operation") != "invoke_tool"
        for c in cases
        if c["layer"] == "end_to_end"
    )
    assert all(
        c["runtime_execution"] == "NOT_RUN" and c["approval"] == "PENDING"
        for c in cases
    )


def test_validator_rejects_false_schema_oracle_and_missing_source_anchor():
    from dataset_builder.nanobot_generation.cases import build_cases
    from dataset_builder.nanobot_generation.validation import validate_cases

    data = load()
    cases, blockers = build_cases(data)
    assert validate_cases(data, cases, blockers)["valid"]
    bad = copy.deepcopy(cases)
    case = next(c for c in bad if c["kind"] == "schema_contract")
    case["oracle"]["checks"][0]["expected"] = not case["oracle"]["checks"][0][
        "expected"
    ]
    assert not validate_cases(data, bad, blockers)["valid"]
    bad = copy.deepcopy(cases)
    case = next(c for c in bad if c["kind"] == "behavior_candidate")
    case["source_refs"][0]["anchor"] = "NONEXISTENT-ANCHOR-1234"
    assert not validate_cases(data, bad, blockers)["valid"]


def test_nanobot_delivery_independent_movable_no_overwrite_tamper(tmp_path):
    from dataset_builder.nanobot_generation.delivery import generate, verify

    out = tmp_path / "nanobot"
    report = generate(SOURCE, out, HASH)
    assert report["valid"]
    assert verify(out)["valid"]
    assert (out / "datasets/tools/tool.read_file.schema_contract.jsonl").exists()
    assert (out / "datasets/critical_links/README.md").exists()
    assert "[x]" not in (out / "review.md").read_text()
    assert json.loads((out / "manifest.json").read_text())["agent_id"] == "nanobot"
    with pytest.raises(FileExistsError):
        generate(SOURCE, out, HASH)
    moved = tmp_path / "moved"
    out.rename(moved)
    assert verify(moved)["valid"]
    target = moved / "datasets/tools/tool.read_file.schema_contract.jsonl"
    target.write_text(target.read_text() + "{}\n")
    assert not verify(moved)["valid"]


def test_failed_publication_does_not_leave_output(tmp_path, monkeypatch):
    from dataset_builder.nanobot_generation import delivery

    def fail(*_args):
        raise RuntimeError("injected publication failure")

    monkeypatch.setattr(delivery, "_publish", fail)
    with pytest.raises(RuntimeError, match="publication failure"):
        delivery.generate(SOURCE, tmp_path / "out", HASH)
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".out-*"))


def test_nanobot_cli_is_explicit_and_mini_agent_path_unchanged():
    from dataset_builder.cli import parser

    args = parser().parse_args(
        [
            "generate-nanobot",
            "--delivery-root",
            str(SOURCE),
            "--expected-bundle-hash",
            HASH,
            "--workspace",
            "/tmp/nanobot-test",
        ]
    )
    assert args.command == "generate-nanobot"
    assert (
        parser()
        .parse_args(["validate-nanobot", "--workspace", "/tmp/nanobot-test"])
        .command
        == "validate-nanobot"
    )
    assert (
        parser().parse_args(["validate-full", "--workspace", "/tmp/mini-test"]).command
        == "validate-full"
    )
