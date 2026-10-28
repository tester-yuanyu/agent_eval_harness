from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from dataset_builder.policies import (
    POLICY_MODELS,
    PolicySet,
    load_policy,
    load_policy_set,
    validate_kernel_policy_compatibility,
)
from dataset_builder.suite_config import PathReference, PolicyReferences


def _payloads() -> dict[str, dict]:
    return {
        "source": {
            "policy_kind": "source",
            "policy_version": "1.0",
            "schema_version": "1.0",
            "config": {
                "allowed_source_bases": ["suite_dir", "projects_root"],
                "unknown_capability_behavior": "preserve",
                "require_hash_binding": True,
            },
        },
        "coverage": {
            "policy_kind": "coverage",
            "policy_version": "1.0",
            "schema_version": "1.0",
            "config": {"distribution_fields": []},
        },
        "generation": {
            "policy_kind": "generation",
            "policy_version": "1.0",
            "schema_version": "1.0",
            "config": {
                "candidate_protocol": {
                    "allowed_intents": ["query_user"],
                    "allowed_statuses": ["READY"],
                    "allowed_next_actions": ["CALL_TOOL"],
                    "allowed_scenario_types": ["normal"],
                    "allowed_difficulties": ["easy"],
                    "rule_refs_required": True,
                },
                "compilation": {
                    "case_id_prefix": "TEST-",
                    "case_id_width": 3,
                    "task_ids": {"query_user": "intent-query-user"},
                    "scenario_type_map": {},
                    "labels": [{"source": "literal", "value": "test"}],
                    "execution": {
                        "tool_profile": "shadow",
                        "allowed_tools": None,
                        "fault_injection": {},
                        "max_steps": 1,
                        "timeout_seconds": 1.0,
                    },
                    "user_responses_by_intent": {},
                    "cleanup_by_intent": {},
                    "oracle_reason": "contract",
                    "assertions": [
                        {
                            "name": "intent_match",
                            "weight": 1,
                            "critical": True,
                            "config": {},
                        }
                    ],
                },
            },
        },
        "validation": {
            "policy_kind": "validation",
            "policy_version": "1.0",
            "schema_version": "1.0",
            "config": {
                "validation": {
                    "decision_protocol": None,
                    "capability_by_intent": {},
                    "parameters_schema_pointer": "/parameters_schema",
                    "missing_parameters_pointer": "/missing_parameters",
                    "allowed_parameters_by_intent": {},
                    "omit_null_parameters": True,
                    "status_rules": {},
                    "forbidden_intents": [],
                    "execution_parameter_names": [],
                    "require_slot_scenario_match": True,
                    "require_rule_refs_match": True,
                },
                "quality": {
                    "minimum_input_length": 1,
                    "forbidden_phrases": [],
                    "sensitive_phrases": [],
                    "compound_markers": [],
                    "compound_forbidden_intents": [],
                },
                "enabled_gates": [
                    "evaluator",
                    "capability_snapshot",
                    "contract",
                    "coverage",
                    "duplicate",
                    "leakage",
                    "quality",
                ],
            },
        },
        "review": {
            "policy_kind": "review",
            "policy_version": "1.0",
            "schema_version": "1.0",
            "config": {
                "locale": "zh-CN",
                "require_all_cases": True,
                "required_fields": ["case_id", "scenario_type"],
            },
        },
        "freeze": {
            "policy_kind": "freeze",
            "policy_version": "1.0",
            "schema_version": "1.0",
            "config": {
                "non_overwrite": True,
                "require_frozen_bundle": True,
                "versioning": "explicit_new_version",
            },
        },
    }


def _write_policy_set(root: Path) -> PolicyReferences:
    references = {}
    for kind, payload in _payloads().items():
        path = root / f"{kind}.json"
        path.write_text(json.dumps(payload))
        references[kind] = PathReference(base="suite_dir", path=path.name)
    return PolicyReferences.model_validate(references)


def test_all_six_policy_envelopes_are_strict_and_versioned():
    payloads = _payloads()

    assert set(POLICY_MODELS) == set(payloads)
    for kind, payload in payloads.items():
        policy = POLICY_MODELS[kind].model_validate(payload)
        assert policy.policy_kind == kind
        assert policy.policy_version == "1.0"
        assert policy.schema_version == "1.0"

        unknown = deepcopy(payload)
        unknown["unexpected"] = True
        with pytest.raises(ValidationError, match="extra"):
            POLICY_MODELS[kind].model_validate(unknown)


def test_policy_loader_rejects_kind_mismatch_and_missing_file(tmp_path):
    payload = _payloads()["source"]
    (tmp_path / "source.json").write_text(json.dumps(payload))

    loaded = load_policy(
        PathReference(base="suite_dir", path="source.json"),
        suite_dir=tmp_path,
        expected_kind="source",
    )
    assert loaded.policy_kind == "source"

    with pytest.raises(ValueError, match="expected policy_kind"):
        load_policy(
            PathReference(base="suite_dir", path="source.json"),
            suite_dir=tmp_path,
            expected_kind="coverage",
        )
    with pytest.raises(FileNotFoundError):
        load_policy(
            PathReference(base="suite_dir", path="missing.json"),
            suite_dir=tmp_path,
            expected_kind="source",
        )


def test_policy_paths_reject_absolute_and_parent_traversal():
    for path in ("/tmp/source.json", "../source.json", "a/../source.json"):
        with pytest.raises(ValidationError, match="relative"):
            PathReference(base="suite_dir", path=path)


def test_complete_policy_set_loads_exactly_one_of_each_kind(tmp_path):
    references = _write_policy_set(tmp_path)

    policy_set = load_policy_set(references, suite_dir=tmp_path)

    assert isinstance(policy_set, PolicySet)
    assert policy_set.source.policy_kind == "source"
    assert policy_set.coverage.policy_kind == "coverage"
    assert policy_set.generation.policy_kind == "generation"
    assert policy_set.validation.policy_kind == "validation"
    assert policy_set.review.policy_kind == "review"
    assert policy_set.freeze.policy_kind == "freeze"


def test_kernel_rejects_policy_that_weakens_lifecycle_invariants(tmp_path):
    policy_set = load_policy_set(_write_policy_set(tmp_path), suite_dir=tmp_path)

    validate_kernel_policy_compatibility(
        policy_set,
        source_references=[PathReference(base="suite_dir", path="source.json")],
    )

    cases = [
        (
            policy_set.model_copy(
                update={
                    "source": policy_set.source.model_copy(
                        update={
                            "config": policy_set.source.config.model_copy(
                                update={"allowed_source_bases": ["projects_root"]}
                            )
                        }
                    )
                }
            ),
            "source base",
        ),
        (
            policy_set.model_copy(
                update={
                    "review": policy_set.review.model_copy(
                        update={
                            "config": policy_set.review.config.model_copy(
                                update={"require_all_cases": False}
                            )
                        }
                    )
                }
            ),
            "review every case",
        ),
        (
            policy_set.model_copy(
                update={
                    "freeze": policy_set.freeze.model_copy(
                        update={
                            "config": policy_set.freeze.config.model_copy(
                                update={"non_overwrite": False}
                            )
                        }
                    )
                }
            ),
            "non-overwrite",
        ),
    ]
    for weakened, message in cases:
        with pytest.raises(ValueError, match=message):
            validate_kernel_policy_compatibility(
                weakened,
                source_references=[
                    PathReference(base="suite_dir", path="source.json")
                ],
            )
