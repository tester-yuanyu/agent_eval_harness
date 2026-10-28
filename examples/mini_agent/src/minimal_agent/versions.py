"""Version identifiers owned by the MiniAgent runtime."""

from importlib.metadata import version

MODEL_CLIENT_PROTOCOL_VERSION = "environment-configured-responses-api-v1"
TOOL_REGISTRY_CONTRACT_VERSION = "tool-registry-v2"


def agent_package_version() -> str:
    """Return the installed package version."""

    return version("minimal-agent")
