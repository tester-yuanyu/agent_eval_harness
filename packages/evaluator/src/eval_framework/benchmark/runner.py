"""Inspectable execution, immutable per-trial journals and independent scoring."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import statistics
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

HARNESS_VERSION = "file-harness-v2"


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
    for field in ("dataset", "scoring_version"):
        if baseline["identity"][field] != candidate["identity"][field]:
            raise ValueError(f"comparison requires identical {field}")
    for field in ("harness_version", "harness_source", "scoring_identity", "offline"):
        if baseline["identity"].get(field) != candidate["identity"].get(field):
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
) -> dict:
    import anyio
    from inspect_ai import Task
    from inspect_ai import eval as inspect_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.log import transcript
    from inspect_ai.scorer import Score, scorer
    from inspect_ai.solver import solver

    from .metrics import score_task
    from .nanobot_runtime import execute_task, runtime_identity
    from .oracle import reference_observation
    from .tasks import execution_task

    validate_config(config)
    if not tasks or not 1 <= repeats <= 5 or not 1 <= concurrency <= 12:
        raise ValueError("nonempty tasks, 1–5 repeats and 1–12 concurrency required")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = {"mode": "reference_smoke_only"} if offline else runtime_identity(config)
    scoring = scoring_identity()
    identity = {
        "dataset": dataset,
        "scoring_version": scoring["version"],
        "scoring_identity": scoring,
        "harness_source": code_identity(
            [
                "runner.py",
                "nanobot_runtime.py",
                "nanobot_worker.py",
                "module_runtime.py",
                "module_worker.py",
                "decision_runtime.py",
                "decision_worker.py",
            ]
        ),
        "inspect_ai": version("inspect_ai"),
        "harness_version": HARNESS_VERSION,
        "config": config,
        "runtime": source,
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
            execute_task,
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
    execute_task,
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
        meta = {
            "run_id": output.name + "-" + uuid.uuid4().hex[:16],
            "identity_hash": identity_hash,
            "identity": identity,
            "config": config,
            "started_at": now(),
            "planned_case_ids": [t["id"] for t in tasks],
            "trials_per_case": repeats,
            "execution_backend": "inspect_ai",
            "scoring_backend": "deepeval",
            "mode": "offline_reference_smoke"
            if offline
            else (
                "real_module"
                if all(t.get("execution_mode") == "module" for t in tasks)
                else "real_model_decision"
                if all(t.get("execution_mode") == "decision" for t in tasks)
                else "mixed_real_execution"
                if any(t.get("execution_mode") == "module" for t in tasks)
                else "real_agent"
            ),
        }
        save_json(meta_path, meta)
    jobs = {
        f"{index + 1:04d}-t{trial}": (task, trial)
        for index, task in enumerate(tasks)
        for trial in range(1, repeats + 1)
    }
    records = {}
    for key in jobs:
        path = output / "trials" / f"{key}.json"
        if path.exists():
            row = json.loads(path.read_text())
            if row.get("identity_hash") != identity_hash:
                raise ValueError("trial journal belongs to another run")
            records[key] = row
    pending = {}

    @solver
    def agent_execution():
        async def solve(state, generate):
            key = str(state.sample_id)
            task, trial = jobs[key]
            started = now()
            monotonic = time.monotonic()
            workspace = Path(tempfile.mkdtemp(prefix="agent-benchmark-")) / "workspace"
            try:
                workspace.mkdir()
                from .nanobot_runtime import runtime_identity, safe_path

                for name, content in task["fixtures"].items():
                    path = safe_path(workspace, name)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                if offline:
                    observation = reference_observation(task)
                    observation["runtime_identity"] = source
                else:
                    require_runtime_identity(source, runtime_identity(config))
                    executor = execute_task
                    if task.get("execution_mode") == "module":
                        from .module_runtime import execute_module_task

                        executor = execute_module_task
                    elif task.get("execution_mode") == "decision":
                        from .decision_runtime import execute_decision_task

                        executor = execute_decision_task
                    observation = await executor(
                        execution_task(task), config=config, workspace=workspace
                    )
                    try:
                        observed_source = source
                        if task.get("execution_mode") == "module":
                            from .module_runtime import module_identity

                            observed_source = module_identity(config)
                        elif task.get("execution_mode") == "decision":
                            from .decision_runtime import decision_identity

                            observed_source = decision_identity(config)
                        require_runtime_identity(
                            observed_source, observation["runtime_identity"]
                        )
                        require_runtime_identity(source, runtime_identity(config))
                    except RuntimeIdentityChanged:
                        observation["status"] = "error"
                        observation["errors"].append(
                            {
                                "kind": "harness",
                                "code": "runtime_identity_changed",
                                "message": "Agent source changed during experiment",
                            }
                        )
                observation["execution_kind"] = (
                    "deterministic_reference_not_agent"
                    if offline
                    else (
                        {
                            "module": "real_module",
                            "decision": "real_model_decision",
                        }.get(task.get("execution_mode"), "real_agent")
                    )
                )
            except Exception as exc:
                observation = {
                    "status": "error",
                    "turns": [],
                    "events": [],
                    "usage": {},
                    "errors": [
                        {
                            "kind": "harness",
                            "code": "runtime_identity_changed"
                            if isinstance(exc, RuntimeIdentityChanged)
                            else type(exc).__name__,
                            "message": type(exc).__name__,
                        }
                    ],
                    "runtime_identity": source,
                }
            finally:
                try:
                    shutil.rmtree(workspace.parent)
                    cleanup = "complete"
                except OSError:
                    cleanup = "failed"
            row = {
                "identity_hash": identity_hash,
                "case_id": task["id"],
                "trial": trial,
                "category": task["category"],
                "split": task["split"],
                "family": task["family"],
                "evaluation_level": task.get("evaluation_level", "e2e"),
                "execution_mode": task.get("execution_mode", "agent"),
                "started_at": started,
                "finished_at": now(),
                "latency_seconds": time.monotonic() - monotonic,
                "cleanup_status": cleanup,
                "observation": observation,
            }
            pending[key] = row
            transcript().info(
                {
                    "evidence_file": f"trials/{key}.json",
                    "status": observation["status"],
                    "case_id": task["id"],
                    "trial": trial,
                },
                source="benchmark_evidence",
            )
            state.output.completion = "\n".join(
                t.get("output", "") for t in observation.get("turns", [])
            )
            state.completed = True
            return state

        return solve

    @scorer(metrics=[])
    def deepeval_bridge():
        async def score(state, target):
            key = str(state.sample_id)
            row = pending.pop(key)
            task, _ = jobs[key]
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
            if row["cleanup_status"] != "complete":
                assessment = {
                    **assessment,
                    "verdict": "INVALID",
                    "validity": "INVALID",
                    "errors": assessment.get("errors", []) + ["cleanup_failed"],
                }
            row["assessment"] = assessment
            save_json(output / "trials" / f"{key}.json", row)
            records[key] = row
            if any(
                isinstance(error, dict)
                and error.get("code") == "runtime_identity_changed"
                for error in row["observation"].get("errors", [])
            ):
                raise RuntimeError("runtime identity changed; stop this experiment")
            print(
                json.dumps(
                    {
                        "completed": len(records),
                        "planned": len(jobs),
                        "case": row["case_id"],
                        "trial": row["trial"],
                        "verdict": assessment["verdict"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            # Inspect persists the DeepEval result without a second metric.
            return Score(
                value=assessment["verdict"],
                explanation=json.dumps(assessment, ensure_ascii=False),
            )

        return score

    remaining = [
        Sample(
            id=key,
            input=task["prompt"],
            target="",
            metadata={"case_id": task["id"], "trial": trial},
        )
        for key, (task, trial) in jobs.items()
        if key not in records
    ]
    if remaining:
        task = Task(
            name="file_tool_benchmark",
            version=HARNESS_VERSION,
            dataset=remaining,
            solver=agent_execution(),
            scorer=deepeval_bridge(),
            metadata={
                "identity_hash": identity_hash,
                "scoring_backend": "deepeval",
                "model_owner": "nanobot",
            },
        )
        logs = inspect_eval(
            task,
            model="mockllm/model",
            display="none",
            ctl_server=False,
            notification=False,
            log_dir=str(output / "inspect"),
            max_samples=concurrency,
            retry_on_error=0,
            fail_on_error=True,
            log_realtime=False,
            log_samples=True,
        )
        if not logs or logs[0].status != "success":
            raise RuntimeError(
                "Inspect execution incomplete; completed trial journals can be resumed"
            )
    result = {
        **meta,
        "finished_at": now(),
        "trials": [records[key] for key in jobs],
        "summary": summarize(list(records.values()), meta["planned_case_ids"], repeats),
    }
    save_json(output / "results.json", result)
    return result
