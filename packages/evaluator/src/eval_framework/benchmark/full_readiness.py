"""现有 Builder 产物的可选 MiniAgent reference worker（离线）。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

from eval_contracts.benchmark import TaskInput
from eval_contracts.full_readiness import (
    FullEvidence,
    FullRequest,
    ToolEvidence,
    assertion_identity,
    execution_for,
)
from eval_contracts.readiness import RunnerIdentity

from .readiness import ReadFileReference
from .readiness import identity as base_identity


def identity(
    mini_root: Path, *, operations: bool = True, agent: bool = True
) -> RunnerIdentity:
    base = base_identity()
    digest = hashlib.sha256(base.implementation_sha256.encode())
    spec = importlib.util.find_spec("minimal_agent")
    if spec is None or spec.origin is None:
        raise ValueError("MiniAgent optional dependency is required for this runner")
    for label, root in [
        ("minimal_agent", Path(spec.origin).parent),
        ("full_tool_fixture", mini_root / "examples/full_tool_fixture"),
    ]:
        paths = sorted(root.rglob("*.py"))
        if not paths:
            raise ValueError(f"missing reference implementation: {root}")
        for path in paths:
            digest.update(f"{label}/{path.relative_to(root).as_posix()}\0".encode())
            digest.update(path.read_bytes())
    return RunnerIdentity(
        runner_id="inspect-mini-agent-v3"
        if operations and agent
        else (
            "inspect-mini-operations-v2" if operations else "native-mini-query-user-v1"
        ),
        implementation_sha256=digest.hexdigest(),
        runtime={**base.runtime, "full_assertions_sha256": assertion_identity()},
    )


def fixture_class(mini_root: Path):
    # Only an explicit trusted installation path is loaded, never dataset code.
    folder = mini_root.resolve() / "examples/full_tool_fixture"
    name = "_agent_eval_reference_fixture"
    for key in list(sys.modules):
        if key == name or key.startswith(name + "."):
            del sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        name, folder / "__init__.py", submodule_search_locations=[str(folder)]
    )
    if spec is None or spec.loader is None:
        raise ValueError("reference fixture not found")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.FixtureEnvironment


def function_schema(schema):
    result = deepcopy(schema.get("function", schema))
    # These are wrapper metadata / a JSON Schema annotation, not constraints.
    result.pop("type", None)
    result.pop("strict", None)

    def remove_titles(node):
        node.pop("title", None)
        # Inspect lacks exclusiveMinimum. For integer bounds this is equivalent,
        # including at zero; never apply this rewrite to numbers or mixed types.
        if node.get("type") == "integer" and type(node.get("exclusiveMinimum")) is int:
            bound = node.pop("exclusiveMinimum") + 1
            node["minimum"] = max(bound, node.get("minimum", bound))
        for child in node.get("properties", {}).values():
            remove_titles(child)
        for key in ("anyOf", "oneOf", "allOf"):
            for child in node.get(key, []):
                remove_titles(child)
        if isinstance(node.get("items"), dict):
            remove_titles(node["items"])

    remove_titles(result["parameters"])
    return result


class QueryEnvironment:
    def __init__(self, factory, expected_schema):
        self.factory = factory
        self.expected_schema = expected_schema

    async def reset(self, initial_state):
        self.env = self.factory()
        self.env.users = {
            row["user_id"]: deepcopy(row) for row in initial_state["users"]
        }
        self.env.gifts, self.env.pools, self.env.resources = {}, {}, []
        self.registry = self.env.registry()
        self.schema = function_schema(self.registry.get("query_user_info").schema())
        if self.schema != function_schema(self.expected_schema):
            raise ValueError("runtime tool schema differs from reference bundle")

    def tool_schemas(self):
        return [self.schema]

    async def step(self, name, arguments):
        result = self.registry.invoke(
            name, arguments, allowed_tools=frozenset({"query_user_info"})
        )
        return result.model_dump_json()

    async def snapshot(self):
        return {"users": deepcopy(list(self.env.users.values()))}

    async def teardown(self):
        pass


class ToolReference(ReadFileReference):
    def __init__(self, arguments):
        self.arguments = arguments
        self.called = False

    async def step(self, state):
        if self.called:
            return await super().step(state)
        from inspect_ai.model import ChatMessageAssistant, ModelOutput, get_model
        from inspect_ai.tool import ToolCall

        from ..harness.adapters.agent.base import AgentAction

        message = ChatMessageAssistant(
            content="",
            tool_calls=[
                ToolCall(
                    id="reference-query",
                    function="query_user_info",
                    arguments=self.arguments,
                )
            ],
        )
        output = ModelOutput.from_content("mockllm/model", "")
        output.choices[0].message = message
        output.choices[0].stop_reason = "tool_calls"
        self.called = True
        observed = await get_model("mockllm/model", custom_outputs=[output]).generate(
            input=state.messages, tools=state.tools
        )
        return AgentAction(observed.message, observed.stop_reason, observed)


def run(dataset: Path, log_dir: Path, mini_root: Path) -> FullEvidence:
    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.solver import solver

    from ..harness.adapters.inspect_solver import execute_native_task

    request = FullRequest.model_validate_json(dataset.read_bytes())
    operations = request.schema_version != "builder-full-readiness-v1"
    binding = identity(
        mini_root,
        operations=operations,
        agent=request.schema_version == "builder-full-readiness-v3",
    )
    if operations:
        from .operation_readiness import run_operations

        return run_operations(request, log_dir, mini_root, binding)
    factory = fixture_class(mini_root)
    # Only explicit arguments/fixtures enter execution; oracle stays in request.
    recipes = {
        case.case_id: recipe
        for case in request.cases
        if (recipe := execution_for(case)) is not None
    }
    if not recipes:
        return FullEvidence(dataset_sha256=request.sha256(), runner=binding, results=[])

    @solver
    def reference_solver():
        async def solve(state, generate):
            key = str(state.sample_id)
            recipe = recipes[key]
            await execute_native_task(
                TaskInput(
                    task_id=key,
                    prompt="执行给定的用户查询。",
                    initial_state={"users": recipe.users},
                    tools=["query_user_info"],
                    max_steps=3,
                ),
                agent=ToolReference(recipe.arguments),
                environment=QueryEnvironment(factory, request.tool_schema),
                task_state=state,
                execution_kind="deterministic_reference_not_agent",
                timeout_seconds=30,
                max_tool_calls=1,
            )
            return state

        return solve

    log = inspect_eval(
        Task(
            dataset=[
                Sample(id=key, input="执行给定的用户查询。", target="")
                for key in recipes
            ],
            solver=reference_solver(),
        ),
        model="mockllm/model",
        log_dir=str(log_dir),
        display="none",
        notification=False,
        ctl_server=False,
        max_samples=1,
        fail_on_error=False,
    )[0]
    results = []
    for sample in log.samples or []:
        row = (sample.metadata or {}).get("harness_observation", {})
        errors = [str(error) for error in row.get("errors", [])]
        if sample.error:
            errors.append(str(sample.error))
        if log.status != "success":
            errors.append("Inspect run did not finish successfully")
        calls = [
            event for event in row.get("events", []) if event.get("type") == "tool"
        ]
        errors.extend(str(event["error"]) for event in calls if event.get("error"))
        try:
            result = json.loads(calls[0]["output"]) if len(calls) == 1 else {}
        except (ValueError, TypeError, KeyError):
            result = {}
            errors.append("missing structured tool result")
        results.append(
            ToolEvidence(
                case_id=str(sample.id),
                status=row.get("status", "error"),
                evidence_complete=row.get("evidence_complete", False),
                before_state=row.get("before_files") or {},
                after_state=row.get("final_files") or {},
                tool_calls=[
                    {"name": event["name"], "arguments": event.get("input", {})}
                    for event in calls
                    if event.get("execution_started")
                ],
                tool_result=result,
                errors=errors,
            )
        )
    if identity(mini_root, operations=False) != binding:
        raise ValueError("runner implementation changed during verification")
    return FullEvidence(
        dataset_sha256=request.sha256(), runner=binding, results=results
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", action="store_true")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--mini-agent-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(args.output)
    if not args.identity and (args.dataset is None or args.log_dir is None):
        parser.error("--dataset and --log-dir required")
    result = (
        identity(args.mini_agent_root)
        if args.identity
        else run(args.dataset, args.log_dir, args.mini_agent_root)
    )
    with args.output.open("x") as handle:
        handle.write(result.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
