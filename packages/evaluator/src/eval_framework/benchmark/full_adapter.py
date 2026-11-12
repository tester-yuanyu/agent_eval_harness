"""v4使用现有Inspect Docker environment及真实模型bridge。"""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path

from ..source_identity import capture_identity, source_bytes
from .inspect_docker import bind_docker_environment, source_digest
from .inspect_runtime import aggregate_usage, model_evidence
from .mini_adapter import (
    MiniAgentBenchmarkAdapter,
    opencode_bridge_filter,
    project_events,
)
from .package_sandbox import (
    RuntimeEnvironmentCache,
    package_inputs,
    prepare_package_sandbox,
)


def turn_snapshots(row, *, turn_count=None):
    observations = row["observations"]
    count = turn_count if turn_count is not None else len(observations.get("turns", []))
    snapshots = observations.get("turn_snapshots")
    if snapshots is None:
        if count > 1:
            raise ValueError("per-turn snapshots missing for multi-turn evidence")
        return [deepcopy(row["after_state"])]
    if len(snapshots) != count:
        raise ValueError("per-turn snapshot count differs from completed turns")
    return deepcopy(snapshots)


def order_events(events, row):
    from datetime import datetime

    turns = [event for event in events if event["type"] == "turn"]
    snapshots = turn_snapshots(row, turn_count=len(turns))
    for position, event in enumerate(turns):
        index = event.get("turn", position + 1) - 1
        if not 0 <= index < len(snapshots):
            raise ValueError("turn snapshot index is invalid")
        event["snapshot"] = snapshots[index]
        if len(turns) == 1 and row["observations"].get("module_output") is not None:
            event["output"] = row["observations"]["module_output"]
    return sorted(
        events,
        key=lambda e: datetime.fromisoformat(e["start_time"].replace("Z", "+00:00")),
    )


class FullBenchmarkAdapter(MiniAgentBenchmarkAdapter):
    provider_id = "mini_agent_full"

    def extra_files(self):
        files = {}
        runtime_names = (
            "full_worker.py",
            "agent_readiness.py",
            "operation_readiness.py",
            "full_readiness.py",
            "readiness.py",
        )
        for name in runtime_names:
            files["packages/evaluator/src/eval_framework/benchmark/" + name] = (
                source_bytes(Path(__file__).parent / name)
            )
        folder = self.packages["agent"] / "examples/full_tool_fixture"
        for name in ("__init__.py", "contracts.py", "environment.py", "results.py"):
            files[
                "packages/agent/src/_eval_fixture_root/examples/full_tool_fixture/"
                + name
            ] = source_bytes(folder / name)
        return files

    def fingerprint_sources(self):
        return [
            *super().fingerprint_sources(),
            self.packages["agent"] / "examples/full_tool_fixture",
        ]

    @capture_identity
    def runtime_identity(self, mode=None):
        return dict(
            provider_id=self.provider_id,
            version="builder-v4-docker-v1",
            mode=mode,
            source_sha256=source_digest(
                {**package_inputs(self.packages, self.bundle), **self.extra_files()}
            ),
            model=self.config.get("model"),
            isolation="docker",
            fixture_implementation="full_tool_fixture",
        )

    def needs_model(self, mode):
        return mode == "agent"

    def execution_kind(self, mode):
        return (
            "real_model_agent" if mode == "agent" else "deterministic_environment_check"
        )

    def sandbox_spec(self, output, *, needs_model):
        self.output = output.parent
        return prepare_package_sandbox(
            self.packages,
            self.bundle,
            output,
            extra_files=self.extra_files(),
            build_isolation=False,
        )

    async def execute(self, task, *, mode, config):
        from inspect_ai.agent import sandbox_agent_bridge
        from inspect_ai.log import transcript
        from inspect_ai.util import sandbox

        from .worker_evidence import WorkerEvidence

        env = sandbox()
        start = len(transcript().events)
        result = dict(
            status="error",
            turns=[],
            events=[],
            usage={},
            errors=[],
            evidence_complete=False,
            runtime_identity=self.runtime_identity(mode),
            isolation="docker",
            execution_backend="inspect_ai",
            execution_kind=self.execution_kind(mode),
            before_files={},
            final_files={},
        )
        evidence = WorkerEvidence(self.output, task["case_id"])
        result["worker_evidence"] = evidence.receipt
        prefix = [
            "env",
            "-i",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "DEEPEVAL_TELEMETRY_OPT_OUT=YES",
        ]
        if not hasattr(self, "_environment_cache"):
            self._environment_cache = RuntimeEnvironmentCache()

        async def probe():
            setup = await env.exec(
                prefix
                + [
                    "python",
                    "-c",
                    "import json,platform,importlib.metadata as m; "
                    "print(json.dumps({'python':platform.python_version(),"
                    "'packages':{d.metadata['Name']:d.version "
                    "for d in m.distributions()}}))",
                ]
            )
            if not setup.success:
                raise RuntimeError("v4 environment setup failed")
            return json.loads(setup.stdout)

        result["runtime_environment"] = await self._environment_cache.get(
            config["_inspect_docker_compose"],
            probe=probe,
            bind=bind_docker_environment,
        )

        @asynccontextmanager
        async def bridge():
            if task["live"]:
                async with sandbox_agent_bridge(
                    forward_generation_config=True,
                    filter=opencode_bridge_filter(config, budget=self.request_budget),
                ) as value:
                    yield f"http://localhost:{value.port}/v1"
            else:
                yield None

        pending = None
        try:
            async with bridge() as url:
                finished = await env.exec(
                    prefix
                    + [
                        "python",
                        "-m",
                        "eval_framework.benchmark.full_worker",
                        "--evidence-root",
                        evidence.remote,
                    ],
                    input=json.dumps(dict(task=task, bridge_url=url)),
                    timeout=config.get("timeout_seconds", 240),
                )
                if not finished.success:
                    raise RuntimeError("v4 worker: " + finished.stderr[-1800:])
                row = json.loads(finished.stdout)
                disk = await env.read_file(evidence.remote + "/observation.json")
                if json.loads(disk) != row or row.get("case_id") != task["case_id"]:
                    raise ValueError("worker/disk evidence mismatch")
                path = evidence.directory / "observation.json"
                path.write_text(disk)
                result["native_evidence"] = dict(
                    path=str(path.relative_to(self.output)),
                    sha256=hashlib.sha256(disk.encode()).hexdigest(),
                )
                result.update(
                    row=row,
                    status=row["status"],
                    evidence_complete=row["evidence_complete"],
                    errors=[
                        dict(code="WORKER_ERROR", message=e) for e in row["errors"]
                    ],
                )
                obs = row["observations"]
                result["adapter_output"] = dict(
                    module_output=obs.get("module_output"),
                    turns=obs.get("turns", []),
                    before_snapshot=row["before_state"],
                    turn_snapshots=turn_snapshots(row),
                    snapshot=row["after_state"],
                    trace_events=obs.get("events", []),
                    evidence_status=obs.get("evidence_manifest", {}).get("status"),
                    evidence_manifest=obs.get("evidence_manifest"),
                    execution_completed=row["status"] == "completed",
                )
                if obs.get("events"):
                    result["events"] = project_events(
                        dict(
                            trace_events=obs["events"],
                            turns=obs.get("turns", []),
                            turn_snapshots=turn_snapshots(row),
                        )
                    )
                result["turns"] = [
                    dict(
                        input=task["execution"]["user_input"],
                        output=json.dumps(
                            obs.get("module_output") or obs.get("agent_result") or obs,
                            ensure_ascii=False,
                        ),
                    )
                ]
                if len(obs.get("turns", [])) > 1:
                    inputs = [
                        task["execution"]["user_input"],
                        *task["execution"].get("user_responses", []),
                    ]
                    if len(inputs) < len(obs["turns"]):
                        raise ValueError("public inputs missing for completed turns")
                    result["turns"] = [
                        dict(
                            input=inputs[index],
                            output=json.dumps(turn, ensure_ascii=False),
                        )
                        for index, turn in enumerate(obs["turns"])
                    ]
        except BaseException as exc:
            result["status"] = "error"
            result["evidence_complete"] = False
            result["errors"].append(dict(code=type(exc).__name__, message=str(exc)))
            if not isinstance(exc, Exception):
                pending = exc
        finally:
            import anyio

            with anyio.CancelScope(shield=True):
                complete = result["evidence_complete"]
                result["evidence_complete"] = False
                try:
                    with anyio.move_on_after(15):
                        receipt = await evidence.collect(
                            env,
                            complete=complete,
                            require_business_trace="category" in task.get("plan", {}),
                        )
                        result["worker_evidence"] = receipt
                        result["evidence_complete"] = bool(
                            complete
                            and receipt["status"] == "COMPLETE"
                            and receipt["files"].get("observation.json")
                            == result.get("native_evidence", {}).get("sha256")
                        )
                except Exception as exc:
                    result["errors"].append(
                        dict(
                            code="EVIDENCE_COLLECTION_FAILED",
                            message=type(exc).__name__,
                        )
                    )
                if complete and not result["evidence_complete"]:
                    result["errors"].append(
                        dict(
                            code="WORKER_EVIDENCE_INCOMPLETE",
                            message="Attempt evidence was not fully verified",
                        )
                    )
                with anyio.move_on_after(15):
                    generations = await model_evidence(
                        transcript().events[start:], result["events"]
                    )
                    result["events"].extend(generations)
                    if "row" in result:
                        try:
                            result["events"] = order_events(
                                result["events"], result["row"]
                            )
                        except ValueError as exc:
                            result["status"] = "error"
                            result["evidence_complete"] = False
                            result["errors"].append(
                                dict(code="TURN_SNAPSHOT_MISSING", message=str(exc))
                            )
                    result["usage"] = aggregate_usage(generations)
                    if task["live"]:
                        result["evidence_complete"] = bool(
                            result["evidence_complete"]
                            and generations
                            and not any(e.get("incomplete") for e in generations)
                        )
        if pending is not None:
            pending.benchmark_observation = result
            raise pending
        return result


class FullBenchmarkFactory:
    def create_adapter(self, *, config):
        return FullBenchmarkAdapter(config)
