from __future__ import annotations

import ast
import json
from pathlib import Path

import eval_framework

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "src" / "eval_framework"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_contract_and_catalog_kernel_do_not_import_concrete_integrations() -> None:
    paths = [
        *sorted((PACKAGE / "contracts").glob("*.py")),
        PACKAGE / "plugins" / "catalog.py",
        PACKAGE / "compiled_execution.py",
    ]

    for path in paths:
        imports = _imports(path)
        assert not any("providers.mini_agent" in item for item in imports), path
        assert not any("judges.deepseek" in item for item in imports), path


def test_compiler_contains_no_builtin_plugin_ids() -> None:
    source = (PACKAGE / "contracts" / "compiler.py").read_text(encoding="utf-8")

    for plugin_id in (
        "legacy_jsonl_eval_case_v1",
        "fixture_json_document_v1",
        "mini_agent_provider_v1",
    ):
        assert plugin_id not in source


def test_runner_does_not_import_dataset_loader_plugins() -> None:
    imports = _imports(PACKAGE / "runner.py")

    assert not any("plugins.builtin" in item for item in imports)
    assert not any("dataset_loaders" in item for item in imports)


def test_benchmark_runner_does_not_import_concrete_agents() -> None:
    imports = _imports(PACKAGE / "benchmark" / "runner.py")
    for concrete in (
        "nanobot_runtime", "module_runtime", "decision_runtime", "minimal_agent",
    ):
        assert not any(concrete in item for item in imports)


def test_suite_schema_has_no_executable_property_names() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "suite_definition.schema.json").read_text()
    )
    property_names: set[str] = set()

    def visit(value) -> None:
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict):
                property_names.update(properties)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)

    assert property_names.isdisjoint({"module", "command", "entry_point"})


def test_contract_plugin_public_api_is_exported() -> None:
    for name in (
        "PluginCatalog",
        "SuiteDefinition",
        "CompiledSuite",
        "ContractStore",
        "load_suite_definition",
        "compile_suite",
        "execute_compiled_suite",
    ):
        assert getattr(eval_framework, name) is not None
