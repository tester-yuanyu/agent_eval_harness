"""Core integrations work when the reference Agent is not installed."""

import subprocess
import sys


def test_default_catalog_does_not_import_installed_agent():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from eval_framework.composition import default_plugin_catalog, default_provider_registry
default_plugin_catalog()
default_provider_registry()
assert "minimal_agent" not in sys.modules
""",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_core_catalog_and_external_provider_without_minimal_agent():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib.abc
import sys

class MissingAgent(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "minimal_agent" or fullname.startswith("minimal_agent."):
            raise ModuleNotFoundError("minimal_agent is not installed", name=fullname)

sys.meta_path.insert(0, MissingAgent())
import eval_framework
from eval_framework.composition import default_plugin_catalog, default_provider_registry
from eval_framework.plugins.models import PluginReference
from eval_framework.capabilities import CapabilityBundle, CapabilityRegistry
from eval_framework.providers.external import ExternalProvider, RuntimeBinding
from eval_framework.schemas import ExecutionProfile, ExecutionSpec

catalog = default_plugin_catalog()
default_provider_registry()
catalog.resolve(
    PluginReference(plugin_id="external_provider_v1", version="1.0.0", config={
        "binding": {"version": "1.0", "agent_id": "fixture", "adapter": "static"}
    }), expected_kind="provider", contract_version="1.0", field_path="provider"
)
provider = ExternalProvider(
    RuntimeBinding(version="1.0", agent_id="fixture", adapter="static"),
    CapabilityRegistry(CapabilityBundle(
        root=".", provider_id="fixture", bundle_format_version="3.0",
        capability_bundle_sha256="a" * 64, documents=(),
    )), execution_profiles={"none": ExecutionProfile(allowed_tools=[])}
)
execution = ExecutionSpec(
    user_input="inspect fixture", tool_profile="none", adapter_input={
    "input": {"operation": "inspect_snapshot", "declared_value": {"answer": 42}},
    "preconditions": [],
})
runtime = provider.create_runtime(execution, "fixture-session", "module")
try:
    assert provider.run_module(runtime, execution).observations == {
        "declared_value": {"answer": 42}
    }
finally:
    provider.cleanup(runtime)
assert "minimal_agent" not in sys.modules
""",
        ],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
