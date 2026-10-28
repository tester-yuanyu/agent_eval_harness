from minimal_agent.versions import (
    MODEL_CLIENT_PROTOCOL_VERSION,
    TOOL_REGISTRY_CONTRACT_VERSION,
    agent_package_version,
)


def test_runtime_versions_are_owned_outside_capability_protocol() -> None:
    assert MODEL_CLIENT_PROTOCOL_VERSION == "environment-configured-responses-api-v1"
    assert TOOL_REGISTRY_CONTRACT_VERSION == "tool-registry-v2"
    assert agent_package_version() == "0.1.0"
