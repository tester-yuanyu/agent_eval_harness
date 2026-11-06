import copy

import pytest

from eval_framework.benchmark.runner import run_benchmark
from eval_framework.provider_registry import ProviderRegistry

from .test_agent_adapters import AdapterFactory, OfflineAdapter


def test_runner_uses_injected_domain_and_keeps_private_truth_out(tmp_path):
    class Domain:
        def identity(self):
            return {"version": "fixture-v1", "source_sha256": "fixture-code"}

        def execution_task(self, task):
            return {key: copy.deepcopy(task[key]) for key in ("prompt", "fixtures")}

        def score_task(self, task, observation):
            assert task["oracle"] == {"private": 42}
            return {
                "verdict": "INCONCLUSIVE",
                "validity": "VALID",
                "metrics": [],
                "scoring_backend": "deepeval",
                "errors": ["fixture"],
            }

    adapter = OfflineAdapter()
    registry = ProviderRegistry()
    registry.register(adapter.provider_id, AdapterFactory(adapter))
    task = dict(
        id="case",
        prompt="public",
        fixtures={},
        category="test",
        split="dev",
        family="test",
        oracle={"private": 42},
    )
    result = run_benchmark(
        [task],
        dataset={"id": "fixture"},
        config={"provider": adapter.provider_id},
        output=tmp_path,
        provider_registry=registry,
        domain=Domain(),
    )
    assert adapter.received == [{"prompt": "public", "fixtures": {}}]
    assert result["trials"][0]["assessment"]["errors"] == ["fixture"]
    assert result["identity"]["scoring_version"] == "fixture-v1"


def test_pure_comparisons_preserve_strict_types_without_inspect(monkeypatch):
    from eval_framework import native_scoring

    def reject(*args):
        raise AssertionError("Inspect scorer must not run in DeepEval domain")

    monkeypatch.setattr(native_scoring, "_measure", reject)
    with native_scoring.deterministic_values():
        assert native_scoring.exact_value({"x": 1}, {"x": 1})
        assert not native_scoring.exact_value(True, 1)
        assert not native_scoring.exact_value(" a ", "a")
        assert native_scoring.subset_value({"x": 1, "y": 2}, {"x": 1})
        assert native_scoring.contains_text("hello world", "world")
    with pytest.raises(AssertionError, match="Inspect scorer"):
        native_scoring.exact_value(1, 1)
