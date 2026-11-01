"""Replay saved benchmark results into Langfuse; never execute or re-score."""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import httpx
from langfuse.api import CreateScoreRequest, OtelResourceSpan, OtelScope, OtelScopeSpan

from ..observability import _span, client_from_env, destination_fingerprint, stable_id
from .runner import now, save_json
from .tasks import dataset_identity, load_tasks

VERSION = "file-benchmark-langfuse-v1"


def _connect_retry(method, **kwargs):
    """Only retry transport failures known to precede request delivery."""
    for attempt in range(3):
        try:
            return method(**kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if attempt == 2:
                raise
            time.sleep(0.5 * (2**attempt))


def item_id(dataset_id: str, case_id: str) -> str:
    return stable_id(VERSION, dataset_id, case_id)


def build_payload(run: dict, tasks: dict, dataset_id: str, source_hash: str):
    spans, scores, traces = [], [], []
    for row in run["trials"]:
        task = tasks[row["case_id"]]
        trace = stable_id(VERSION, run["run_id"], row["case_id"], str(row["trial"]))
        root = stable_id(trace, "root", length=16)
        experiment = stable_id(VERSION, run["run_id"], str(row["trial"]))
        observation = row["observation"]
        metadata = {
            "run_id": run["run_id"],
            "case_id": row["case_id"],
            "trial": row["trial"],
            "category": row["category"],
            "split": row["split"],
            "results_sha256": source_hash,
            "execution_backend": "inspect_ai",
            "formal_score_owner": "deepeval",
            "mode": run["mode"],
            "runtime_identity": observation.get("runtime_identity"),
            "evidence_complete": observation.get("evidence_complete"),
            "verdict": row["assessment"]["verdict"],
        }
        context = {
            "langfuse.experiment.id": experiment,
            "langfuse.experiment.name": (run["run_id"] + "-trial-" + str(row["trial"])),
            "langfuse.experiment.dataset.id": dataset_id,
            "langfuse.experiment.item.id": item_id(dataset_id, row["case_id"]),
            "langfuse.experiment.item.root_observation_id": root,
            "langfuse.environment": "benchmark",
            "langfuse.experiment.metadata.run_id": run["run_id"],
            "langfuse.experiment.metadata.results_sha256": source_hash,
        }
        attrs = {
            **context,
            "langfuse.observation.type": "agent",
            "langfuse.observation.metadata": {
                **metadata,
                "before_files": observation.get("before_files"),
                "final_files": observation.get("final_files"),
                "errors": observation.get("errors"),
                "assessment": row["assessment"],
            },
            "langfuse.observation.input": {
                "prompt": task["prompt"],
                "followups": task.get("followups", []),
            },
            "langfuse.observation.output": observation.get("turns"),
            "langfuse.experiment.item.expected_output": task["oracle"],
        }
        spans.append(
            _span(
                trace,
                root,
                row["case_id"],
                row["started_at"],
                row["finished_at"],
                attrs,
            )
        )
        ids = {
            event["id"]: stable_id(trace, event["id"], length=16)
            for event in observation.get("events", [])
        }
        for event in observation.get("events", []):
            if not event.get("end_time"):
                # Unfinished operations are points with explicit incomplete metadata.
                end = event["start_time"]
            else:
                end = event["end_time"]
            event_attrs = {
                **context,
                "langfuse.observation.type": event["type"]
                if event["type"] in ("generation", "tool")
                else "span",
                "langfuse.observation.input": event.get("input"),
                "langfuse.observation.output": event.get("output"),
                "langfuse.observation.metadata": {
                    "event_id": event["id"],
                    "error": event.get("error"),
                    "complete": bool(event.get("end_time"))
                    and not event.get("incomplete", False),
                    "case_id": row["case_id"],
                    **{
                        key: event[key]
                        for key in (
                            "response_model",
                            "tool_call_id",
                            "execution_started",
                        )
                        if key in event
                    },
                },
            }
            if event["type"] == "generation":
                event_attrs["langfuse.observation.model.name"] = event.get(
                    "model"
                ) or observation.get("runtime_identity", {}).get("model", "unknown")
                event_attrs["langfuse.observation.metadata"]["requested_model"] = (
                    event_attrs["langfuse.observation.model.name"]
                )
                usage = event.get("usage") or {}
                event_attrs["langfuse.observation.usage_details"] = {
                    k: v
                    for k, v in {
                        "input": usage.get("input_tokens", usage.get("prompt_tokens")),
                        "output": usage.get(
                            "output_tokens", usage.get("completion_tokens")
                        ),
                        "total": usage.get("total_tokens"),
                    }.items()
                    if v is not None
                }
            if event.get("error"):
                event_attrs["langfuse.observation.level"] = "ERROR"
                event_attrs["langfuse.observation.status_message"] = str(event["error"])
            spans.append(
                _span(
                    trace,
                    ids[event["id"]],
                    event["name"],
                    event["start_time"],
                    end,
                    event_attrs,
                    ids.get(event.get("parent_id"), root),
                )
            )
        entries = [("verdict", row["assessment"]["verdict"], "CATEGORICAL", {})]
        entries += [
            (metric["name"], metric["score"], "NUMERIC", metric)
            for metric in row["assessment"]["metrics"]
            if metric.get("score") is not None
        ]
        for name, value, dtype, metric in entries:
            scores.append(
                CreateScoreRequest(
                    id=stable_id(trace, name),
                    trace_id=trace,
                    observation_id=root,
                    name=name,
                    value=value,
                    data_type=dtype,
                    timestamp=datetime.fromisoformat(
                        row["finished_at"].replace("Z", "+00:00")
                    ),
                    metadata={**metadata, "metric": metric},
                    comment=metric.get("reason"),
                )
            )
        traces.append(
            {
                "case_id": row["case_id"],
                "trial": row["trial"],
                "trace_id": trace,
                "root_id": root,
                "experiment_id": experiment,
                "observation_ids": [root, *ids.values()],
                "score_ids": [s.id for s in scores if s.trace_id == trace],
            }
        )
    return spans, scores, traces


def _source(run_dir: Path, dataset_path: Path):
    raw = (run_dir / "results.json").read_bytes()
    run = json.loads(raw)
    if run["identity"]["dataset"] != dataset_identity(dataset_path):
        raise ValueError("export dataset does not match run identity")
    return (
        run,
        {t["id"]: t for t in load_tasks(dataset_path)},
        hashlib.sha256(raw).hexdigest(),
    )


def export_run(run_dir: Path, dataset_path: Path, *, client=None) -> dict:
    run_dir = Path(run_dir)
    run, tasks, source_hash = _source(run_dir, dataset_path)
    client = client or client_from_env()
    receipt_path = run_dir / "langfuse_export.json"
    destination = destination_fingerprint()
    receipt = (
        json.loads(receipt_path.read_text())
        if receipt_path.exists()
        else {
            "version": VERSION,
            "source_hash": source_hash,
            "destination": destination,
            "status": "PENDING",
            "accepted_observation_ids": [],
            "accepted_score_ids": [],
            "inflight": [],
        }
    )
    if receipt["source_hash"] != source_hash or receipt["destination"] != destination:
        raise ValueError("immutable export source/destination changed")
    if receipt["inflight"]:
        raise ValueError(
            "uncertain observation batch: reconcile remote IDs before retry; "
            "do not duplicate observations"
        )
    if receipt["status"] in ("ACCEPTED", "VERIFIED"):
        return receipt
    name = (
        "file-tools-v1-"
        + hashlib.sha256(
            json.dumps(run["identity"]["dataset"], sort_keys=True).encode()
        ).hexdigest()[:12]
    )
    if "dataset_id" not in receipt:
        dataset = client.datasets.create(
            name=name,
            description=(
                "Frozen file-tool benchmark; AI-assisted synthetic fixtures; "
                "DeepEval scoring."
            ),
            metadata=run["identity"]["dataset"],
        )
        receipt.update(dataset_id=dataset.id, dataset_name=name, registered_cases=[])
        save_json(receipt_path, receipt)
    dataset_id = receipt["dataset_id"]
    pending = [
        case
        for case in run["planned_case_ids"]
        if case not in receipt["registered_cases"]
    ]

    def register(case):
        task = tasks[case]
        _connect_retry(
            client.dataset_items.create,
            dataset_name=name,
            id=item_id(dataset_id, case),
            input={
                "prompt": task["prompt"],
                "followups": task.get("followups", []),
                "fixtures": task["fixtures"],
            },
            expected_output=task["oracle"],
            metadata={
                "case_id": case,
                "family": task["family"],
                "split": task["split"],
                "category": task["category"],
            },
        )
        return case

    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed(pool.submit(register, case) for case in pending):
            case = future.result()
            receipt["registered_cases"].append(case)
            save_json(receipt_path, receipt)
    spans, scores, traces = build_payload(run, tasks, dataset_id, source_hash)
    receipt["traces"] = traces
    accepted = set(receipt["accepted_observation_ids"])
    remaining = [s for s in spans if s.span_id not in accepted]
    for start in range(0, len(remaining), 75):
        batch = remaining[start : start + 75]
        receipt["inflight"] = [s.span_id for s in batch]
        save_json(receipt_path, receipt)
        try:
            response = _connect_retry(
                client.opentelemetry.export_traces,
                resource_spans=[
                    OtelResourceSpan(
                        scope_spans=[
                            OtelScopeSpan(
                                scope=OtelScope(name="agent-eval-suite-benchmark"),
                                spans=batch,
                            )
                        ]
                    )
                ],
                request_options={"max_retries": 0},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # A connection was never established, so no span was accepted.
            receipt["inflight"] = []
            save_json(receipt_path, receipt)
            raise
        partial = response.model_dump(by_alias=True).get("partialSuccess")
        if partial and (partial.get("rejectedSpans") or partial.get("errorMessage")):
            raise ValueError("Langfuse partial rejection; reconcile inflight batch")
        receipt["accepted_observation_ids"].extend(receipt["inflight"])
        receipt["inflight"] = []
        save_json(receipt_path, receipt)
    remaining_scores = [
        s for s in scores if s.id not in set(receipt["accepted_score_ids"])
    ]
    for start in range(0, len(remaining_scores), 100):
        batch = remaining_scores[start : start + 100]
        response = _connect_retry(
            client.scores.create, request=batch, request_options={"max_retries": 0}
        )
        if (
            getattr(response, "rejected", 0)
            or getattr(response, "errors", [])
            or getattr(response, "accepted", len(batch)) != len(batch)
        ):
            raise ValueError("Langfuse rejected scores")
        receipt["accepted_score_ids"].extend(s.id for s in batch)
        save_json(receipt_path, receipt)
    receipt["status"] = "ACCEPTED"
    receipt["accepted_at"] = now()
    receipt["counts"] = {
        "observations": len(spans),
        "scores": len(scores),
        "trials": len(traces),
    }
    save_json(receipt_path, receipt)
    return {
        k: v
        for k, v in receipt.items()
        if k
        not in (
            "traces",
            "accepted_observation_ids",
            "accepted_score_ids",
            "registered_cases",
        )
    }


def _paginate(method, *, page_size=100, **kwargs):
    rows, cursor = [], None
    seen = set()
    while True:
        for attempt in range(3):
            try:
                response = method(**kwargs, limit=page_size, cursor=cursor)
                break
            except httpx.TransportError:
                if attempt == 2:
                    raise
                time.sleep(0.5 * (2**attempt))
        body = response.model_dump()
        rows.extend(body["data"])
        cursor = body.get("meta", {}).get("cursor") or body.get("meta", {}).get(
            "next_cursor"
        )
        if not cursor:
            return rows
        if cursor in seen:
            raise ValueError("Remote pagination repeated a cursor")
        seen.add(cursor)


def verify_run(run_dir: Path, dataset_path: Path, *, client=None) -> dict:
    run_dir = Path(run_dir)
    run, tasks, source_hash = _source(run_dir, dataset_path)
    receipt_path = run_dir / "langfuse_export.json"
    receipt = json.loads(receipt_path.read_text())
    if (
        receipt["source_hash"] != source_hash
        or receipt["destination"] != destination_fingerprint()
    ):
        raise ValueError("verification identity changed")
    client = client or client_from_env()
    spans, scores, traces = build_payload(
        run, tasks, receipt["dataset_id"], source_hash
    )
    expected_scores = {s.id: s for s in scores}
    expected_spans = {s.span_id: s for s in spans}
    since = datetime.fromisoformat(run["started_at"])
    until = datetime.fromisoformat(run["finished_at"])
    observation_rows = _paginate(
        client.observations.get_many,
        page_size=1000,
        from_start_time=since,
        to_start_time=until,
        environment="benchmark",
        fields="core,basic,io,metadata,model,usage",
    )
    score_rows = _paginate(
        client.scores.get_many,
        page_size=100,
        from_timestamp=since,
        to_timestamp=until,
        fields="subject,details",
    )
    observations_by_trace, scores_by_trace = defaultdict(list), defaultdict(list)
    for record in observation_rows:
        observations_by_trace[record["trace_id"]].append(record)
    for record in score_rows:
        subject = record.get("subject") or {}
        trace_id = (
            subject.get("trace_id")
            if subject.get("kind") == "observation"
            else subject.get("id")
            if subject.get("kind") == "trace"
            else None
        )
        if trace_id:
            scores_by_trace[trace_id].append(record)

    def verify(trace):
        observations = observations_by_trace[trace["trace_id"]]
        by_id = {r["id"]: r for r in observations}
        errors = []
        if set(by_id) != set(trace["observation_ids"]):
            errors.append("observation_ids_mismatch")
        for identity in set(by_id) & set(trace["observation_ids"]):
            actual = by_id[identity]
            expected = expected_spans[identity]
            attrs = {a.key: a.value.string_value for a in expected.attributes}
            expected_metadata = json.loads(
                attrs.get("langfuse.observation.metadata", "{}")
            )
            for field in (
                "requested_model",
                "response_model",
                "tool_call_id",
                "execution_started",
            ):
                if (
                    field in expected_metadata
                    and (actual.get("metadata") or {}).get(field)
                    != expected_metadata[field]
                ):
                    errors.append(identity + ":metadata_" + field + "_mismatch")
            if actual.get("parent_observation_id") != expected.parent_span_id:
                errors.append(identity + ":parent_mismatch")
            if actual.get("type", "").lower() != attrs["langfuse.observation.type"]:
                errors.append(identity + ":type_mismatch")
            for field, expected_ns in (
                ("start_time", expected.start_time_unix_nano),
                ("end_time", expected.end_time_unix_nano),
            ):
                timestamp = actual.get(field)
                # The remote API stores millisecond timestamps.
                if (
                    timestamp is None
                    or abs(timestamp.timestamp() * 1e9 - int(expected_ns)) >= 1_000_000
                ):
                    errors.append(identity + ":" + field + "_mismatch")
            if attrs["langfuse.observation.type"] == "generation":
                if actual.get("model") != attrs["langfuse.observation.model.name"]:
                    errors.append(identity + ":model_mismatch")
                expected_usage = json.loads(attrs["langfuse.observation.usage_details"])
                if any(
                    (actual.get("usage_details") or {}).get(k) != v
                    for k, v in expected_usage.items()
                ):
                    errors.append(identity + ":usage_mismatch")
            for field in ("input", "output"):
                value = attrs.get("langfuse.observation." + field)
                try:
                    value = json.loads(value)
                except (ValueError, TypeError):
                    pass
                actual_value = actual.get(field)
                if isinstance(actual_value, str):
                    try:
                        actual_value = json.loads(actual_value)
                    except ValueError:
                        pass
                if actual_value != value:
                    errors.append(identity + ":" + field + "_mismatch")
        remote_scores = scores_by_trace[trace["trace_id"]]
        found = {s["id"]: s for s in remote_scores}
        for identity in trace["score_ids"]:
            if identity not in found:
                errors.append("missing_score:" + identity)
            else:
                actual = found[identity]
                value = actual.get("value", actual.get("string_value"))
                if value != expected_scores[identity].value:
                    errors.append("score_mismatch:" + identity)
                if (actual.get("subject") or {}).get("id") != (
                    expected_scores[identity].observation_id
                ):
                    errors.append("score_observation_mismatch:" + identity)
        return {
            "case_id": trace["case_id"],
            "trial": trace["trial"],
            "observations": len(observations),
            "scores": len(remote_scores),
            "errors": errors,
        }

    with ThreadPoolExecutor(max_workers=6) as pool:
        checks = list(pool.map(verify, traces))
    since = datetime.fromisoformat(run["started_at"])
    experiment_checks = []
    for identity in sorted({t["experiment_id"] for t in traces}):
        items = _paginate(
            client.experiments.list_items, from_start_time=since, experiment_id=identity
        )
        experiment_checks.append(
            {
                "experiment_id": identity,
                "items": len(items),
                "expected": sum(t["experiment_id"] == identity for t in traces),
            }
        )
    passed = all(not c["errors"] for c in checks) and all(
        c["items"] == c["expected"] for c in experiment_checks
    )
    result = {
        "status": "VERIFIED" if passed else "MISMATCH",
        "verified_at": now(),
        "source_hash": source_hash,
        "trial_checks": checks,
        "experiments": experiment_checks,
        "scope": (
            "Remote API read-back: identity, IO, type, parent, timestamps, model, "
            "usage, scores and experiment counts. UI verification is separate."
        ),
    }
    save_json(run_dir / "langfuse_verification.json", result)
    if passed:
        receipt["status"] = "VERIFIED"
        save_json(receipt_path, receipt)
    return {
        "status": result["status"],
        "trials": len(checks),
        "failed_checks": [c for c in checks if c["errors"]],
        "experiments": experiment_checks,
    }
