"""Explicit, resumable semantic annotation of immutable saved executions."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

from .regrade import _validate_source
from .runner import code_identity, digest, now, save_json, summarize, validate_config
from .tasks import dataset_identity, load_tasks

JUDGE_SOURCE_FILES = [
    "judging.py",
    "agentic_metrics.py",
    "agentic_metrics_worker.py",
    "metrics.py",
    "judge_run.py",
]

JUDGE_EXECUTION_SOURCE_FILES = [
    "judge_checkpoints.py",
    "judge_recovery.py",
    "request_policy.py",
    "scorers/trajectory_judge.py",
    "scorers/judge_client.py",
    "scorers/llm_judge.py",
]


def _judge_run_locked(
    source_dir: Path,
    dataset_path: Path,
    output_dir: Path,
    config: dict[str, Any],
    *,
    repeats: int = 1,
    concurrency: int = 2,
    limit: int | None = None,
    options: dict | None = None,
) -> dict[str, Any]:
    """Add diagnostic scores in a new run; never rerun an Agent or alter verdicts."""
    from .judging import (
        judge_observation,
        summarize_judgments,
        summarize_repeated_judgments,
    )

    source_dir, output_dir = Path(source_dir).resolve(), Path(output_dir).resolve()
    if output_dir == source_dir or output_dir.is_relative_to(source_dir):
        raise ValueError("Judge output must be outside the source run")
    if (
        type(repeats) is not int
        or type(concurrency) is not int
        or not 1 <= repeats <= 5
        or not 1 <= concurrency <= 8
    ):
        raise ValueError("Judge repeats must be 1–5 and concurrency 1–8")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("Judge task limit must be positive")
    validate_config(config)
    options = dict(options or {})
    allowed = {
        "metric_checkpoints",
        "metric_concurrency",
        "request_retries",
        "reuse_from",
        "retry_failed",
        "preflight",
    }
    if set(options) - allowed:
        raise ValueError("Unknown Judge execution options")
    for key in ("metric_checkpoints", "retry_failed", "preflight"):
        if key in options and type(options[key]) is not bool:
            raise ValueError(key + " must be boolean")
    metric_concurrency = options.get("metric_concurrency", 1)
    if type(metric_concurrency) is not int or not 1 <= metric_concurrency <= 8:
        raise ValueError("metric_concurrency must be 1–8")
    if concurrency * metric_concurrency > 16:
        raise ValueError("Combined Judge concurrency must be <=16")
    use_checkpoints = options.get("metric_checkpoints", False) or bool(
        options.get("reuse_from")
    )
    controls = (
        options.get("preflight")
        or options.get("request_retries", 0)
        or metric_concurrency > 1
        or options.get("retry_failed")
    )
    if controls and not use_checkpoints:
        raise ValueError("Judge execution controls require metric_checkpoints=True")
    if use_checkpoints:
        from .scorers.trajectory_judge import DIMENSIONS, GEVAL_DIMENSIONS

        if set(config.get("dimensions", DIMENSIONS)) - set(GEVAL_DIMENSIONS):
            raise ValueError(
                "Metric checkpoints require explicit GEval-only dimensions"
            )
    from .request_policy import RequestPolicy

    policy = RequestPolicy(retries=options.get("request_retries", 0))
    raw = (source_dir / "results.json").read_bytes()
    source = json.loads(raw)
    identify, load = dataset_identity, load_tasks
    full = (
        source["identity"]["dataset"].get("task_contract")
        == "builder-full-benchmark-v1"
    )
    if full:
        from .full_benchmark import dataset_identity as identify
        from .full_benchmark import load_tasks as load
    dataset = identify(dataset_path)
    if source["identity"]["dataset"] != dataset:
        raise ValueError("Judge dataset differs from the execution dataset")
    tasks = {t["id"]: t for t in load(dataset_path)}
    _validate_source(source, tasks)
    if (
        not full and source.get("mode") not in {"real_agent", "real_model_decision"}
    ) or source["identity"].get("offline") is True:
        raise ValueError("Judge requires saved real execution, not reference smoke")
    selected = source["planned_case_ids"][:limit]
    rows = [r for r in source["trials"] if r["case_id"] in selected]
    if not full and any(
        r.get("execution_mode") == "module"
        or r["observation"].get("execution_kind")
        in ("real_module", "deterministic_reference_not_agent")
        for r in rows
    ):
        raise ValueError("LLM Judge requires Agent decisions; select an Agent run")
    if source.get("provenance", {}).get("operation") == "judge_saved_evidence":
        raise ValueError(
            "Select original Agent execution evidence, not a prior Judge run"
        )
    config = copy.deepcopy(config)
    provenance = {
        "operation": "judge_saved_evidence",
        "source_run_id": source["run_id"],
        "source_results_sha256": hashlib.sha256(raw).hexdigest(),
        "source_identity_hash": source["identity_hash"],
        "new_agent_executions": 0,
        "judge_repeats": repeats,
        "calibration": "not_calibrated",
        "source_dir": str(source_dir),
    }
    identity = copy.deepcopy(source["identity"])
    identity.update(
        judge_config=config,
        judge_repeats=repeats,
        judge_source=code_identity(JUDGE_SOURCE_FILES),
        source_results_sha256=provenance["source_results_sha256"],
        case_ids=selected,
    )
    seeds = {}
    if options:
        identity["judge_execution_sources"] = code_identity(
            JUDGE_EXECUTION_SOURCE_FILES
        )
    if options:
        identity["judge_execution_options"] = {
            k: v for k, v in options.items() if k != "reuse_from"
        }
    if options.get("reuse_from"):
        from .judge_recovery import load_judge_seeds

        seeds, binding = load_judge_seeds(
            Path(options["reuse_from"]),
            source,
            provenance["source_results_sha256"],
            config,
            repeats,
        )
        if binding.get("checkpoint_hashes"):
            saved_meta = json.loads(Path(binding["source"]).read_text())
            if saved_meta["identity"].get("judge_execution_sources") != identity.get(
                "judge_execution_sources"
            ):
                raise ValueError(
                    "Partial metric recovery implementation changed; "
                    "cannot safely reuse checkpoints"
                )
        identity["judge_recovery"] = binding
        provenance["judge_recovery"] = binding
    identity_hash = digest(identity)
    output_dir.mkdir(parents=True, exist_ok=True)
    meta_path = output_dir / "judge-run.json"
    if meta_path.exists():
        if json.loads(meta_path.read_text())["identity_hash"] != identity_hash:
            raise ValueError("Judge resume identity changed")
        if (output_dir / "results.json").exists():
            result = json.loads((output_dir / "results.json").read_text())
            if (
                result.get("identity_hash") != identity_hash
                or digest(result.get("identity")) != identity_hash
            ):
                raise ValueError("Saved Judge result identity is inconsistent")
            return result
    else:
        if any(path.name != ".running" for path in output_dir.iterdir()):
            raise ValueError("Judge output directory must be empty")
        save_json(
            meta_path,
            {
                "identity_hash": identity_hash,
                "identity": identity,
                "provenance": provenance,
                "started_at": now(),
            },
        )

    def annotate(original: dict[str, Any]) -> dict[str, Any]:
        row = copy.deepcopy(original)
        row["execution_identity_hash"] = original.get(
            "execution_identity_hash", source["identity_hash"]
        )
        row["identity_hash"] = identity_hash
        row["source_assessment"] = copy.deepcopy(original["assessment"])
        row["source_trial_sha256"] = digest(original)
        row["execution_finished_at"] = original["finished_at"]
        for repeat in range(1, repeats + 1):
            key = digest([row["case_id"], row["trial"], repeat])[:24]
            journal = output_dir / "judgments" / f"{key}.json"
            if journal.exists():
                saved = json.loads(journal.read_text())
                if (
                    saved["identity_hash"] != identity_hash
                    or saved.get("source_trial_sha256") != digest(original)
                    or saved.get("judge_repeat") != repeat
                ):
                    raise ValueError("Judge journal belongs to another run or trial")
                metrics = saved["metrics"]
            else:
                # Always grade original public evidence, never previous Judge output.
                judge_input = copy.deepcopy(original["observation"])
                if full and not tasks[row["case_id"]]["live"]:
                    judge_input["execution_kind"] = "deterministic_reference_not_agent"
                if use_checkpoints:
                    from .judge_checkpoints import judge_with_checkpoints

                    metrics = judge_with_checkpoints(
                        tasks[row["case_id"]],
                        judge_input,
                        config,
                        output_dir / "metric-checkpoints",
                        repeat_identity=[
                            source["identity_hash"],
                            row["case_id"],
                            row["trial"],
                            repeat,
                        ],
                        concurrency=metric_concurrency,
                        retry_failed=options.get("retry_failed", False),
                        request_policy=policy,
                        seed_metrics=seeds.get((row["case_id"], row["trial"], repeat)),
                        reuse_directory=(
                            Path(options["reuse_from"]) / "metric-checkpoints"
                            if options.get("reuse_from")
                            else None
                        ),
                    )
                else:
                    metrics = judge_observation(
                        tasks[row["case_id"]], judge_input, config
                    )
                save_json(
                    journal,
                    {
                        "identity_hash": identity_hash,
                        "source_trial_sha256": digest(original),
                        "judge_repeat": repeat,
                        "metrics": metrics,
                    },
                )
            for index, metric in enumerate(metrics):
                metric = copy.deepcopy(metric)
                metric.update(
                    judge_repeat=repeat,
                    case_id=row["case_id"],
                    trial=row["trial"],
                    formal=False,
                )
                row["assessment"]["metrics"].append(metric)
                for call_index, call in enumerate(metric.get("events", [])):
                    event = copy.deepcopy(call)
                    event.update(
                        id="judge-" + digest([key, index, call_index])[:24],
                        parent_id=metric.get("event_id"),
                        type="generation",
                        name=f"Judge: {metric['name']}",
                        is_judge=True,
                        metric_name=metric["name"],
                        judge_repeat=repeat,
                    )
                    event.setdefault("end_time", event.get("start_time"))
                    call.update(event)
                    row["observation"]["events"].append(event)
        row["finished_at"] = now()
        print(
            json.dumps(
                {
                    "judge_case": row["case_id"],
                    "trial": row["trial"],
                    "judge_repeats": repeats,
                }
            ),
            flush=True,
        )
        return row

    canary = (
        next((r for r in rows if tasks[r["case_id"]].get("live", True)), None)
        if options.get("preflight")
        else None
    )
    import time

    judge_started = time.monotonic()
    try:
        first = annotate(canary) if canary is not None else None
        if policy.stopped.is_set():
            raise RuntimeError(
                "Judge preflight stopped the batch after a configuration error; "
                "inspect request-audit.json"
            )
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            completed = list(
                executor.map(annotate, [r for r in rows if r is not canary])
            )
        by_key = {(r["case_id"], r["trial"]): r for r in completed}
        if first is not None:
            by_key[(first["case_id"], first["trial"])] = first
        annotated = [by_key[(r["case_id"], r["trial"])] for r in rows]
    finally:
        if options:
            save_json(
                output_dir / "request-audit.json",
                {
                    "stopped": policy.stopped.is_set(),
                    "model_requests": policy.model_requests,
                    "failures": policy.attempts,
                },
            )
    result = copy.deepcopy(source)
    result.update(
        run_id=output_dir.name + "-judge-" + identity_hash[:8],
        identity=identity,
        identity_hash=identity_hash,
        planned_case_ids=selected,
        trials=annotated,
        provenance=provenance,
        finished_at=now(),
        judge_phase_seconds=time.monotonic() - judge_started,
        execution_identity=copy.deepcopy(
            source.get("execution_identity", source["identity"])
        ),
    )
    metrics = [
        m for r in annotated for m in r["assessment"]["metrics"] if "judge_repeat" in m
    ]
    result["judge_summary"] = summarize_judgments(metrics)
    # Prefix with the execution trial identity: event IDs can repeat across Agents.
    repeated = [
        [
            {
                **metric,
                "metric_id": digest(
                    [metric["case_id"], metric["trial"], metric["metric_id"]]
                ),
            }
            for metric in metrics
            if metric["judge_repeat"] == repeat
        ]
        for repeat in range(1, repeats + 1)
    ]
    result["judge_stability"] = summarize_repeated_judgments(repeated)
    calls = [call for metric in metrics for call in metric.get("events", [])]
    requests_unknown = any(
        metric.get("model_requests_unknown") is True for metric in metrics
    )
    result["judge_usage"] = {
        "model_requests": None if requests_unknown else len(calls),
        "model_requests_known_subtotal": len(calls),
        "model_requests_unknown": requests_unknown,
    }
    for field in ("input_tokens", "output_tokens", "cost_usd"):
        values = [call.get("usage", {}).get(field) for call in calls]
        known = [value for value in values if type(value) in (int, float)]
        result["judge_usage"][field] = (
            sum(known)
            if not requests_unknown and known and len(known) == len(values)
            else None
        )
        result["judge_usage"][field + "_known_subtotal"] = sum(known) if known else None
        result["judge_usage"][field + "_known_calls"] = len(known)
    result["summary"] = summarize(annotated, selected, source["trials_per_case"])
    known_judge_requests = sum(len(m.get("events", [])) for m in metrics)
    result["provenance"]["new_judge_model_requests"] = (
        None if requests_unknown else known_judge_requests
    )
    result["provenance"]["new_judge_model_requests_known_subtotal"] = (
        known_judge_requests
    )
    result["provenance"]["new_judge_model_requests_unknown"] = requests_unknown
    result["provenance"]["graded_at"] = now()
    if (source_dir / "results.json").read_bytes() != raw or code_identity(
        JUDGE_SOURCE_FILES
    ) != identity["judge_source"]:
        raise ValueError(
            "Source evidence or Judge implementation changed while judging"
        )
    if use_checkpoints:
        result["provenance"]["new_judge_model_requests"] = policy.model_requests
        result["provenance"]["new_judge_model_requests_known_subtotal"] = (
            policy.model_requests
        )
        result["provenance"]["new_judge_model_requests_unknown"] = False
        result["provenance"]["saved_scoring_requests"] = len(calls)
    if options and identity["judge_execution_sources"] != code_identity(
        JUDGE_EXECUTION_SOURCE_FILES
    ):
        raise ValueError("Judge execution implementation changed while judging")
    save_json(output_dir / "results.json", result)
    return result


def judge_run(
    source_dir: Path,
    dataset_path: Path,
    output_dir: Path,
    config: dict[str, Any],
    *,
    repeats: int = 1,
    concurrency: int = 2,
    limit: int | None = None,
    options: dict | None = None,
) -> dict[str, Any]:
    """Exclusively annotate one immutable source; checkpoints enable safe resume.

    A crashed process can leave .running behind. It must be inspected and removed
    explicitly after confirming no owner is active; never silently steal a lock.
    """
    source_dir, output_dir = Path(source_dir).resolve(), Path(output_dir).resolve()
    if output_dir == source_dir or output_dir.is_relative_to(source_dir):
        raise ValueError("Judge output must be outside the source run")
    output_dir.mkdir(parents=True, exist_ok=True)
    lock = output_dir / ".running"
    token = json.dumps({"pid": os.getpid(), "token": uuid4().hex, "started_at": now()})
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(
            "Judge output has a running owner (.running); inspect before resuming"
        ) from exc
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(token)
        return _judge_run_locked(
            source_dir,
            dataset_path,
            output_dir,
            config,
            repeats=repeats,
            concurrency=concurrency,
            limit=limit,
            options=options,
        )
    finally:
        if lock.exists() and lock.read_text() == token:
            lock.unlink()
