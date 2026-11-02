"""Inspect-owned offline execution of the frozen nanobot core module suite."""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .capability_coverage import snapshot_nanobot
from .core_scoring import score_core_task
from .core_tasks import core_dataset_identity, core_execution_task, load_core_tasks
from .inspect_runtime import apply_native_limits, sample_files
from .runner import digest, save_json


def validate_core_config(config: dict) -> dict:
    if not isinstance(config, dict) or set(config) != {"nanobot_root", "python"}:
        raise ValueError("core config requires only nanobot_root and python")
    if any(
        not isinstance(value, str) or not value.strip() for value in config.values()
    ):
        raise ValueError("core config paths must be nonempty strings")
    return {
        key: str(Path(value).expanduser().absolute()) for key, value in config.items()
    }


def _runtime_identity(snapshot: dict) -> dict:
    profile = snapshot["profiles"]["core_modules"]
    return {
        "snapshot": snapshot["snapshot_hash"],
        "profile": "core_modules",
        "profile_hash": profile["profile_hash"],
        "adapter_sha256": profile["adapter_sha256"],
        "scoring_sha256": profile["scoring_sha256"],
        "source_sha256": snapshot["source"]["working_tree_sha256"],
        "dependencies_sha256": snapshot["environment"]["dependencies_sha256"],
    }


def core_command(config: dict, args: list[str]) -> list[str]:
    """Match the identity probe's isolated startup before adding source paths."""
    harness = str(Path(__file__).parent)
    process_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "en_US.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    bootstrap = """import sys,runpy,importlib.util
from pathlib import Path
root,harness=map(Path,sys.argv[1:3])
sys.path[:0]=[str(root),str(harness)]
origin=Path(importlib.util.find_spec('nanobot').origin).resolve()
if origin != root.resolve()/'nanobot'/'__init__.py':
    raise RuntimeError('nanobot import source mismatch')
args=sys.argv[3:]
if args[0]=='-c':
    sys.argv=['-c',*args[2:]]
    exec(compile(args[1],'<core-boundary>','exec'))
else:
    sys.argv=args
    runpy.run_path(args[0],run_name='__main__')
"""
    return [
        "env",
        "-i",
        *[f"{k}={v}" for k, v in process_env.items()],
        config["python"],
        "-I",
        "-B",
        "-X",
        "pycache_prefix="
        + str(Path(tempfile.gettempdir()) / ("core-no-cache-" + uuid.uuid4().hex)),
        "-c",
        bootstrap,
        config["nanobot_root"],
        harness,
        *args,
    ]


async def execute_core_boundary(public: dict, *, config: dict, identity: dict) -> dict:
    """Fixed trusted module calls, not a security sandbox for hostile code."""
    from inspect_ai.util import sandbox

    environment = sandbox()
    harness = str(Path(__file__).parent)

    async def exec_json(args, *, stdin=None):
        response = await environment.exec(
            core_command(config, args[1:]), input=stdin, timeout=45
        )
        if not response.success:
            raise RuntimeError("core subprocess failed: " + response.stderr[-2000:])
        return json.loads(response.stdout)

    root = await exec_json(
        [
            config["python"],
            "-c",
            "import os,pathlib,json; pathlib.Path('workspace').mkdir(exist_ok=True); "
            "pathlib.Path('runtime').mkdir(exist_ok=True); "
            "print(json.dumps(os.getcwd()))",
        ]
    )
    workspace, runtime = root + "/workspace", root + "/runtime"

    async def snapshot(path):
        return await exec_json(
            [
                config["python"],
                "-c",
                "import json,sys; from pathlib import Path; "
                "from nanobot_runtime import snapshot_files; "
                "print(json.dumps(snapshot_files(Path(sys.argv[1])),ensure_ascii=False))",
                path,
            ]
        )

    observation = {
        "status": "error",
        "execution_kind": "real_core_module",
        "events": [],
        "errors": [],
        "usage": {},
        "before_files": None,
        "final_files": None,
        "session_files": None,
        "evidence_complete": False,
        "runtime_identity": identity,
        "execution_backend": "inspect_ai",
    }
    try:
        observation["before_files"] = await snapshot(workspace)
        response = await exec_json(
            [config["python"], str(Path(harness) / "core_worker.py")],
            stdin=json.dumps(
                {"task": public, "workspace": workspace, "runtime_dir": runtime},
                ensure_ascii=False,
            ),
        )
        for field in ("status", "execution_kind", "events", "errors", "usage"):
            observation[field] = response[field]
        observation["final_files"] = await snapshot(workspace)
        observation["session_files"] = await snapshot(runtime)
        observation["evidence_complete"] = observation["status"] == "completed"
    except Exception as exc:
        observation["status"] = "error"
        observation["evidence_complete"] = False
        observation["errors"].append({"code": type(exc).__name__, "message": str(exc)})
    return observation


def summarize_core(rows: list[dict], planned: list[str], repeats: int) -> dict:
    counts = Counter(row["assessment"]["verdict"] for row in rows)
    valid = sum(row["assessment"]["validity"] == "VALID" for row in rows)
    total = len(planned) * repeats
    passed = counts["PASS"]
    all_passed = sum(
        len(selected := [row for row in rows if row["case_id"] == case_id]) == repeats
        and all(row["assessment"]["verdict"] == "PASS" for row in selected)
        for case_id in planned
    )
    return {
        "execution_kind": "real_core_module",
        "planned_cases": len(planned),
        "trials_per_case": repeats,
        "planned_trials": total,
        "observed_trials": len(rows),
        "missing_trials": total - len(rows),
        "verdict_counts": dict(counts),
        "valid_trials": valid,
        "pass_rate_planned": passed / total if total else None,
        "pass_rate_valid": passed / valid if valid else None,
        "all_repeats_passed_cases": all_passed,
        "human_reviewed_cases": 0,
        "latency_seconds_total": sum(row["latency_seconds"] for row in rows),
        "model_calls": 0,
        "tokens": None,
        "provider_cost": None,
        "scope": "固定输入下的组件行为；不代表模型、完整 Agent 或跨进程重启成功率",
    }


def run_core_benchmark(
    dataset: Path, config: dict, output: Path, *, repeats=3, concurrency=4
) -> dict:
    """Only dev is executable in v1; reserved holdout remains schema-validated."""
    import anyio
    from inspect_ai import Epochs, Task, eval_set
    from inspect_ai.dataset import Sample
    from inspect_ai.log import read_eval_log, transcript
    from inspect_ai.scorer import Score, scorer
    from inspect_ai.solver import solver

    config = validate_core_config(config)
    if (
        type(repeats) is not int
        or repeats < 1
        or type(concurrency) is not int
        or concurrency < 1
    ):
        raise ValueError("repeats and concurrency must be positive integers")
    dataset_identity = core_dataset_identity(dataset)
    tasks = [task for task in load_core_tasks(dataset) if task["split"] == "dev"]
    if core_dataset_identity(dataset) != dataset_identity:
        raise RuntimeError("dataset identity changed while loading tasks")
    if not tasks:
        raise ValueError("core-run requires dev tasks; holdout execution is disabled")
    if output.exists():
        raise ValueError("output already exists; use a new run directory")
    snapshot = snapshot_nanobot(config)
    runtime_identity = _runtime_identity(snapshot)
    identity = {
        "dataset": dataset_identity,
        **runtime_identity,
        "controls": {
            "split": "dev",
            "repeats": repeats,
            "concurrency": concurrency,
            "time_limit_seconds": 120,
            "model_calls": 0,
        },
    }
    identity_hash = digest(identity)
    by_id = {task["id"]: task for task in tasks}
    planned = list(by_id)
    meta = {
        "run_id": "nanobot-core-" + uuid.uuid4().hex,
        "identity": identity,
        "identity_hash": identity_hash,
        "planned_case_ids": planned,
        "trials_per_case": repeats,
        "started_at": datetime.now(UTC).isoformat(),
    }
    output.mkdir(parents=True)
    save_json(output / "snapshot.json", snapshot)
    save_json(output / "run.json", meta)
    pending, records = {}, {}
    drifted = False

    async def require_identity():
        current = await anyio.to_thread.run_sync(lambda: snapshot_nanobot(config))
        if current != snapshot or core_dataset_identity(dataset) != dataset_identity:
            raise RuntimeError("runtime or dataset identity changed")

    @solver
    def core_execution():
        async def solve(state, generate):
            nonlocal drifted
            task = by_id[str(state.sample_id)]
            started = time.monotonic()
            pending_error = None
            try:
                await require_identity()
                observation = await execute_core_boundary(
                    core_execution_task(task), config=config, identity=runtime_identity
                )
                await require_identity()
            except BaseException as exc:
                drifted = drifted or "identity changed" in str(exc)
                observation = {
                    "status": "error",
                    "execution_kind": "real_core_module",
                    "events": [],
                    "errors": [{"code": type(exc).__name__, "message": str(exc)}],
                    "usage": {},
                    "runtime_identity": runtime_identity,
                    "evidence_complete": False,
                }
                if not isinstance(exc, Exception):
                    pending_error = exc
            pending[(task["id"], state.epoch)] = {
                "identity_hash": identity_hash,
                "case_id": task["id"],
                "trial": state.epoch,
                "component": task["component"],
                "family": task["family"],
                "split": task["split"],
                "latency_seconds": time.monotonic() - started,
                "observation": observation,
            }
            state.completed = True
            if pending_error is not None:
                raise pending_error
            return state

        return solve

    @scorer(metrics=[])
    def core_deepeval():
        async def score(state, target):
            key = (str(state.sample_id), state.epoch)
            row = pending.pop(key)
            apply_native_limits(row["observation"], transcript().events)
            row["assessment"] = await anyio.to_thread.run_sync(
                lambda: score_core_task(by_id[key[0]], row["observation"])
            )
            return Score(
                value=row["assessment"]["verdict"],
                metadata={"benchmark_record": row},
                explanation=json.dumps(row["assessment"], ensure_ascii=False),
            )

        return score

    task = Task(
        name="nanobot_core_modules",
        version="1",
        dataset=[
            Sample(
                id=task["id"],
                input="执行固定组件操作",
                target="",
                files=sample_files(task["fixtures"]),
            )
            for task in tasks
        ],
        solver=core_execution(),
        scorer=core_deepeval(),
        sandbox="local",
        epochs=Epochs(repeats, reducer="mode"),
        time_limit=120,
        score_on_error=True,
        metadata={"identity_hash": identity_hash, "scoring_backend": "deepeval"},
    )
    success, logs = eval_set(
        task,
        model="mockllm/model",
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
    for log in logs:
        if log.samples is None and log.location:
            log = read_eval_log(log.location)
        for sample in log.samples or []:
            for score_value in (sample.scores or {}).values():
                row = (score_value.metadata or {}).get("benchmark_record")
                if row:
                    key = (row["case_id"], row["trial"])
                    if row["identity_hash"] != identity_hash or key in records:
                        raise ValueError("duplicate or mismatched Inspect evidence")
                    records[key] = row
                    save_json(
                        output
                        / "trials"
                        / f"{planned.index(key[0]):04d}-t{key[1]}.json",
                        row,
                    )
    expected = [
        (case_id, trial) for case_id in planned for trial in range(1, repeats + 1)
    ]
    if (
        drifted
        or snapshot_nanobot(config) != snapshot
        or core_dataset_identity(dataset) != dataset_identity
    ):
        raise RuntimeError("runtime identity changed; native evidence preserved")
    if not success or set(expected) != set(records):
        raise RuntimeError("Inspect execution incomplete; native evidence preserved")
    rows = [records[key] for key in expected]
    result = {
        **meta,
        "finished_at": datetime.now(UTC).isoformat(),
        "trials": rows,
        "summary": summarize_core(rows, planned, repeats),
    }
    save_json(output / "results.json", result)
    return result
