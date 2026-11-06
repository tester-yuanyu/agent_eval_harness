"""DeepEval executes the existing Provider assertions on independent evidence."""

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase

from ..assertions import run_assertions
from ..capabilities import CapabilityRegistry
from ..native_scoring import deterministic_values
from ..provider import AdapterOutput
from ..scoring import score_assertions
from .provider_tasks import (
    as_eval_case,
    provider_dataset_identity,
    public_execution,
    sha256,
)

VERSION = "provider-domain-deepeval-v1"


class ProviderAssertionMetric(BaseMetric):
    def __init__(self, case, spec, output, capabilities):
        self.case, self.spec = case, spec
        self.output, self.capabilities = output, capabilities
        self.threshold = 1.0
        self.async_mode = False
        self.strict_mode = True
        self.result = None
        self.score = None
        self.success = None
        self.reason = ""

    @property
    def __name__(self):
        return self.spec.name

    def measure(self, test_case, *args, **kwargs):
        evaluation = self.case.oracle.evaluation.model_copy(
            update={"checks": [self.spec]}
        )
        oracle = self.case.oracle.model_copy(update={"evaluation": evaluation})
        case = self.case.model_copy(update={"oracle": oracle})
        with deterministic_values():
            self.result = run_assertions(case, self.output, self.capabilities)[0]
        self.score = None if self.result.passed is None else float(self.result.passed)
        self.success = self.result.passed
        self.reason = self.result.message or json.dumps(
            {
                "expected": self.result.expected,
                "actual": self.result.actual,
                "evidence_refs": self.result.evidence_refs,
            },
            ensure_ascii=False,
        )
        return self.score

    async def a_measure(self, test_case, *args, **kwargs):
        return self.measure(test_case, *args, **kwargs)

    def is_successful(self):
        return self.success is True


class MiniAgentDomain:
    def __init__(self, dataset: Path):
        from ..providers.mini_agent.capability_adapter import (
            load_mini_agent_capability_bundle,
        )

        self.root = Path(dataset).resolve()
        self.dataset_identity = provider_dataset_identity(self.root)
        self.capabilities = CapabilityRegistry(
            load_mini_agent_capability_bundle(
                self.root / self.dataset_identity["reference_bundle"]
            )
        )

    def identity(self) -> dict:
        root = Path(__file__).parent.parent
        names = (
            "assertions.py",
            "native_scoring.py",
            "scoring.py",
            "turn_assertions.py",
            "observation_assertions.py",
            "benchmark/mini_scoring.py",
            "benchmark/provider_tasks.py",
            "benchmark/datasets/io.py",
            "benchmark/domain.py",
        )
        return {
            "version": VERSION,
            "deepeval": version("deepeval"),
            "sources": {name: sha256(root / name) for name in names},
            "reference_bundle": self.capabilities.bundle.capability_bundle_sha256,
        }

    def execution_task(self, task: dict) -> dict:
        return public_execution(task)

    def score_task(self, task: dict, observation: dict) -> dict:
        result = dict(
            verdict="INCONCLUSIVE",
            validity="VALID",
            metrics=[],
            errors=[],
            scoring_backend="deepeval",
            metrics_version=VERSION,
            score=None,
        )
        if observation.get("status") != "completed":
            result.update(verdict="INVALID", validity="INVALID")
            result["errors"] = [
                {
                    "code": "EXECUTION_INCOMPLETE",
                    "message": "Provider execution did not complete",
                }
            ]
            return result
        if not observation.get("evidence_complete"):
            result["errors"] = [
                {
                    "code": "MISSING_EVIDENCE",
                    "message": "Independent evidence incomplete",
                }
            ]
            return result
        output = AdapterOutput(**observation["adapter_output"])
        generations = [
            e
            for e in observation["events"]
            if e["type"] == "generation" and not e.get("incomplete")
        ]
        if output.evidence_status != "COMPLETE" or not generations:
            result["errors"] = [
                {
                    "code": "MISSING_EVIDENCE",
                    "message": "Provider or model evidence incomplete",
                }
            ]
            return result
        case = as_eval_case(task)
        test_case = LLMTestCase(
            input=case.execution.user_input,
            actual_output=json.dumps(
                output.module_output or output.turns, ensure_ascii=False
            ),
        )
        assertions = []
        for spec in case.oracle.evaluation.checks:
            metric = ProviderAssertionMetric(case, spec, output, self.capabilities)
            metric.measure(test_case)
            assertions.append(metric.result)
            scope, event_id = "task", None
            if case.test_scope == "module":
                scope, event_id = "generation", generations[-1]["id"]
            elif spec.name in {
                "tool_called",
                "tool_args_match",
                "tool_result_consistent",
            }:
                tool = next(
                    (e for e in observation["events"] if e["type"] == "tool"), None
                )
                if tool:
                    scope, event_id = "tool", tool["id"]
            record = {
                "name": spec.name,
                "score": metric.score,
                "success": metric.success,
                "threshold": 1.0,
                "reason": metric.reason,
                "backend": "deepeval",
                "implementation": "ProviderAssertionMetric",
                "formal": True,
                "version": VERSION,
                "scope": scope,
                "status": "UNSCORED" if metric.score is None else "SCORED",
                "weight": spec.weight,
                "critical": spec.critical,
                "native_scores": metric.result.native_scores,
                "evidence_refs": metric.result.evidence_refs,
            }
            if event_id:
                record["event_id"] = event_id
            result["metrics"].append(record)
        result["score"], result["verdict"] = score_assertions(assertions, 100)
        return result
