"""Inspectable execution, immutable per-trial journals and independent scoring."""

from __future__ import annotations

import json
import os
import time
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from capability_snapshot_kit.hashing import sha256_json as digest

from ..agent_adapter import adapter_identity
from ..provider_registry import ProviderRegistry
from .domain import BenchmarkDomain
from .identity import code_identity as code_identity
from .identity import scoring_identity as scoring_identity
from .run_context import InspectRuntime, RunContext

HARNESS_VERSION = "file-harness-inspect-v4"


class RuntimeIdentityChanged(RuntimeError):
    pass


def require_runtime_identity(expected: dict, actual: dict) -> None:
    if actual != expected:
        raise RuntimeIdentityChanged(
            "runtime source/configuration changed during the experiment"
        )


def now() -> str:
    return datetime.now(UTC).isoformat()


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def validate_config(config: dict) -> None:
    for key in config:
        if any(
            word in key.lower()
            for word in (
                "api_key",
                "secret",
                "password",
                "access_token",
                "authorization",
            )
        ) and not key.endswith("_env"):
            raise ValueError(
                "secret values are forbidden in benchmark configuration; "
                "use an environment-variable name"
            )
    if not 1 <= int(config.get("max_steps", 12)) <= 30:
        raise ValueError("max_steps must be between 1 and 30")
    if not 1 <= float(config.get("timeout_seconds", 180)) <= 600:
        raise ValueError("timeout_seconds must be between 1 and 600")


def summarize(records: list[dict], case_ids: list[str], repeats: int) -> dict:
    """保持历史汇总 API；统计实现归 Aggregator 所有。"""
    from ..aggregator import summarize as aggregate

    return aggregate(records, case_ids, repeats)


def compare_runs(baseline: dict, candidate: dict) -> dict:
    """保持历史导入入口；比较规则归 Aggregator 所有。"""
    from ..aggregator.comparison import compare_runs as compare

    return compare(baseline, candidate)


def run_benchmark(
    tasks: list[dict],
    *,
    dataset: dict,
    config: dict,
    output: Path,
    repeats: int = 1,
    concurrency: int = 4,
    offline: bool = False,
    provider_registry: ProviderRegistry | None = None,
    domain: BenchmarkDomain | None = None,
) -> dict:
    runtime = InspectRuntime.load()

    from ..composition import resolve_benchmark_adapter
    from .domains.file_tools import FileToolsDomain
    from .scorers.reference_runner import reference_observation

    if domain is not None:
        if offline:
            raise ValueError(
                "custom domains require a registered offline adapter for demos"
            )
    selected_domain = domain if domain is not None else FileToolsDomain()
    execution_task = selected_domain.execution_task
    score_task = selected_domain.score_task

    validate_config(config)
    if not tasks or not 1 <= repeats <= 5 or not 1 <= concurrency <= 12:
        raise ValueError("nonempty tasks, 1–5 repeats and 1–12 concurrency required")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    adapter = None if offline else resolve_benchmark_adapter(config, provider_registry)
    source = deepcopy(
        {"mode": "reference_smoke_only"} if offline else adapter.runtime_identity()
    )
    modes = sorted({task.get("execution_mode", "agent") for task in tasks})
    scoring = selected_domain.identity()
    identity = {
        "dataset": dataset,
        "scoring_version": scoring["version"],
        "scoring_identity": scoring,
        "harness_source": code_identity(
            [
                "runner.py",
                "../agent_adapter.py",
                "../provider_registry.py",
                "../composition.py",
                "inspect_runtime.py",
                "inspect_docker.py",
            ]
        ),
        "inspect_ai": version("inspect_ai"),
        "harness_version": HARNESS_VERSION,
        "config": config,
        "runtime": source,
        "runtime_modes": {
            mode: deepcopy(adapter.runtime_identity(mode)) for mode in modes
        }
        if not offline
        else {},
        "adapter": adapter_identity(adapter) if adapter is not None else None,
        "case_ids": [t["id"] for t in tasks],
        "repeats": repeats,
        "offline": offline,
    }
    identity_hash = digest(identity)
    lock_path = output / ".running"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(
            "run directory is locked; verify the previous process ended "
            "before removing .running"
        ) from exc
    os.write(lock_fd, str(os.getpid()).encode())
    os.close(lock_fd)
    try:
        return _run(
            tasks,
            context=RunContext(
                config=config,
                output=output,
                repeats=repeats,
                concurrency=concurrency,
                offline=offline,
                identity=identity,
                identity_hash=identity_hash,
                adapter=adapter,
                reference_observation=reference_observation,
                execution_task=execution_task,
                score_task=score_task,
                source=source,
            ),
            runtime=runtime,
        )
    finally:
        lock_path.unlink(missing_ok=True)


def _run(tasks: list[dict], *, context: RunContext, runtime: InspectRuntime) -> dict:
    from inspect_ai import Epochs
    from inspect_ai.util import LimitExceededError

    from .inspect_docker import SandboxEnvironmentChanged
    from .inspect_runtime import (
        apply_native_limits,
        sample_files,
    )

    meta_path = context.output / "run.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta["identity_hash"] != context.identity_hash:
            raise ValueError(
                "resume identity changed: "
                "dataset/config/source/repeats must remain fixed"
            )
        if (context.output / "results.json").exists():
            existing = json.loads((context.output / "results.json").read_text())
            if existing["identity_hash"] != context.identity_hash:
                raise ValueError("completed results identity mismatch")
            return existing
    else:
        modes = {task.get("execution_mode", "agent") for task in tasks}
        kinds = (
            {context.adapter.execution_kind(mode) for mode in modes}
            if not context.offline
            else set()
        )
        meta = {
            "run_id": context.output.name + "-" + uuid.uuid4().hex[:16],
            "identity_hash": context.identity_hash,
            "identity": context.identity,
            "config": context.config,
            "started_at": now(),
            "planned_case_ids": [task["id"] for task in tasks],
            "trials_per_case": context.repeats,
            "execution_backend": "inspect_ai",
            "scoring_backend": "deepeval",
            "inspect_log_dir": "inspect",
            "mode": "offline_reference_smoke"
            if context.offline
            else next(iter(kinds))
            if len(kinds) == 1
            else "mixed_execution",
        }
        save_json(meta_path, meta)
    by_id = {task["id"]: task for task in tasks}
    if len(by_id) != len(tasks):
        raise ValueError("task identifiers must be unique")
    indices = {task["id"]: index + 1 for index, task in enumerate(tasks)}
    pending = {}
    records = {}
    modes = {task.get("execution_mode", "agent") for task in tasks}
    needs_model = not context.offline and any(
        context.adapter.needs_model(mode) for mode in modes
    )
    model = context.adapter.inspect_model() if needs_model else "mockllm/model"
    sandboxes = {
        mode: "local"
        if context.offline
        else context.adapter.sandbox_spec(
            context.output / "sandbox-build",
            needs_model=context.adapter.needs_model(mode),
        )
        for mode in sorted(modes)
    }
    if not context.offline and context.config.get("sandbox"):
        for selected in sandboxes.values():
            actual = selected[0] if isinstance(selected, tuple) else selected
            if context.config["sandbox"] != actual:
                raise ValueError(
                    f"adapter sandbox {actual!r} cannot satisfy requested "
                    f"sandbox {context.config['sandbox']!r}"
                )

    def key_for(case_id, epoch):
        return f"{indices[case_id]:04d}-t{epoch}"

    @runtime.solver
    def agent_execution():
        async def solve(state, generate):
            task = by_id[str(state.sample_id)]
            trial = state.epoch
            key = key_for(task["id"], trial)
            started, monotonic = now(), time.monotonic()
            pending_error = None
            mode = task.get("execution_mode", "agent")
            try:
                if context.offline:
                    observation = context.reference_observation(task)
                    observation["runtime_identity"] = context.source
                else:
                    require_runtime_identity(
                        context.source, context.adapter.runtime_identity()
                    )
                    require_runtime_identity(
                        context.identity["adapter"], adapter_identity(context.adapter)
                    )
                    expected_source = context.identity["runtime_modes"][mode]
                    require_runtime_identity(
                        expected_source, context.adapter.runtime_identity(mode)
                    )
                    selected_sandbox = sandboxes[mode]
                    effective = {
                        **context.config,
                        "sandbox": selected_sandbox[0]
                        if isinstance(selected_sandbox, tuple)
                        else selected_sandbox,
                    }
                    if isinstance(selected_sandbox, tuple):
                        effective["_inspect_docker_compose"] = selected_sandbox[1]
                    native_execute = getattr(
                        context.adapter, "execute_in_inspect", None
                    )
                    if callable(native_execute):
                        observation = await native_execute(
                            context.execution_task(task),
                            mode=mode,
                            config=effective,
                            state=state,
                        )
                    else:
                        observation = await context.adapter.execute(
                            context.execution_task(task), mode=mode, config=effective
                        )
                    require_runtime_identity(
                        expected_source, observation["runtime_identity"]
                    )
                    require_runtime_identity(
                        context.source, context.adapter.runtime_identity()
                    )
                    require_runtime_identity(
                        expected_source, context.adapter.runtime_identity(mode)
                    )
                    require_runtime_identity(
                        context.identity["adapter"], adapter_identity(context.adapter)
                    )
            except BaseException as exc:
                observation = getattr(exc, "benchmark_observation", None) or {
                    "status": "error",
                    "turns": [],
                    "events": [],
                    "usage": {},
                    "errors": [
                        {
                            "kind": "harness",
                            "code": "runtime_identity_changed"
                            if isinstance(exc, RuntimeIdentityChanged)
                            else "sandbox_environment_changed"
                            if isinstance(exc, SandboxEnvironmentChanged)
                            else type(exc).__name__,
                            "message": str(exc),
                        }
                    ],
                    "runtime_identity": context.source,
                    "evidence_complete": False,
                }
                if isinstance(
                    exc,
                    (
                        LimitExceededError,
                        RuntimeIdentityChanged,
                        SandboxEnvironmentChanged,
                    ),
                ) or not isinstance(exc, Exception):
                    pending_error = exc
            observation["execution_kind"] = (
                "deterministic_reference_not_agent"
                if context.offline
                else context.adapter.execution_kind(mode)
            )
            row = {
                "identity_hash": context.identity_hash,
                "case_id": task["id"],
                "trial": trial,
                "category": task["category"],
                "split": task["split"],
                "family": task["family"],
                "evaluation_level": task.get("evaluation_level", "e2e"),
                "execution_mode": mode,
                "started_at": started,
                "finished_at": now(),
                "latency_seconds": time.monotonic() - monotonic,
                "cleanup_status": "inspect_managed",
                "observation": observation,
            }
            pending[key] = row
            runtime.transcript().info(
                {
                    "evidence_file": f"trials/{key}.json",
                    "case_id": task["id"],
                    "trial": trial,
                },
                source="benchmark_export",
            )
            state.output.completion = "\n".join(
                turn.get("output", "") for turn in observation.get("turns", [])
            )
            state.completed = True
            if pending_error:
                raise pending_error
            return state

        return solve

    @runtime.scorer(metrics=[])
    def deepeval_bridge():
        async def score(state, target):
            key = key_for(str(state.sample_id), state.epoch)
            row = pending.pop(key)
            apply_native_limits(row["observation"], runtime.transcript().events)
            task = by_id[str(state.sample_id)]
            try:
                assessment = await runtime.anyio.to_thread.run_sync(
                    lambda: context.score_task(task, row["observation"])
                )
            except Exception as exc:
                assessment = {
                    "verdict": "INVALID",
                    "validity": "INVALID",
                    "metrics": [],
                    "errors": ["scorer_exception:" + type(exc).__name__],
                    "scoring_backend": "deepeval",
                }
            row["assessment"] = assessment
            save_json(context.output / "trials" / f"{key}.json", row)
            records[key] = row
            return runtime.Score(
                value=assessment["verdict"],
                explanation=json.dumps(assessment, ensure_ascii=False),
                metadata={"benchmark_record": row},
            )

        return score

    dataset = [
        runtime.Sample(
            id=task["id"],
            input=task["prompt"],
            target="",
            files=sample_files(task["fixtures"]),
            metadata={"case_id": task["id"]},
            sandbox=sandboxes[task.get("execution_mode", "agent")],
        )
        for task in tasks
    ]
    task = runtime.Task(
        name="file_tool_benchmark",
        version=HARNESS_VERSION,
        dataset=dataset,
        solver=agent_execution(),
        scorer=deepeval_bridge(),
        epochs=Epochs(context.repeats, reducer="mode"),
        token_limit=context.config.get("token_limit"),
        message_limit=context.config.get("message_limit"),
        time_limit=int(context.config.get("timeout_seconds", 180)),
        score_on_error=True,
        metadata={
            "identity_hash": context.identity_hash,
            "scoring_backend": "deepeval",
            "model_owner": "inspect_ai",
        },
    )
    success, logs = runtime.inspect_eval(
        task,
        model=model,
        display="none",
        ctl_server=False,
        notification=False,
        log_dir=str(context.output / "inspect"),
        max_samples=context.concurrency,
        retry_attempts=1,
        retry_on_error=0,
        fail_on_error=False,
        score_on_error=True,
        log_realtime=False,
        log_samples=True,
    )
    # Reconstruct exports from authoritative native logs, including eval_set reuse.
    for log in logs:
        if log.samples is None and log.location:
            from inspect_ai.log import read_eval_log

            log = read_eval_log(log.location)
        for sample in log.samples or []:
            for score_value in (sample.scores or {}).values():
                row = (score_value.metadata or {}).get("benchmark_record")
                if row:
                    if row["identity_hash"] != context.identity_hash:
                        raise ValueError("Inspect sample belongs to another run")
                    key = key_for(row["case_id"], row["trial"])
                    records[key] = row
                    save_json(context.output / "trials" / f"{key}.json", row)
    expected = [
        key_for(task["id"], trial)
        for task in tasks
        for trial in range(1, context.repeats + 1)
    ]
    if any(
        error.get("code") in {"runtime_identity_changed", "sandbox_environment_changed"}
        for row in records.values()
        for error in row["observation"].get("errors", [])
        if isinstance(error, dict)
    ):
        raise RuntimeIdentityChanged(
            "runtime or sandbox identity changed; Inspect evidence preserved, "
            "use a new run directory"
        )
    if not success or any(key not in records for key in expected):
        raise RuntimeError(
            "Inspect execution incomplete; rerun with identical identity to resume"
        )
    result = {
        **meta,
        "finished_at": now(),
        "trials": [records[key] for key in expected],
        "summary": summarize(
            list(records.values()), meta["planned_case_ids"], context.repeats
        ),
    }
    save_json(context.output / "results.json", result)
    return result
