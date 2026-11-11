"""公开兼容 API；仅在使用时加载历史执行、报告和可选集成。"""

from importlib import import_module
from typing import Any

__all__ = [
    "DatasetBundle",
    "DatasetFilters",
    "DatasetLoadError",
    "EvalCase",
    "EvaluationRunResult",
    "EvaluationPreflightError",
    "EvaluationProvider",
    "AgentAdapter",
    "EvaluationProviderAdapter",
    "PluginCatalog",
    "ProviderRegistry",
    "SuiteDefinition",
    "CompiledSuite",
    "ContractStore",
    "ExecutionSpec",
    "OracleSpec",
    "ReportPaths",
    "RunConfig",
    "MiniAgentProvider",
    "ValidationReport",
    "load_dataset",
    "load_suite_definition",
    "compile_suite",
    "execute_compiled_suite",
    "load_run_result",
    "LoadedRunResult",
    "JudgeClient",
    "run_evaluation",
    "run_provider_evaluation",
    "validate_dataset",
    "write_report",
    "import_reviews",
    "check_comparability",
    "compare_runs",
    "evaluate_gate",
    "load_gate_policy",
    "write_gate_result",
    "write_comparison",
    "analyze_case_trace",
    "analyze_run",
    "write_run_analysis",
]

_EXPORTS = {
    "import_reviews": ("adjudication", "import_reviews"),
    "AgentAdapter": ("agent_adapter", "AgentAdapter"),
    "EvaluationProviderAdapter": ("agent_adapter", "EvaluationProviderAdapter"),
    "check_comparability": ("comparison", "check_comparability"),
    "compare_runs": ("comparison", "compare_runs"),
    "write_comparison": ("comparison", "write_comparison"),
    "execute_compiled_suite": ("compiled_execution", "execute_compiled_suite"),
    "compile_suite": ("contracts.compiler", "compile_suite"),
    "load_suite_definition": ("contracts.compiler", "load_suite_definition"),
    "CompiledSuite": ("contracts.models", "CompiledSuite"),
    "SuiteDefinition": ("contracts.models", "SuiteDefinition"),
    "ContractStore": ("contracts.store", "ContractStore"),
    "DatasetLoadError": ("dataset_loader", "DatasetLoadError"),
    "load_dataset": ("dataset_loader", "load_dataset"),
    "validate_dataset": ("dataset_validator", "validate_dataset"),
    "evaluate_gate": ("gating", "evaluate_gate"),
    "load_gate_policy": ("gating", "load_gate_policy"),
    "write_gate_result": ("gating", "write_gate_result"),
    "JudgeClient": ("judge", "JudgeClient"),
    "PluginCatalog": ("plugins.catalog", "PluginCatalog"),
    "EvaluationPreflightError": ("provider", "EvaluationPreflightError"),
    "EvaluationProvider": ("provider", "EvaluationProvider"),
    "ProviderRegistry": ("provider_registry", "ProviderRegistry"),
    "write_report": ("reporting", "write_report"),
    "LoadedRunResult": ("result_loader", "LoadedRunResult"),
    "load_run_result": ("result_loader", "load_run_result"),
    "run_evaluation": ("runner", "run_evaluation"),
    "run_provider_evaluation": ("runner", "run_provider_evaluation"),
    "DatasetBundle": ("schemas", "DatasetBundle"),
    "DatasetFilters": ("schemas", "DatasetFilters"),
    "EvalCase": ("schemas", "EvalCase"),
    "EvaluationRunResult": ("schemas", "EvaluationRunResult"),
    "ExecutionSpec": ("schemas", "ExecutionSpec"),
    "OracleSpec": ("schemas", "OracleSpec"),
    "ReportPaths": ("schemas", "ReportPaths"),
    "RunConfig": ("schemas", "RunConfig"),
    "ValidationReport": ("schemas", "ValidationReport"),
    "analyze_case_trace": ("trace_analysis", "analyze_case_trace"),
    "analyze_run": ("trace_analysis", "analyze_run"),
    "write_run_analysis": ("trace_analysis", "write_run_analysis"),
    "MiniAgentProvider": ("providers.mini_agent", "MiniAgentProvider"),
}


def __getattr__(name: str) -> Any:
    try:
        module, attribute = _EXPORTS[name]
    except KeyError:
        raise AttributeError(name) from None
    value = getattr(import_module(f".{module}", __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
