from __future__ import annotations

from types import SimpleNamespace

import pytest

from dataset_builder.capability_ir import SupportStatus
from dataset_builder.intent_compiler import compile_intent_candidates
from dataset_builder.source_pack import build_source_pack
from dataset_builder.suite_definition import load_suite


def test_source_pack_uses_canonical_ir_as_only_capability_source():
    suite = load_suite("mini_agent_query_user_intent_v1")
    text, manifest = build_source_pack(suite)

    assert "# Capability IR" in text
    assert suite.capability_ir.canonical_sha256 in text
    assert '"intent.query_user"' in text
    assert "capabilities/intents/query_user.json" not in text
    assert manifest[0] == {
        "path": "capability-ir://mini_agent_query_user_intent_v1",
        "sha256": suite.capability_ir.canonical_sha256,
    }


@pytest.mark.parametrize(
    "status", [SupportStatus.UNSUPPORTED, SupportStatus.UNKNOWN]
)
def test_non_supported_ir_cannot_compile_positive_oracles(status):
    suite = SimpleNamespace(
        capability_ir=SimpleNamespace(support_status=status)
    )
    with pytest.raises(ValueError, match="cannot compile positive oracles"):
        compile_intent_candidates([], suite)


def test_ir_drives_intent_parameter_and_decision_contracts():
    suite = load_suite("mini_agent_query_user_intent_v1")
    ir = suite.capability_ir
    assert ir.parameters_schema["properties"]["phone"]["anyOf"][0][
        "pattern"
    ] == "^[0-9]{11}$"
    assert ir.decision_rules["incomplete"] == {
        "next_action": "ASK_USER",
        "status": "NEED_CLARIFICATION",
    }
    assert "single_user_query_condition" in ir.parameter_semantics[
        "missing_parameters"
    ]
