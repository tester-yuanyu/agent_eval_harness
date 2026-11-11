"""按评分项保存GEval进度，复用既有评分算法；不同重复实验不共用结果。"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
from pathlib import Path

from .request_policy import RequestPolicy
from .runner import digest, save_json
from .scorers.trajectory_judge import GEVAL_DIMENSIONS, _candidates, judge_observation


class JudgeBudgetExceeded(RuntimeError):
    pass


class CaseBudget:
    def __init__(self, policy, maximum):
        self.policy, self.remaining, self.lock = policy, maximum, threading.Lock()

    def call(self, request):
        def bounded():
            with self.lock:
                if self.remaining <= 0:
                    raise JudgeBudgetExceeded("Case model request budget exhausted")
                self.remaining -= 1
            self.policy.record_model_request()
            return request()

        return self.policy.call(bounded)


def judge_with_checkpoints(
    task,
    observation,
    config,
    directory: Path,
    *,
    repeat_identity,
    concurrency=1,
    retry_failed=False,
    request_policy=None,
    seed_metrics=None,
    reuse_directory: Path | None = None,
):
    if type(concurrency) is not int or not 1 <= concurrency <= 8:
        raise ValueError("metric concurrency must be 1–8")
    dimensions = config.get("dimensions", list(GEVAL_DIMENSIONS))
    if set(dimensions) - set(GEVAL_DIMENSIONS):
        raise ValueError("Metric checkpoints support GEval dimensions only")
    maximum = config.get("max_evaluations", 16)
    if type(maximum) is not int or maximum < 0:
        raise ValueError("max_evaluations must be a nonnegative integer")
    candidates = _candidates(task, observation, dimensions)
    public_config = {k: v for k, v in config.items() if k != "api_key"}
    sources = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [
            Path(__file__),
            Path(__file__).parent / "scorers/trajectory_judge.py",
            Path(__file__).parent / "scorers/judge_client.py",
        ]
    }
    policy = request_policy or RequestPolicy(retries=0)
    budget = CaseBudget(policy, maximum)
    # Request budgets also apply when resuming a partially completed case.
    prepared = []
    seeds = {m["metric_id"]: copy.deepcopy(m) for m in (seed_metrics or [])}
    if len(seeds) != len(seed_metrics or []) or set(seeds) - {
        r["metric_id"] for r, _ in candidates
    }:
        raise ValueError("Duplicate or unknown seed metrics")
    for record, evidence in candidates:
        identity = digest(
            {
                "record": record,
                "evidence": evidence,
                "config": public_config,
                "repeat": repeat_identity,
                "sources": sources,
                "deepeval": version("deepeval"),
            }
        )
        path = Path(directory) / f"{identity}.json"
        saved = seeds.get(record["metric_id"])
        if saved is not None:
            for field in ("name", "version", "rubric_sha256", "library_version"):
                if saved.get(field) != record.get(field):
                    raise ValueError("Seed metric scoring contract changed: " + field)
            if saved.get("model") not in (None, config.get("model")):
                raise ValueError("Seed metric model changed")
        checkpoint = path
        if not checkpoint.exists() and reuse_directory is not None:
            checkpoint = Path(reuse_directory) / path.name
        if checkpoint.exists():
            envelope = json.loads(checkpoint.read_text())
            if envelope.get("input_hash") != identity or envelope.get(
                "record_hash"
            ) != digest(envelope.get("record")):
                raise ValueError("Invalid metric checkpoint identity/content")
            saved = envelope["record"]
            if saved.get("metric_id") != record["metric_id"]:
                raise ValueError("Metric checkpoint belongs to another candidate")
        prepared.append((record, evidence, identity, path, saved))
    if not retry_failed:
        budget.remaining = max(
            0,
            maximum
            - sum(len(saved.get("events", [])) for *_, saved in prepared if saved),
        )

    def score(item):
        record, evidence, identity, path, saved = item
        retryable = (
            saved
            and saved.get("status") == "ERROR"
            and any(
                e.get("failure_kind") in {"transient", "rate_limit"}
                or e.get("error") in {"APIConnectionError", "APITimeoutError"}
                for e in saved.get("events", [])
            )
        )
        if saved is not None and not (retry_failed and retryable):
            return saved
        if evidence is None:
            result = copy.deepcopy(record)
        else:
            result = judge_observation(
                task,
                observation,
                config,
                dimensions=dimensions,
                metric_ids={record["metric_id"]},
                request_policy=budget,
            )[0]
        if saved is not None:
            archive = path.with_name(
                path.stem + ".attempt-" + digest(saved)[:12] + ".json"
            )
            if not archive.exists():
                save_json(
                    archive,
                    {
                        "input_hash": identity,
                        "record_hash": digest(saved),
                        "record": saved,
                    },
                )
            result["prior_attempts"] = [
                *saved.get("prior_attempts", []),
                {"record_hash": digest(saved), "path": archive.name},
            ]
            result["events"] = [*saved.get("events", []), *result.get("events", [])]
            result["model_requests"] = result["model_requests_known_subtotal"] = len(
                result["events"]
            )
        save_json(
            path,
            {"input_hash": identity, "record_hash": digest(result), "record": result},
        )
        return result

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(score, prepared))
