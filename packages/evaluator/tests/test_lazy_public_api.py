"""核心导入不得激活历史执行、评分或可选 Agent 集成。"""

import os
import subprocess
import sys


def test_core_import_and_external_registry_do_not_load_legacy_runtime():
    code = """
import importlib.abc
import sys
class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"eval_framework.runner", "eval_framework.reporting",
                        "eval_framework.compiled_execution", "minimal_agent"}:
            raise AssertionError("unexpected import: " + fullname)
sys.meta_path.insert(0, BlockLegacy())
import eval_framework
from eval_framework import ProviderRegistry, EvaluationProvider, ExecutionSpec
from eval_framework.providers.external import ExternalProviderFactory
registry = ProviderRegistry()
assert registry is not None
assert ExternalProviderFactory is not None
assert "run_evaluation" in dir(eval_framework)
assert "write_report" in eval_framework.__all__
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_historical_exports_preserve_object_identity_and_unknown_attributes():
    import eval_framework
    import pytest
    from eval_framework.reporting import write_report
    from eval_framework.runner import run_evaluation

    assert eval_framework.write_report is write_report
    assert eval_framework.run_evaluation is run_evaluation
    assert eval_framework.run_evaluation is run_evaluation
    with pytest.raises(AttributeError):
        _ = eval_framework.not_a_public_api
