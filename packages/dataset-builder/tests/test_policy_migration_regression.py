from __future__ import annotations

from dataset_builder.pipeline import prepare_generation
from dataset_builder.suite_definition import load_suite


def test_all_suites_use_six_external_policies_without_embedded_fallback():
    for suite_id in (
        "mini_agent_intent_v1",
        "mini_agent_query_user_intent_v1",
        "mini_agent_query_gift_intent_v1",
    ):
        suite = load_suite(suite_id)
        assert suite.policy_set is not None
        assert {item["kind"] for item in suite.policy_bindings} == {
            "source",
            "coverage",
            "generation",
            "validation",
            "review",
            "freeze",
        }


def test_generation_request_hash_binds_policies_and_capability_adapter(tmp_path):
    suite = load_suite("mini_agent_query_user_intent_v1")
    request = prepare_generation(suite, tmp_path)

    assert all(len(item["sha256"]) == 64 for item in request.policy_bindings)
    assert all(
        len(item["schema_sha256"]) == 64 for item in request.policy_bindings
    )
    adapter = next(
        item
        for item in request.plugin_bindings
        if item["role"] == "capability_adapter"
    )
    assert adapter["protocol"] == "capability-snapshot"
    assert len(adapter["implementation_sha256"]) == 64
