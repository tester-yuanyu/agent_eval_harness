"""Builder 全量定义的正式 benchmark Domain；只在主进程读取 Oracle。"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase
from eval_contracts.agent_readiness import (
    AgentPlan,
    agent_checks,
    binding_for,
    node_evidence,
    reference_context,
)
from eval_contracts.full_readiness import FullCase, FullRequest, ToolEvidence
from eval_contracts.operation_readiness import _value, operation_checks

from .domains.presentation import ProviderPresentation

CONTRACT = "builder-full-benchmark-v1"
VERSION = "builder-full-deepeval-v1"


def load_request(root: Path) -> FullRequest:
    root = Path(root).resolve()
    r = FullRequest.model_validate_json(
        (root.parent / "readiness/dataset.json").read_bytes()
    )
    raw = (root / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    if (
        hashlib.sha256(raw).hexdigest() != r.source_manifest_sha256
        or manifest["files_sha256"] != r.source_files
        or manifest["bundle_sha256"] != r.bundle_sha256
        or manifest["definition_counts"] != r.definition_counts
    ):
        raise ValueError("v4 request/source identity mismatch")
    documents, schemas, source_cases = [], {}, {}
    for name, expected in r.source_files.items():
        path = (root / name).resolve()
        if (
            not path.is_relative_to(root)
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError("v4 source file mismatch: " + name)
        if name.startswith("source_delivery/bundle/") and name.endswith(".json"):
            doc = json.loads(path.read_bytes())
            if (
                isinstance(doc, dict)
                and "snapshot_id" in doc
                and "snapshot_type" in doc
            ):
                documents.append(doc)
            if path.parent.name == "tools":
                schemas["tool." + path.stem] = doc["function_schema"]
            elif path.parent.name == "intents":
                schemas["intent." + path.stem] = doc["parameters_schema"]
    for ds in manifest["datasets"]:
        if ds["definition_kind"] == "behavior_case":
            for line in (root / ds["path"]).read_bytes().splitlines():
                if line.strip():
                    case = json.loads(line)
                    if case["case_id"] in source_cases:
                        raise ValueError("duplicate source case")
                    source_cases[case["case_id"]] = (ds["path"], case)
    if (
        source_cases != {c.case_id: (c.source_path, c.payload) for c in r.cases}
        or sorted(documents, key=lambda d: d["snapshot_id"])
        != sorted(r.capability_documents, key=lambda d: d["snapshot_id"])
        or schemas != r.target_schemas
    ):
        raise ValueError("v4 request contents differ from bound source")
    return r


def dataset_identity(root: Path) -> dict:
    r = load_request(root)
    return dict(
        dataset_id="mini-agent-builder-v4",
        version="2026-11-11",
        task_contract=CONTRACT,
        task_count=len(r.cases),
        request_sha256=r.sha256(),
        source_manifest_sha256=r.source_manifest_sha256,
        reference_bundle_sha256=r.bundle_sha256,
        definition_counts=r.definition_counts,
    )


def tasks_for(request: FullRequest) -> list[dict]:
    tasks = []
    for c in request.cases:
        plan = binding_for(c, request)
        if plan is None:
            raise ValueError("unbound v4 case: " + c.case_id)
        live = isinstance(plan, AgentPlan) and plan.category != "module_event"
        scope = plan.scope if isinstance(plan, AgentPlan) else "module"
        category = (
            plan.category
            if isinstance(plan, AgentPlan)
            else (
                "schema_validation"
                if plan.operation == "validate_arguments"
                else "tool_behavior"
            )
        )
        tasks.append(
            dict(
                id=c.case_id,
                prompt=getattr(plan, "user_input", c.case_id),
                followups=[],
                fixtures={},
                split="dev",
                category=category,
                family=category,
                evaluation_level={
                    "module": "module",
                    "link": "chain",
                    "end_to_end": "e2e",
                }[scope],
                execution_mode="agent" if live else "module",
                case=c.model_dump(mode="json"),
                plan=plan.model_dump(mode="json"),
                live=live,
                oracle=deepcopy(c.payload.get("oracle", {})),
                target=c.payload.get("target", c.payload.get("target_id", "")),
                labels=c.payload.get("labels", []),
            )
        )
    return tasks


def load_tasks(root: Path) -> list[dict]:
    return tasks_for(load_request(root))


def public_task(task: dict, request: FullRequest) -> dict:
    # Authored input recipes and public contracts only. Never include case/Oracle.
    return dict(
        case_id=task["id"],
        execution={"user_input": task["prompt"]},
        plan=deepcopy(task["plan"]),
        live=task["live"],
        context=reference_context(request).model_dump(mode="json"),
    )


class RuleMetric(BaseMetric):
    threshold = 1.0
    async_mode = False
    strict_mode = True

    def __init__(self, name, passed):
        self.name, self.passed = name, passed

    @property
    def __name__(self):
        return self.name

    def measure(self, test_case, *args, **kwargs):
        self.score = float(self.passed)
        self.success = self.passed
        self.reason = "独立证据满足断言" if self.passed else "独立证据不满足断言"
        return self.score

    async def a_measure(self, test_case, *args, **kwargs):
        return self.measure(test_case)

    def is_successful(self):
        return self.success


def live_checks(case, plan, row, request):
    from ..assertions import run_assertions
    from ..native_scoring import deterministic_values
    from ..provider import AdapterOutput
    from ..schemas import EvalCase
    from .full_worker import capability_registry

    obs = row.observations
    events = obs.get("events", [])
    manifest = obs.get("evidence_manifest", {})
    checks = dict(
        execution_complete=row.evidence_complete
        and row.status == "completed"
        and not row.errors,
        plan_bound=row.execution == plan.model_dump(mode="json"),
        reference_bound=obs.get("reference_bundle_sha256") == request.bundle_sha256,
        trace_complete=bool(events)
        and manifest.get("status") == "COMPLETE"
        and all(e.get("validation_status") == "VALID" for e in events),
        trace_sequence=[e.get("sequence") for e in events]
        == list(range(1, len(events) + 1)),
        real_model_input=bool(obs.get("model_interactions"))
        and obs["model_interactions"][0]["input"] == plan.user_input,
    )
    if "execution" in case.payload:
        output = AdapterOutput(
            obs.get("module_output"),
            obs.get("turns", []),
            row.before_state,
            [row.after_state],
            row.after_state,
            trace_events=events,
            evidence_status=manifest.get("status"),
            evidence_manifest=manifest,
        )
        with deterministic_values():
            results = run_assertions(
                EvalCase.model_validate(case.payload),
                output,
                capability_registry(reference_context(request)),
            )
        checks.update({r.name: r.passed is True for r in results})
    else:
        context = {
            "trace": {"event_types": [e["event_type"] for e in events]},
            "agent_result": obs.get("agent_result") or {},
            "tool_trace": {"names": [c["name"] for c in row.tool_calls]},
        }
        assertions = case.payload.get("oracle", {}).get("checks", [])
        checks["assertions_present"] = bool(assertions)
        for i, c in enumerate(assertions):
            try:
                actual = _value(context, c["actual"])
                passed = (
                    (type(actual) is type(c["expected"]) and actual == c["expected"])
                    if c["op"] == "equals"
                    else c["op"] == "subset"
                    and isinstance(actual, list)
                    and all(v in actual for v in c["expected"])
                )
            except (KeyError, TypeError, ValueError, IndexError):
                passed = False
            checks[f"oracle_{i}"] = passed
    if plan.chain_id:
        nodes = node_evidence(plan, events, request)
        checks["ordered_chain_nodes"] = bool(nodes) and nodes == obs.get("chain_nodes")
    return checks


class FullBenchmarkDomain:
    presentation = ProviderPresentation(task_name="mini_agent_builder_v4")

    def __init__(self, root: Path):
        self.request = load_request(root)

    def identity(self):
        from eval_contracts.full_readiness import assertion_identity

        return dict(
            version=VERSION,
            source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            assertions_sha256=assertion_identity(),
            rule_sources={
                name: hashlib.sha256(
                    (Path(__file__).parent / name).read_bytes()
                ).hexdigest()
                for name in (
                    "../assertions.py",
                    "../native_scoring.py",
                    "../turn_assertions.py",
                    "../observation_assertions.py",
                    "../scoring.py",
                    "full_worker.py",
                )
            },
        )

    def execution_task(self, task):
        return public_task(task, self.request)

    def score_task(self, task, observation):
        result = dict(
            verdict="INVALID",
            validity="INVALID",
            score=None,
            metrics=[],
            errors=[],
            scoring_backend="deepeval",
            metrics_version=VERSION,
        )
        if observation.get("status") != "completed" or not observation.get(
            "evidence_complete"
        ):
            result["errors"] = [
                {
                    "code": "EXECUTION_INCOMPLETE",
                    "message": "environment execution/evidence incomplete",
                }
            ]
            return result
        case = FullCase.model_validate(task["case"])
        row = ToolEvidence.model_validate(observation["row"])
        plan = binding_for(case, self.request)
        checks = (
            live_checks(case, plan, row, self.request)
            if task["live"]
            else (
                agent_checks(case, plan, row, self.request)
                if isinstance(plan, AgentPlan)
                else operation_checks(case, plan, row)
            )
        )
        for name, passed in checks.items():
            metric = RuleMetric(name, passed)
            metric.measure(
                LLMTestCase(
                    input=task["prompt"],
                    actual_output=json.dumps(row.observations, ensure_ascii=False),
                )
            )
            result["metrics"].append(
                dict(
                    name=name,
                    score=metric.score,
                    success=metric.success,
                    threshold=1.0,
                    reason=metric.reason,
                    backend="deepeval",
                    implementation="RuleMetric",
                    formal=True,
                    version=VERSION,
                    scope="task",
                    status="SCORED",
                    weight=1,
                    critical=True,
                )
            )
        passed = bool(checks) and all(checks.values())
        result.update(
            verdict="PASS" if passed else "FAIL",
            validity="VALID",
            score=100.0 if passed else 0.0,
        )
        return result
