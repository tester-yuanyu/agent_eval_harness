from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from dataset_builder.deepeval_generation import DeepEvalGenerationClient
from dataset_builder.pipeline import (
    compile_candidates,
    generate_candidates,
    prepare_generation,
    validate_draft,
)
from dataset_builder.suite_definition import load_suite


@pytest.fixture
def prepared(tmp_path):
    suite = load_suite("mini_agent_query_user_intent_v2")
    request = prepare_generation(suite, tmp_path)
    candidates = json.loads((suite.suite_dir / "seed_catalog.json").read_text())[
        "candidates"
    ]
    return suite, request, candidates, tmp_path


def golden(candidate, **overrides):
    value = {
        "input": candidate["user_input"],
        "expected_output": json.dumps(candidate, ensure_ascii=False),
        "context": [],
        "additional_metadata": {"synthetic_input_quality": 0.0},
    }
    value.update(overrides)
    return SimpleNamespace(**value)


def client_with_goldens(monkeypatch, suite, candidates, transform=None):
    client = DeepEvalGenerationClient(suite=suite, model="offline")
    index = 0

    def synthesize(context, slot, schema):
        nonlocal index
        candidate = candidates[index]
        index += 1
        assert slot["slot_id"] == candidate["slot_id"]
        assert "Capability IR" in context
        assert '"rule_refs"' in schema
        values = [golden(candidate)]
        return transform(values) if transform else values

    monkeypatch.setattr(client, "_synthesize", synthesize)
    monkeypatch.setattr(client, "_sdk_version", lambda: "4.3.2")
    return client


def test_goldens_compile_validate_and_preserve_audit_without_freeze(
    prepared, monkeypatch
):
    suite, request, candidates, workspace = prepared
    client = client_with_goldens(monkeypatch, suite, candidates)
    raw = generate_candidates(request, client, workspace)
    assert raw.mode == "deepeval"
    assert raw.response == {"candidates": candidates}
    assert len(raw.metadata["goldens"]) == 42
    assert raw.metadata["settings"]["num_evolutions"] == 0
    assert raw.metadata["oracle_status"] == "unreviewed"
    cases = compile_candidates(suite, raw, workspace)
    assert len(cases) == 42
    assert validate_draft(suite, workspace / "draft.jsonl").valid
    manifest = json.loads((workspace / "generation_manifest.json").read_text())
    assert manifest["generator_metadata"]["sdk_version"] == "4.3.2"
    assert manifest["state"] == "DRAFT"
    assert not (workspace / "approval.json").exists()


@pytest.mark.parametrize(
    "broken",
    [
        lambda gs: [],
        lambda gs: gs * 2,
        lambda gs: [SimpleNamespace(**{**vars(gs[0]), "expected_output": None})],
        lambda gs: [
            SimpleNamespace(**{**vars(gs[0]), "expected_output": "```json\n{}"})
        ],
        lambda gs: [SimpleNamespace(**{**vars(gs[0]), "input": "changed meaning"})],
        lambda gs: [golden({**json.loads(gs[0].expected_output), "slot_id": "other"})],
        lambda gs: [golden({**json.loads(gs[0].expected_output), "rule_refs": []})],
        lambda gs: [
            golden(
                {
                    **json.loads(gs[0].expected_output),
                    "scenario_type": "missing_parameter",
                }
            )
        ],
        lambda gs: [
            golden(
                {
                    **json.loads(gs[0].expected_output),
                    "expected_status": "NEED_CLARIFICATION",
                }
            )
        ],
    ],
)
def test_invalid_goldens_fail_without_repair(prepared, monkeypatch, broken):
    suite, request, candidates, _ = prepared
    client = client_with_goldens(monkeypatch, suite, candidates, broken)
    with pytest.raises(ValueError):
        client.generate(request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt", "tampered prompt"),
        ("candidate_schema", {}),
        ("coverage_plan_sha256", "0" * 64),
        ("suite_id", "other-suite"),
        ("suite_config_sha256", "0" * 64),
        ("policy_bindings", []),
    ],
)
def test_stale_request_rejected_before_model_call(prepared, monkeypatch, field, value):
    suite, request, _, _ = prepared
    client = DeepEvalGenerationClient(suite=suite, model="offline")

    def forbidden(*args):
        pytest.fail("model must not be called for stale authoring sources")

    monkeypatch.setattr(client, "_synthesize", forbidden)
    with pytest.raises(ValueError, match="prepared request"):
        client.generate(request.model_copy(update={field: value}))


def test_explicit_credentials_required(monkeypatch, suite):
    monkeypatch.delenv("DATASET_GENERATOR_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "not-used")
    with pytest.raises(RuntimeError, match="DATASET_GENERATOR_MODEL"):
        DeepEvalGenerationClient.from_env(suite)


def test_cli_selects_deepeval_and_emits_draft(prepared, monkeypatch):
    from dataset_builder.cli import main

    suite, _, candidates, workspace = prepared
    client = client_with_goldens(monkeypatch, suite, candidates)
    monkeypatch.setattr(DeepEvalGenerationClient, "from_env", lambda suite: client)
    assert (
        main(
            [
                "generate",
                "--backend",
                "deepeval",
                "--request",
                str(workspace / "generation_request.json"),
                "--workspace",
                str(workspace),
            ]
        )
        == 0
    )
    assert len((workspace / "draft.jsonl").read_text().splitlines()) == 42
    assert (
        json.loads((workspace / "raw_response.json").read_text())["mode"] == "deepeval"
    )


def test_missing_optional_dependency_has_install_instruction(prepared, monkeypatch):
    from importlib.metadata import PackageNotFoundError

    suite, request, _, _ = prepared

    def missing(_):
        raise PackageNotFoundError("deepeval")

    monkeypatch.setattr("dataset_builder.deepeval_generation.version", missing)
    with pytest.raises(RuntimeError, match=r"pip install.*deepeval"):
        DeepEvalGenerationClient(suite=suite, model="offline").generate(request)


@pytest.mark.parametrize("mutation", ["change", "remove", "remove_hash"])
def test_changed_golden_evidence_blocks_validation(prepared, monkeypatch, mutation):
    suite, request, candidates, workspace = prepared
    raw = generate_candidates(
        request, client_with_goldens(monkeypatch, suite, candidates), workspace
    )
    compile_candidates(suite, raw, workspace)
    path = workspace / "raw_response.json"
    if mutation == "change":
        payload = json.loads(path.read_text())
        payload["metadata"]["goldens"] = []
        path.write_text(json.dumps(payload))
    elif mutation == "remove":
        path.unlink()
    else:
        manifest_path = workspace / "generation_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        del manifest["raw_response_sha256"]
        manifest_path.write_text(json.dumps(manifest))
    report = validate_draft(suite, workspace / "draft.jsonl")
    assert not report.valid
    assert any(
        "raw response" in issue for gate in report.gates for issue in gate.issues
    )


def test_compile_rejects_raw_object_that_differs_from_saved_evidence(
    prepared, monkeypatch
):
    from dataset_builder.orchestration import StageExecutionError

    suite, request, candidates, workspace = prepared
    raw = generate_candidates(
        request, client_with_goldens(monkeypatch, suite, candidates), workspace
    )
    changed = raw.model_copy(deep=True)
    changed.response["candidates"][0]["user_input"] = "a different request"
    with pytest.raises(StageExecutionError, match="saved raw response"):
        compile_candidates(suite, changed, workspace)
    assert not (workspace / "draft.jsonl").exists()


@pytest.mark.parametrize(
    "suite_id", ["mini_agent_query_user_intent_v2", "mini_agent_query_user_intent_v3"]
)
def test_real_sdk_preserves_low_quality_negative_slots_offline(
    tmp_path, monkeypatch, suite_id
):
    """Use the real SDK; only the LLM is scripted and all sockets are forbidden."""
    import socket
    from importlib.metadata import PackageNotFoundError, version

    try:
        version("deepeval")
    except PackageNotFoundError:
        # An uninstalled SDK can leave a namespace directory behind; importing
        # that empty namespace does not mean the optional dependency is present.
        pytest.skip("DeepEval optional dependency is not installed")

    monkeypatch.setenv("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
    monkeypatch.setenv("DEEPEVAL_UPDATE_WARNING_OPT_IN", "0")
    monkeypatch.delenv("CONFIDENT_API_KEY", raising=False)
    pytest.importorskip("deepeval")
    from deepeval.models import DeepEvalBaseLLM

    def no_network(*args, **kwargs):
        pytest.fail("offline SDK contract test attempted network access")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    suite = load_suite(suite_id)
    workspace = tmp_path
    request = prepare_generation(suite, workspace)
    candidates = json.loads((suite.suite_dir / "seed_catalog.json").read_text())[
        "candidates"
    ]
    blocked = {
        slot["slot_id"]
        for slot in suite.coverage_plan["slots"]
        if slot.get("acceptance", {}).get("oracle_gaps")
    }

    class OfflineLLM(DeepEvalBaseLLM):
        def __init__(self):
            self.index = 0
            self.calls = []
            super().__init__("offline")

        def load_model(self):
            return self

        def get_model_name(self):
            return "offline-deepeval-contract-test"

        def generate(self, prompt, schema=None):
            self.calls.append(schema.__name__)
            candidate = candidates[self.index]
            match schema.__name__:
                case "SyntheticDataList":
                    assert candidate["slot_id"] in prompt
                    return schema(data=[{"input": candidate["user_input"]}])
                case "InputFeedback":
                    # Even a zero clarity score must not rewrite a missing field.
                    return schema(score=0.0, feedback="Intentionally incomplete")
                case "SyntheticData":
                    if candidate["slot_id"] in blocked:
                        self.index += 1
                    return schema(input=candidate["user_input"])
                case "Response":
                    self.index += 1
                    return schema(response=json.dumps(candidate, ensure_ascii=False))
                case _:
                    pytest.fail(f"unexpected rewrite/evolution call: {schema}")

        async def a_generate(self, *args, **kwargs):
            pytest.fail("expected bounded sequential generation")

    model = OfflineLLM()
    if blocked:
        from dataset_builder.deepeval_generation import SynthesisBlocked

        with pytest.raises(SynthesisBlocked) as caught:
            DeepEvalGenerationClient(suite=suite, model=model).generate(request)
        partial = caught.value.partial_generation
        assert model.index == 42
        assert model.calls.count("Response") == 25
        assert model.calls.count("InputFeedback") == 42
        assert len(partial.metadata["blocked_slots"]) == 17
        assert all(
            entry["goldens"][0]["expected_output"] is None
            for entry in partial.metadata["attempt_audit"]
            if not entry["include_expected_output"]
        )
        return
    raw = generate_candidates(
        request, DeepEvalGenerationClient(suite=suite, model=model), workspace
    )
    assert model.index == 42
    assert model.calls.count("InputFeedback") == 42
    assert raw.response == {"candidates": candidates}
    assert (
        raw.metadata["goldens"][0]["additional_metadata"]["synthetic_input_quality"]
        == 0.0
    )
    compile_candidates(suite, raw, workspace)
    assert validate_draft(suite, workspace / "draft.jsonl").valid


def test_v3_constraints_are_visible_and_rejected_attempts_are_preserved(
    tmp_path, monkeypatch
):
    from copy import deepcopy

    suite = load_suite("mini_agent_query_user_intent_v3")
    request = prepare_generation(suite, tmp_path)
    candidates = json.loads((suite.suite_dir / "seed_catalog.json").read_text())[
        "candidates"
    ]
    client = DeepEvalGenerationClient(suite=suite, model="offline", max_slot_attempts=2)
    monkeypatch.setattr(client, "_sdk_version", lambda: "4.3.2")
    calls = []

    def synthesize(context, slot, schema):
        assert '"omit_null_parameters": true' in context
        assert slot["acceptance"]["description"]
        calls.append(slot["slot_id"])
        candidate = deepcopy(
            next(c for c in candidates if c["slot_id"] == slot["slot_id"])
        )
        if len(calls) == 1:
            candidate["expected_parameters_json"] = '{"user_id": null}'
        elif len(calls) == 2:
            assert "REJECTED_ATTEMPT_DIAGNOSTICS" in context
        return (
            [golden(candidate, expected_output=None)]
            if slot["acceptance"].get("oracle_gaps")
            else [golden(candidate)]
        )

    monkeypatch.setattr(client, "_synthesize", synthesize)
    from dataset_builder.deepeval_generation import SynthesisBlocked

    with pytest.raises(SynthesisBlocked) as caught:
        client.generate(request)
    raw = caught.value.partial_generation
    assert len(calls) == 43
    assert raw.response["candidates"] == [
        c for c in candidates if c["expected_status"] == "READY"
    ]
    assert len(raw.metadata["blocked_slots"]) == 17
    assert all("expected_output" not in item for item in raw.metadata["blocked_slots"])
    attempts = raw.metadata["attempt_audit"]
    assert len(attempts) == 43
    assert attempts[0]["issues"]
    assert "null" in attempts[0]["goldens"][0]["expected_output"]
    assert attempts[1]["issues"] == []
    assert raw.metadata["settings"]["max_slot_attempts"] == 2


def test_retries_stop_at_limit_and_expose_failure_audit(tmp_path, monkeypatch):
    suite = load_suite("mini_agent_query_user_intent_v3")
    request = prepare_generation(suite, tmp_path)
    client = DeepEvalGenerationClient(suite=suite, model="offline", max_slot_attempts=2)
    monkeypatch.setattr(client, "_sdk_version", lambda: "4.3.2")
    monkeypatch.setattr(
        client, "_synthesize", lambda *args: [golden({"user_input": "bad"})]
    )
    with pytest.raises(ValueError, match="exhausted 2") as caught:
        client.generate(request)
    assert len(caught.value.attempt_audit) == 2
    assert all(item["issues"] for item in caught.value.attempt_audit)


@pytest.mark.parametrize("attempts", [0, -1, 11, True, 1.5])
def test_invalid_retry_budget_rejected(attempts):
    with pytest.raises(ValueError):
        DeepEvalGenerationClient(
            suite=load_suite("mini_agent_query_user_intent_v3"),
            model="offline",
            max_slot_attempts=attempts,
        )


def test_exhausted_attempts_persist_even_without_draft(tmp_path, monkeypatch):
    from dataset_builder.orchestration import StageExecutionError

    suite = load_suite("mini_agent_query_user_intent_v3")
    request = prepare_generation(suite, tmp_path)
    client = DeepEvalGenerationClient(suite=suite, model="offline")
    monkeypatch.setattr(client, "_sdk_version", lambda: "4.3.2")
    monkeypatch.setattr(
        client, "_synthesize", lambda *args: [golden({"user_input": "bad"})]
    )
    with pytest.raises(StageExecutionError):
        generate_candidates(request, client, tmp_path)
    failure = json.loads((tmp_path / "generation_failure.json").read_text())
    assert failure["request_id"] == request.request_id
    assert len(failure["attempt_audit"]) == 1
    assert failure["attempt_audit"][0]["goldens"][0]["input"] == "bad"
    assert not (tmp_path / "draft.jsonl").exists()


def test_known_contract_gaps_save_input_only_and_never_compile(tmp_path, monkeypatch):
    from dataset_builder.orchestration import StageExecutionError

    suite = load_suite("mini_agent_query_user_intent_v3")
    request = prepare_generation(suite, tmp_path)
    candidates = json.loads((suite.suite_dir / "seed_catalog.json").read_text())[
        "candidates"
    ]
    client = DeepEvalGenerationClient(suite=suite, model="offline", max_slot_attempts=3)
    monkeypatch.setattr(client, "_sdk_version", lambda: "4.3.2")
    calls = []

    def synthesize(context, slot, schema):
        calls.append(slot["slot_id"])
        candidate = next(c for c in candidates if c["slot_id"] == slot["slot_id"])
        return (
            [golden(candidate, expected_output=None)]
            if slot["acceptance"].get("oracle_gaps")
            else [golden(candidate)]
        )

    monkeypatch.setattr(client, "_synthesize", synthesize)
    with pytest.raises(StageExecutionError, match="contract gaps"):
        generate_candidates(request, client, tmp_path)
    failure = json.loads((tmp_path / "generation_failure.json").read_text())
    assert failure["status"] == "CONTRACT_BLOCKED"
    assert len(calls) == 42
    partial = failure["partial_generation"]
    assert len(partial["response"]["candidates"]) == 25
    assert len(partial["metadata"]["blocked_slots"]) == 17
    assert all(
        c["expected_status"] == "READY" for c in partial["response"]["candidates"]
    )
    assert not (tmp_path / "raw_response.json").exists()
    assert not (tmp_path / "draft.jsonl").exists()


def test_duplicate_inputs_regenerate_without_overwriting_first_golden(
    prepared, monkeypatch
):
    from copy import deepcopy

    suite, request, candidates, _ = prepared
    client = DeepEvalGenerationClient(suite=suite, model="offline", max_slot_attempts=2)
    monkeypatch.setattr(client, "_sdk_version", lambda: "4.3.2")
    calls = []
    second_attempt = 0

    def synthesize(context, slot, schema):
        nonlocal second_attempt
        calls.append(slot["slot_id"])
        candidate = deepcopy(
            next(c for c in candidates if c["slot_id"] == slot["slot_id"])
        )
        if slot["slot_id"] == candidates[4]["slot_id"]:
            second_attempt += 1
            if second_attempt == 1:
                candidate["user_input"] = candidates[0]["user_input"] + "！"
                candidate["expected_parameters_json"] = candidates[0][
                    "expected_parameters_json"
                ]
            else:
                assert "duplicate input" in context
        return [golden(candidate)]

    monkeypatch.setattr(client, "_synthesize", synthesize)
    raw = client.generate(request)
    assert len(calls) == 43
    assert raw.response["candidates"] == candidates
    assert any(
        "duplicate input" in issue
        for entry in raw.metadata["attempt_audit"]
        for issue in entry["issues"]
    )
