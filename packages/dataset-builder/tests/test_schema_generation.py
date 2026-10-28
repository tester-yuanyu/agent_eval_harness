from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from dataset_builder.candidate_parser import parse_candidates
from dataset_builder.capability_profiles import ProfileTrustStore, ProtocolProfile
from dataset_builder.policies import POLICY_MODELS
from dataset_builder.suite_config import SuiteConfig
from dataset_builder.suite_definition import load_suite


def _assert_strict_objects(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            assert schema.get("additionalProperties") is False
            assert set(schema.get("required", [])) == set(
                schema.get("properties", {})
            )
        for value in schema.values():
            _assert_strict_objects(value)
    elif isinstance(schema, list):
        for value in schema:
            _assert_strict_objects(value)


def test_strict_schema_requires_every_property_and_forbids_extras():
    suite = load_suite("mini_agent_intent_v1")
    _assert_strict_objects(suite.batch_type.model_json_schema())


def test_candidate_rejects_extra_field(seed):
    suite = load_suite("mini_agent_intent_v1")
    candidate = copy.deepcopy(seed["candidates"][0])
    candidate["reason"] = "model must not provide this"
    with pytest.raises(ValidationError):
        suite.candidate_type.model_validate(candidate)


@pytest.mark.parametrize("value", ["not-json", "[]", "1"])
def test_parser_rejects_invalid_or_non_object_parameters(
    authored, suite, seed, value
):
    _, _, raw, _ = authored
    changed = copy.deepcopy(seed)
    changed["candidates"][0]["expected_parameters_json"] = value
    raw.response = changed
    with pytest.raises((ValueError, json.JSONDecodeError)):
        parse_candidates(suite, raw)


def test_parser_rejects_enum_and_duplicate_slot(authored, suite, seed):
    _, _, raw, _ = authored
    bad_enum = copy.deepcopy(seed)
    bad_enum["candidates"][0]["difficulty"] = "hard"
    raw.response = bad_enum
    with pytest.raises(ValidationError):
        parse_candidates(suite, raw)
    duplicate = copy.deepcopy(seed)
    duplicate["candidates"][1]["slot_id"] = duplicate["candidates"][0]["slot_id"]
    raw.response = duplicate
    with pytest.raises(ValueError, match="unique"):
        parse_candidates(suite, raw)


def test_suite_definition_schema_matches_checked_in_snapshot():
    root = Path(__file__).resolve().parents[1]
    snapshot = root / "schemas" / "suite_definition.schema.json"

    assert json.loads(snapshot.read_text()) == SuiteConfig.model_json_schema()


def test_policy_schemas_match_checked_in_snapshots():
    root = Path(__file__).resolve().parents[1] / "schemas" / "policies"

    for kind, model in POLICY_MODELS.items():
        snapshot = root / f"{kind}_policy.schema.json"
        assert json.loads(snapshot.read_text()) == model.model_json_schema()


def test_protocol_profile_schemas_match_checked_in_snapshots():
    root = Path(__file__).resolve().parents[1] / "schemas" / "protocol_profiles"
    expected = {
        "protocol_profile.schema.json": ProtocolProfile.model_json_schema(),
        "trust_store.schema.json": ProfileTrustStore.model_json_schema(),
    }

    for filename, schema in expected.items():
        assert json.loads((root / filename).read_text()) == schema
