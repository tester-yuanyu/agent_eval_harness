"""Public Agent evaluation API with deterministic and phase-two analysis."""

from importlib import import_module
from typing import Any

from .adjudication import import_reviews
from .agent_adapter import AgentAdapter, EvaluationProviderAdapter
from .comparison import check_comparability, compare_runs, write_comparison
from .compiled_execution import execute_compiled_suite
from .contracts.compiler import compile_suite, load_suite_definition
from .contracts.models import CompiledSuite, SuiteDefinition
from .contracts.store import ContractStore
from .dataset_loader import DatasetLoadError, load_dataset
from .dataset_validator import validate_dataset
from .gating import evaluate_gate, load_gate_policy, write_gate_result
from .judge import JudgeClient
from .plugins.catalog import PluginCatalog
from .provider import EvaluationPreflightError, EvaluationProvider
from .provider_registry import ProviderRegistry
from .reporting import write_report
from .result_loader import LoadedRunResult, load_run_result
from .runner import run_evaluation, run_provider_evaluation
from .schemas import (
    DatasetBundle,
    DatasetFilters,
    EvalCase,
    EvaluationRunResult,
    ExecutionSpec,
    OracleSpec,
    ReportPaths,
    RunConfig,
    ValidationReport,
)
from .trace_analysis import analyze_case_trace, analyze_run, write_run_analysis

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


def __getattr__(name: str) -> Any:
    """Load provider integrations only when callers request them."""

    if name != "MiniAgentProvider":
        raise AttributeError(name)
    value = import_module(
        "eval_framework.providers.mini_agent"
    ).MiniAgentProvider
    globals()[name] = value
    return value
