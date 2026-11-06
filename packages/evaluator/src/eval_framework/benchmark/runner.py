"""Inspectable execution, immutable per-trial journals and independent scoring."""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import time
import uuid
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from ..agent_adapter import adapter_identity
from ..provider_registry import ProviderRegistry
from .domain import BenchmarkDomain

HARNESS_VERSION = "file-harness-inspect-v4"


class RuntimeIdentityChanged(RuntimeError):
    pass


def code_identity(names: list[str]) -> str:
    root = Path(__file__).parent
    return digest(
        {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    )


def scoring_identity() -> dict:
    from .metrics import METRICS_VERSION
    from .tasks import GRADER_VERSION

    return {
        "version": METRICS_VERSION,
        "deepeval": version("deepeval"),
        "oracle": GRADER_VERSION,
        "source_sha256": code_identity(
            [
                "metrics.py",
                "oracle.py",
                "tasks.py",
                "trajectory.py",
                "module_oracle.py",
                "recovery_scoring.py",
                "repetition.py",
                "agentic_metrics.py",
                "agentic_metrics_worker.py",
            ]
        ),
    }


def require_runtime_identity(expected: dict, actual: dict) -> None:
    if actual != expected:
        raise RuntimeIdentityChanged(
            "runtime source/configuration changed during the experiment"
        )


def now() -> str:
    return datetime.now(UTC).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


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
    counts = Counter(r["assessment"]["verdict"] for r in records)
    valid = sum(r["assessment"]["validity"] == "VALID" for r in records)
    planned = len(case_ids) * repeats
    by_case = defaultdict(list)
    for record in records:
        by_case[record["case_id"]].append(record)
    all_pass = sum(
        len(by_case[c]) == repeats
        and all(r["assessment"]["verdict"] == "PASS" for r in by_case[c])
        for c in case_ids
    )
    latencies = sorted(r["latency_seconds"] for r in records)
    usage_records = [r["observation"].get("usage", {}) for r in records]
    usage = {}
    for key in ("input_tokens", "output_tokens", "total_tokens", "cost_usd"):
        alias = {
            "input_tokens": "prompt_tokens",
            "output_tokens": "completion_tokens",
        }.get(key, key)
        values = [u.get(key, u.get(alias)) for u in usage_records]
        known = [v for v in values if isinstance(v, (int, float))]
        usage[key] = sum(known) if known and len(known) == len(values) else None
        usage[key + "_known_subtotal"] = sum(known) if known else None
        usage[key + "_known_trials"] = len(known)
    result = {
        "unique_tasks": len(case_ids),
        "trials_per_case": repeats,
        "planned_trials": planned,
        "completed_trials": len(records),
        "missing_trials": planned - len(records),
        "valid_trials": valid,
        "verdicts": dict(counts),
        "pass_rate_planned": counts["PASS"] / planned if planned else None,
        "pass_rate_valid": counts["PASS"] / valid if valid else None,
        "all_trials_pass_rate": all_pass / len(case_ids) if case_ids else None,
        "all_trials_pass_definition": (
            "All k planned real trials passed; missing and invalid trials "
            "cannot prove success."
        ),
        "latency_seconds_median": statistics.median(latencies) if latencies else None,
        "latency_seconds_p95": latencies[
            min(len(latencies) - 1, int(0.95 * len(latencies)))
        ]
        if latencies
        else None,
        "usage": usage,
    }
    result["mixed_execution_populations"] = (
        len({r.get("execution_mode", "agent") for r in records}) > 1
    )
    for dimension in ("split", "category", "evaluation_level", "execution_mode"):
        groups = defaultdict(list)
        for record in records:
            fallback = "e2e" if dimension == "evaluation_level" else "agent"
            groups[record.get(dimension, fallback)].append(record)
        result["by_" + dimension] = {
            name: {
                "trials": len(rows),
                "unique_tasks": len({r["case_id"] for r in rows}),
                "verdicts": dict(Counter(r["assessment"]["verdict"] for r in rows)),
                "pass_rate_observed": sum(
                    r["assessment"]["verdict"] == "PASS" for r in rows
                )
                / len(rows),
            }
            for name, rows in sorted(groups.items())
        }
    return result


def compare_runs(baseline: dict, candidate: dict) -> dict:
    for run in (baseline, candidate):
        count = run["trials_per_case"]
        cases = run["planned_case_ids"]
        if type(count) is not int or count < 1 or len(set(cases)) != len(cases):
            raise ValueError("comparison requires valid planned cases and trials")
        seen = set()
        for row in run["trials"]:
            key = (row["case_id"], row["trial"])
            if (
                type(row["trial"]) is not int
                or not 1 <= row["trial"] <= count
                or row["case_id"] not in cases
            ):
                raise ValueError("comparison contains invalid trial identifiers")
            if key in seen:
                raise ValueError("comparison contains duplicate case/trial rows")
            seen.add(key)
            if row.get("identity_hash") != run.get("identity_hash"):
                raise ValueError("trial identity_hash differs from its run")
        if "identity_hash" in run and run["identity_hash"] != digest(run["identity"]):
            raise ValueError("run identity_hash does not match identity")
    for field in ("dataset", "scoring_version"):
        if baseline["identity"][field] != candidate["identity"][field]:
            raise ValueError(f"comparison requires identical {field}")
    for field in (
        "harness_version",
        "harness_source",
        "scoring_identity",
        "offline",
        "inspect_ai",
    ):
        if baseline["identity"].get(field) != candidate["identity"].get(field):
            raise ValueError(f"comparison requires identical {field}")
    for field in ("execution_backend", "scoring_backend"):
        if baseline.get(field) != candidate.get(field):
            raise ValueError(f"comparison requires identical {field}")
    if baseline.get("mode") != candidate.get("mode"):
        raise ValueError("cannot compare offline reference with real Agent results")
    if (
        baseline["planned_case_ids"] != candidate["planned_case_ids"]
        or baseline["trials_per_case"] != candidate["trials_per_case"]
    ):
        raise ValueError(
            "comparison requires identical task selection and repeat count"
        )
    expected = {
        (case, t)
        for case in baseline["planned_case_ids"]
        for t in range(1, baseline["trials_per_case"] + 1)
    }
    rows = []
    indices = [
        {(r["case_id"], r["trial"]): r for r in run["trials"]}
        for run in (baseline, candidate)
    ]
    if any(set(index) != expected for index in indices):
        raise ValueError("cannot formally compare incomplete runs")
    for key in sorted(expected):
        left, right = (index[key]["assessment"]["verdict"] for index in indices)
        if left != right:
            rows.append(
                {
                    "case_id": key[0],
                    "trial": key[1],
                    "baseline": left,
                    "candidate": right,
                }
            )
    summaries = [
        summarize(run["trials"], run["planned_case_ids"], run["trials_per_case"])
        for run in (baseline, candidate)
    ]
    return {
        "baseline_run_id": baseline.get("run_id"),
        "candidate_run_id": candidate.get("run_id"),
        "dataset": baseline["identity"]["dataset"],
        "changed_trials": rows,
        "baseline": summaries[0],
        "candidate": summaries[1],
        "pass_rate_delta": summaries[1]["pass_rate_planned"]
        - summaries[0]["pass_rate_planned"],
        "interpretation": (
            "Descriptive paired comparison; no statistical significance claim."
        ),
        "configuration_changes": {
            k: [baseline.get("config", {}).get(k), candidate.get("config", {}).get(k)]
            for k in set(baseline.get("config", {})) | set(candidate.get("config", {}))
            if baseline.get("config", {}).get(k) != candidate.get("config", {}).get(k)
        },
    }


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
    import anyio
    from inspect_ai import Task
    from inspect_ai import eval_set as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.log import transcript
    from inspect_ai.scorer import Score, scorer
    from inspect_ai.solver import solver

    from ..composition import resolve_benchmark_adapter
    from .metrics import score_task
    from .oracle import reference_observation
    from .tasks import execution_task

    if domain is not None:
        if offline:
            raise ValueError(
                "custom domains require a registered offline adapter for demos"
            )
        execution_task = domain.execution_task
        score_task = domain.score_task

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
    scoring = domain.identity() if domain is not None else scoring_identity()
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
        } if not offline else {},
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
            config,
            output,
            repeats,
            concurrency,
            offline,
            identity,
            identity_hash,
            adapter,
            reference_observation,
            execution_task,
            score_task,
            source,
            Task,
            inspect_eval,
            Sample,
            Score,
            scorer,
            solver,
            transcript,
            anyio,
        )
    finally:
        lock_path.unlink(missing_ok=True)


def _run(
    tasks,
    config,
    output,
    repeats,
    concurrency,
    offline,
    identity,
    identity_hash,
    adapter,
    reference_observation,
    execution_task,
    score_task,
    source,
    Task,
    inspect_eval,
    Sample,
    Score,
    scorer,
    solver,
    transcript,
    anyio,
):
    from inspect_ai import Epochs
    from inspect_ai.util import LimitExceededError

    from .inspect_docker import SandboxEnvironmentChanged
    from .inspect_runtime import (
        apply_native_limits,
        sample_files,
    )

    meta_path = output / "run.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta["identity_hash"] != identity_hash:
            raise ValueError(
                "resume identity changed: "
                "dataset/config/source/repeats must remain fixed"
            )
        if (output / "results.json").exists():
            existing = json.loads((output / "results.json").read_text())
            if existing["identity_hash"] != identity_hash:
                raise ValueError("completed results identity mismatch")
            return existing
    else:
        modes = {task.get("execution_mode", "agent") for task in tasks}
        kinds = (
            {adapter.execution_kind(mode) for mode in modes} if not offline else set()
        )
        meta = {
            "run_id": output.name + "-" + uuid.uuid4().hex[:16],
            "identity_hash": identity_hash,
            "identity": identity,
            "config": config,
            "started_at": now(),
            "planned_case_ids": [task["id"] for task in tasks],
            "trials_per_case": repeats,
            "execution_backend": "inspect_ai",
            "scoring_backend": "deepeval",
            "inspect_log_dir": "inspect",
            "mode": "offline_reference_smoke"
            if offline
            else next(iter(kinds)) if len(kinds) == 1 else "mixed_execution",
        }
        save_json(meta_path, meta)
    by_id = {task["id"]: task for task in tasks}
    if len(by_id) != len(tasks):
        raise ValueError("task identifiers must be unique")
    indices = {task["id"]: index + 1 for index, task in enumerate(tasks)}
    pending = {}
    records = {}
    modes = {task.get("execution_mode", "agent") for task in tasks}
    needs_model = not offline and any(adapter.needs_model(mode) for mode in modes)
    model = adapter.inspect_model() if needs_model else "mockllm/model"
    sandboxes = {
        mode: "local" if offline else adapter.sandbox_spec(
            output / "sandbox-build", needs_model=adapter.needs_model(mode)
        )
        for mode in sorted(modes)
    }
    if not offline and config.get("sandbox"):
        for selected in sandboxes.values():
            actual = selected[0] if isinstance(selected, tuple) else selected
            if config["sandbox"] != actual:
                raise ValueError(
                    f"adapter sandbox {actual!r} cannot satisfy requested "
                    f"sandbox {config['sandbox']!r}"
                )

    def key_for(case_id, epoch):
        return f"{indices[case_id]:04d}-t{epoch}"

    @solver
    def agent_execution():
        async def solve(state, generate):
            task = by_id[str(state.sample_id)]
            trial = state.epoch
            key = key_for(task["id"], trial)
            started, monotonic = now(), time.monotonic()
            pending_error = None
            mode = task.get("execution_mode", "agent")
            try:
                if offline:
                    observation = reference_observation(task)
                    observation["runtime_identity"] = source
                else:
                    require_runtime_identity(source, adapter.runtime_identity())
                    require_runtime_identity(
                        identity["adapter"], adapter_identity(adapter)
                    )
                    expected_source = identity["runtime_modes"][mode]
                    require_runtime_identity(
                        expected_source, adapter.runtime_identity(mode)
                    )
                    selected_sandbox = sandboxes[mode]
                    effective = {
                        **config,
                        "sandbox": selected_sandbox[0]
                        if isinstance(selected_sandbox, tuple)
                        else selected_sandbox,
                    }
                    if isinstance(selected_sandbox, tuple):
                        effective["_inspect_docker_compose"] = selected_sandbox[1]
                    observation = await adapter.execute(
                        execution_task(task), mode=mode, config=effective
                    )
                    require_runtime_identity(
                        expected_source, observation["runtime_identity"]
                    )
                    require_runtime_identity(source, adapter.runtime_identity())
                    require_runtime_identity(
                        expected_source, adapter.runtime_identity(mode)
                    )
                    require_runtime_identity(
                        identity["adapter"], adapter_identity(adapter)
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
                    "runtime_identity": source,
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
                if offline
                else adapter.execution_kind(mode)
            )
            row = {
                "identity_hash": identity_hash,
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
            transcript().info(
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

    @scorer(metrics=[])
    def deepeval_bridge():
        async def score(state, target):
            key = key_for(str(state.sample_id), state.epoch)
            row = pending.pop(key)
            apply_native_limits(row["observation"], transcript().events)
            task = by_id[str(state.sample_id)]
            try:
                assessment = await anyio.to_thread.run_sync(
                    lambda: score_task(task, row["observation"])
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
            save_json(output / "trials" / f"{key}.json", row)
            records[key] = row
            return Score(
                value=assessment["verdict"],
                explanation=json.dumps(assessment, ensure_ascii=False),
                metadata={"benchmark_record": row},
            )

        return score

    dataset = [
        Sample(
            id=task["id"],
            input=task["prompt"],
            target="",
            files=sample_files(task["fixtures"]),
            metadata={"case_id": task["id"]},
            sandbox=sandboxes[task.get("execution_mode", "agent")],
        )
        for task in tasks
    ]
    task = Task(
        name="file_tool_benchmark",
        version=HARNESS_VERSION,
        dataset=dataset,
        solver=agent_execution(),
        scorer=deepeval_bridge(),
        epochs=Epochs(repeats, reducer="mode"),
        token_limit=config.get("token_limit"),
        message_limit=config.get("message_limit"),
        time_limit=int(config.get("timeout_seconds", 180)),
        score_on_error=True,
        metadata={
            "identity_hash": identity_hash,
            "scoring_backend": "deepeval",
            "model_owner": "inspect_ai",
        },
    )
    success, logs = inspect_eval(
        task,
        model=model,
        display="none",
        ctl_server=False,
        notification=False,
        log_dir=str(output / "inspect"),
        max_samples=concurrency,
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
                    if row["identity_hash"] != identity_hash:
                        raise ValueError("Inspect sample belongs to another run")
                    key = key_for(row["case_id"], row["trial"])
                    records[key] = row
                    save_json(output / "trials" / f"{key}.json", row)
    expected = [
        key_for(task["id"], trial) for task in tasks for trial in range(1, repeats + 1)
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
        "summary": summarize(list(records.values()), meta["planned_case_ids"], repeats),
    }
    save_json(output / "results.json", result)
    return result
