"""独立 P0 reference worker；使用真实 Harness，mockllm 仅记录确定性动作。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import platform
import subprocess
from pathlib import Path

from eval_contracts.benchmark import TaskInput
from eval_contracts.readiness import (
    CaseEvidence,
    ReadinessDataset,
    ReadinessEvidence,
    RunnerIdentity,
    assertion_identity,
    digest_bytes,
)


def identity() -> RunnerIdentity:
    digest = hashlib.sha256()
    # Bind installed code, not Git HEAD: working-tree changes count too.
    for name in ("eval_framework", "eval_contracts", "agent_trace_sdk"):
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            raise ValueError(f"missing runtime package: {name}")
        root = Path(spec.origin).parent
        for path in sorted(root.rglob("*.py")):
            digest.update(f"{name}/{path.relative_to(root).as_posix()}\0".encode())
            digest.update(bytes.fromhex(digest_bytes(path.read_bytes())))
    runtime = {
        name: importlib.metadata.version(name)
        for name in (
            "inspect-ai",
            "pydantic",
            "jsonschema",
            "anyio",
        )
    }
    runtime.update(python=platform.python_version(), platform=platform.system())
    runtime["assertions_sha256"] = assertion_identity()
    runtime["sandbox_python"] = subprocess.check_output(
        ["python3", "-I", "-c", "import sys; print(sys.version)"],
        text=True,
        timeout=10,
    ).strip()
    return RunnerIdentity(implementation_sha256=digest.hexdigest(), runtime=runtime)


class ReadFileReference:
    """Only the path enters this actor; final text comes from the tool message."""

    def __init__(self, path: str):
        self.path = path
        self.called = False

    async def step(self, state):
        from inspect_ai.model import (
            ChatMessageAssistant,
            ChatMessageTool,
            ModelOutput,
            get_model,
        )
        from inspect_ai.tool import ToolCall

        from ..harness.adapters.agent.base import AgentAction

        if not self.called:
            message = ChatMessageAssistant(
                content="",
                tool_calls=[
                    ToolCall(
                        id="reference-read",
                        function="read_file",
                        arguments={"path": self.path},
                    )
                ],
            )
            stop = "tool_calls"
            self.called = True
        else:
            result = next(
                m for m in reversed(state.messages) if isinstance(m, ChatMessageTool)
            )
            message = ChatMessageAssistant(content=result.text)
            stop = "stop"
        output = ModelOutput.from_content("mockllm/model", message.text)
        output.choices[0].message = message
        output.choices[0].stop_reason = stop
        # Public Inspect generation creates native ModelEvents; this provider
        # is an in-process stub and never contacts a model service.
        model = get_model("mockllm/model", custom_outputs=[output])
        observed = await model.generate(input=state.messages, tools=state.tools)
        return AgentAction(observed.message, observed.stop_reason, observed)

    async def close(self):
        pass


def run(dataset: Path, log_dir: Path) -> ReadinessEvidence:
    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.solver import Generate, Solver, TaskState, solver

    from ..harness.adapters.inspect_solver import execute_native_task

    raw = dataset.read_bytes()
    parsed = ReadinessDataset.model_validate_json(raw)
    binding = identity()
    # Public task and private reference recipe are extracted explicitly.
    tasks = {
        case.case_id: TaskInput(
            task_id=case.case_id,
            prompt=case.prompt,
            initial_state={"files": case.fixtures},
            tools=["read_file"],
            max_steps=3,
        )
        for case in parsed.cases
    }
    paths = {case.case_id: case.reference_path for case in parsed.cases}

    @solver
    def reference_solver() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            await execute_native_task(
                tasks[str(state.sample_id)],
                agent=ReadFileReference(paths[str(state.sample_id)]),
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
                Sample(id=key, input=task.prompt, target="")
                for key, task in tasks.items()
            ],
            solver=reference_solver(),
            sandbox="local",
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
        events = row.get("events", [])
        tools = [event for event in events if event.get("type") == "tool"]
        errors.extend(str(event["error"]) for event in tools if event.get("error"))
        turns = row.get("turns", [])
        results.append(
            CaseEvidence(
                case_id=str(sample.id),
                status=row.get("status", "error"),
                evidence_complete=row.get("evidence_complete", False),
                before_files=row.get("before_files") or {},
                final_files=row.get("final_files") or {},
                final_output=turns[-1]["output"] if turns else "",
                executed_tools=[
                    event["name"] for event in tools if event.get("execution_started")
                ],
                errors=errors,
                observed_path=tools[0].get("input", {}).get("path")
                if len(tools) == 1
                else None,
            )
        )
    if identity() != binding:
        raise ValueError("runner implementation changed during verification")
    return ReadinessEvidence(
        dataset_sha256=digest_bytes(raw), runner=binding, results=results
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", action="store_true")
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.identity:
        result = identity()
    else:
        if args.dataset is None or args.log_dir is None:
            parser.error("--dataset and --log-dir required")
        result = run(args.dataset, args.log_dir)
    with args.output.open("x") as handle:
        handle.write(result.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
