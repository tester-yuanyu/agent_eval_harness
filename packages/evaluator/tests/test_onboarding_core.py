from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_comparison import loaded
from test_gating import policy

from eval_framework.assertions import run_assertions
from eval_framework.capabilities import CapabilityBundle, CapabilityRegistry
from eval_framework.dataset_validator import validate_dataset
from eval_framework.gating import evaluate_gate
from eval_framework.provider import AdapterOutput
from eval_framework.schemas import DatasetBundle, EvalCase, ExecutionProfile, RunConfig
from eval_framework.scoring import score_assertions
from eval_framework.tool_catalog import ToolCatalog


def config(*checks, channel="returned"):
    return {"checks": list(checks), "channel": channel}


def check(path="/answer", operator="equals", expected="ok"):
    return {"path": path, "operator": operator, "expected": expected}


def case(scope="end_to_end", **config_updates):
    return EvalCase.model_validate(
        {
            "schema_version": "1.0",
            "case_id": "generic-1",
            "task_id": "sdk",
            "scenario_type": "normal",
            "test_scope": scope,
            "target": "sdk.RunResult",
            "execution": {"user_input": "serialize", "tool_profile": "none"},
            "oracle": {
                "evaluation": {
                    "checks": [
                        {
                            "name": "observations_match",
                            "weight": 1,
                            "critical": True,
                            "config": config(check(), **config_updates),
                        }
                    ]
                }
            },
        }
    )


def registry():
    return CapabilityRegistry(
        CapabilityBundle(
            root=".",
            provider_id="other_agent",
            bundle_format_version="3.0",
            capability_bundle_sha256="a" * 64,
            documents=(),
        )
    )


def dataset(item):
    return DatasetBundle(
        path="cases.jsonl",
        sha256="a" * 64,
        schema_versions=["1.0"],
        dataset_version="1",
        total_count=1,
        cases=[item],
        execution_profiles={"none": ExecutionProfile(allowed_tools=[])},
    )


def output(observations):
    return AdapterOutput(
        None,
        [],
        None,
        [],
        None,
        observations=observations,
        evidence_status="UNAVAILABLE",
    )


@pytest.mark.parametrize("scope", ["module", "link", "end_to_end"])
def test_generic_observation_case_needs_no_fictional_intent_or_goal(scope):
    value = case(scope)
    report = validate_dataset(dataset(value), capabilities=registry())
    assert report.valid, report.issues
    results = run_assertions(value, output({"answer": "ok"}), registry())
    assert results[0].passed is True
    assert results[0].native_scores


def test_optional_execution_payload_is_separate_from_oracle():
    value = case()
    payload = value.execution.model_dump()
    payload["adapter_input"] = {
        "input": {"operation": "serialize"},
        "preconditions": [],
    }
    execution = type(value.execution).model_validate(payload)
    assert execution.adapter_input == payload["adapter_input"]
    assert "expected" not in execution.model_dump_json()


@pytest.mark.parametrize("actual,expected", [({}, None), ({"answer": None}, True)])
def test_missing_observation_is_not_json_null(actual, expected):
    from eval_framework.observation_assertions import evaluate_observations

    result = evaluate_observations(actual, config(check(expected=None)))
    assert result[0] is expected


def test_partial_observations_preserve_known_critical_failure():
    value = case()
    value.oracle.evaluation.checks[0].config = config(
        check(),
        check("/missing", expected=None),
    )
    results = run_assertions(
        value,
        replace(output({"answer": "wrong"}), execution_completed=False),
        registry(),
    )
    assert results[0].passed is False
    assert score_assertions(results, 0)[1] == "FAIL"


def test_incomplete_return_cannot_pass_even_when_available_values_match():
    result = run_assertions(
        case(), replace(output({"answer": "ok"}), execution_completed=False), registry()
    )[0]
    assert result.passed is None


def test_independent_channel_never_trusts_returned_observations():
    value = case(channel="independent")
    report = validate_dataset(dataset(value), capabilities=registry())
    assert not report.valid
    result = run_assertions(
        value, replace(output({"answer": "ok"}), evidence_status="COMPLETE"), registry()
    )[0]
    assert result.passed is None
    report = validate_dataset(
        dataset(value), capabilities=registry(), environment_state_available=True
    )
    assert report.valid, report.issues
    result = run_assertions(
        value,
        replace(
            output({"answer": "ok"}),
            snapshot={"answer": "wrong"},
            evidence_status="PARTIAL",
        ),
        registry(),
    )[0]
    assert result.passed is False


@pytest.mark.parametrize("path", ["answer", "#/answer", "/bad~", "/bad~2", 3])
def test_observation_config_rejects_non_json_pointers(path):
    from eval_framework.observation_assertions import ObservationCheckConfig

    with pytest.raises(ValidationError):
        ObservationCheckConfig.model_validate(config(check(path)))


@pytest.mark.parametrize(
    "bad",
    [
        {"checks": []},
        config(check(operator="execute")),
        config({"path": "/answer", "operator": "equals"}),
        config(check(operator="contains", expected=3)),
        config(
            check(operator="schema_valid", expected={"$ref": "https://evil/schema"})
        ),
        {**config(check()), "channel": "stdout"},
    ],
)
def test_observation_config_rejects_unsupported_or_unsafe_contract(bad):
    from eval_framework.observation_assertions import ObservationCheckConfig

    with pytest.raises(ValidationError):
        ObservationCheckConfig.model_validate(bad)


@pytest.mark.parametrize(
    "operator,expected,passed",
    [
        ("equals", "hello.txt", True),
        ("contains", "lo.", True),
        ("not_contains", "bad", True),
        ("ends_with", ".txt", True),
        ("ends_with", ".csv", False),
        ("schema_valid", {"type": "string"}, True),
        ("schema_valid", {"type": "integer"}, False),
    ],
)
def test_fixed_observation_operators(operator, expected, passed):
    from eval_framework.observation_assertions import evaluate_observations

    result = evaluate_observations(
        {"a/b": {"~key": ["hello.txt"]}},
        config(check("/a~1b/~0key/0", operator, expected)),
    )
    assert result[0] is passed


def test_json_pointer_array_index_is_canonical():
    from eval_framework.observation_assertions import evaluate_observations

    for pointer in ("/values/00", "/values/-", "/values/-1"):
        assert (
            evaluate_observations(
                {"values": [None]}, config(check(pointer, expected=None))
            )[0]
            is None
        )


@pytest.mark.parametrize(
    "metadata", [{}, {"release_eligible": False}, {"release_eligible": "true"}]
)
def test_intake_cannot_pass_release_without_explicit_eligibility(
    case_result_factory,
    metadata,
):
    candidate = loaded(case_result_factory(), onboarding=metadata)
    result = evaluate_gate(candidate, policy())
    assert result.conclusion == "FAIL"
    assert any(item.code == "ONBOARDING_RELEASE_INELIGIBLE" for item in result.checks)


def test_gate_preserves_legacy_and_eligible_run_behavior(case_result_factory):
    for metadata in (None, {"release_eligible": True}):
        candidate = loaded(case_result_factory(), onboarding=metadata)
        assert evaluate_gate(candidate, policy()).conclusion == "PASS"


def test_runner_copies_observations_and_onboarding(tmp_path):
    from eval_framework.diagnostics import DiagnosticRegistry
    from eval_framework.provider import ProviderExceptionInfo
    from eval_framework.runner import run_provider_evaluation

    class Provider:
        provider_id = "other_agent"
        provider_version = "1"
        capabilities = registry()
        tools = ToolCatalog(profiles={"none": frozenset()}, tools={})
        diagnostics = DiagnosticRegistry()

        def create_runtime(self, execution, session_id, scope):
            return SimpleNamespace()

        def run_full(self, runtime, execution, scope):
            return output({"answer": "ok"})

        def cleanup(self, runtime):
            pass

        def runtime_metadata(self, runtime):
            return {}

        def tool_version(self, runtime):
            return "none"

        def classify_exception(self, exc):
            return ProviderExceptionInfo(
                execution_status="AGENT_EXCEPTION",
                exception={"type": type(exc).__name__},
            )

    bundle = dataset(case()).model_copy(
        update={
            "onboarding": {
                "release_eligible": False,
                "source": "verified-delivery",
            }
        }
    )
    result = run_provider_evaluation(
        bundle,
        RunConfig(run_mode="framework_self_test"),
        Provider(),
        output_dir=tmp_path,
    )
    assert result.onboarding == bundle.onboarding
    assert result.cases[0].observations == {"answer": "ok"}
    assert result.cases[0].quality_conclusion == "PASS"
    assert result.summary.agent_case_pass_rate is None


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def write_v3_bundle(root: Path):
    (root / "schemas").mkdir()
    tool = {
        "snapshot_id": "tool.read",
        "snapshot_type": "tool",
        "snapshot_format_version": "3.0",
        "contract_version": "1.0",
        "tool_name": "read",
        "side_effects": [],
        "idempotency_rules": {"mode": "READ_ONLY"},
    }
    tool["snapshot_sha256"] = _digest(tool)
    (root / "tool.json").write_text(json.dumps(tool))
    reference = {
        key: tool[key]
        for key in (
            "snapshot_id",
            "snapshot_type",
            "snapshot_format_version",
            "contract_version",
            "snapshot_sha256",
        )
    }
    reference["path"] = "tool.json"
    agent = {
        "snapshot_id": "agent.other",
        "snapshot_type": "agent",
        "snapshot_format_version": "3.0",
        "contract_version": "1.0",
        "agent_id": "other_agent",
        "capability_bundle_sha256": _digest([reference]),
        "module_refs": [],
        "intent_refs": [],
        "tool_refs": [reference],
        "scope_refs": [],
        "chain_refs": [],
        "evidence_refs": [],
        "boundary_refs": [],
    }
    agent["snapshot_sha256"] = _digest(agent)
    (root / "agent.json").write_text(json.dumps(agent))
    for name in ("agent", "tool"):
        (root / "schemas" / f"{name}.schema.json").write_text('{"type":"object"}')
    return agent, tool


def test_neutral_v3_loader_preserves_payloads_and_mini_wrapper(tmp_path):
    from eval_framework.capability_loader import load_capability_bundle
    from eval_framework.providers.mini_agent.capability_adapter import (
        load_mini_agent_capability_bundle,
    )

    agent, tool = write_v3_bundle(tmp_path)
    bundle = load_capability_bundle(
        tmp_path, expected_sha256=agent["capability_bundle_sha256"]
    )
    assert bundle.provider_id == "other_agent"
    assert bundle.get_document("tool.read").payload == tool
    assert bundle.get_document("agent.other").payload == agent
    assert CapabilityRegistry(bundle)._modules == {}
    normalized = load_mini_agent_capability_bundle(tmp_path)
    assert normalized.get_document("tool.read").payload["tool_type"] == "read"
    assert "tool_type" not in bundle.get_document("tool.read").payload


def test_neutral_loader_rejects_changed_snapshot(tmp_path):
    from eval_framework.capability_loader import load_capability_bundle

    write_v3_bundle(tmp_path)
    tool = json.loads((tmp_path / "tool.json").read_text())
    tool["tool_name"] = "tampered"
    (tmp_path / "tool.json").write_text(json.dumps(tool))
    with pytest.raises(ValueError, match="hash mismatch"):
        load_capability_bundle(tmp_path)


def test_runner_preserves_observation_mismatch_after_provider_timeout(tmp_path):
    from eval_framework.diagnostics import DiagnosticRegistry
    from eval_framework.provider import ProviderExceptionInfo
    from eval_framework.runner import _run_case

    class Provider:
        capabilities = registry()
        diagnostics = DiagnosticRegistry()

        def create_runtime(self, execution, session_id, scope):
            return object()

        def run_full(self, runtime, execution, scope):
            raise TimeoutError("operation interrupted after partial observations")

        def classify_exception(self, exc):
            return ProviderExceptionInfo(
                execution_status="MODEL_TIMEOUT",
                exception={"type": "TimeoutError"},
                output=output({"answer": "wrong"}),
            )

        def runtime_metadata(self, runtime):
            return {}

        def cleanup(self, runtime):
            pass

        def tool_version(self, runtime):
            return "none"

    result, _ = _run_case(
        case(),
        RunConfig(run_mode="framework_self_test"),
        Provider(),
        evaluator_run_id="partial",
        trial_id="trial_001",
        run_directory=tmp_path,
    )
    assert result.execution_status == "MODEL_TIMEOUT"
    assert result.quality_conclusion == "FAIL"
    assert result.observations == {"answer": "wrong"}


@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "#/$defs/missing"},
        {"$ref": "#missing-anchor"},
        {"$dynamicRef": "#missing-anchor"},
        {
            "$defs": {"valid": {"type": "string"}},
            "properties": {
                "unused": {"$ref": "#/$defs/missing"},
            },
        },
        {"$ref": "#/title", "title": "not a schema"},
    ],
)
def test_observation_schema_rejects_unresolved_local_references_before_run(schema):
    from eval_framework.observation_assertions import ObservationCheckConfig

    with pytest.raises(ValidationError, match="reference"):
        ObservationCheckConfig.model_validate(
            config(check(operator="schema_valid", expected=schema))
        )


@pytest.mark.parametrize(
    "schema",
    [
        {"$defs": {"text": {"type": "string"}}, "$ref": "#/$defs/text"},
        {"$defs": {"text": {"$anchor": "text", "type": "string"}}, "$ref": "#text"},
        {
            "$defs": {"text": {"$dynamicAnchor": "text", "type": "string"}},
            "$dynamicRef": "#text",
        },
        {
            "$defs": {
                "scope": {
                    "$id": "urn:scope",
                    "$defs": {"inner": {"type": "string"}},
                    "$ref": "#/$defs/inner",
                }
            },
            "$ref": "#/$defs/scope",
        },
    ],
)
def test_local_reference_closure_preserves_valid_pointers_and_anchors(schema):
    from eval_framework.observation_assertions import (
        evaluate_observations,
        validate_schema_references,
    )

    validate_schema_references(schema)
    assert (
        evaluate_observations(
            {"answer": "text"}, config(check(operator="schema_valid", expected=schema))
        )[0]
        is True
    )
