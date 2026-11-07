"""Replay saved benchmark results into Langfuse; never execute or re-score."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx
from langfuse.api import CreateScoreRequest, OtelResourceSpan, OtelScope, OtelScopeSpan

from ..observability import _span, client_from_env, destination_fingerprint, stable_id
from .runner import digest, now, save_json
from .tasks import dataset_identity, load_tasks

VERSION = "file-benchmark-langfuse-v1"
EVIDENCE_VERSION_V1 = "langfuse-exact-metadata-v1"
EVIDENCE_VERSION_V2 = "langfuse-exact-metadata-v2"
EVIDENCE_VERSION = "langfuse-exact-metadata-v3"
EVIDENCE_VERSIONS = frozenset(
    (EVIDENCE_VERSION_V1, EVIDENCE_VERSION_V2, EVIDENCE_VERSION)
)
EVIDENCE_RECEIPT = "langfuse_exact_metadata_export.json"
EVIDENCE_TARGET_PREFIX = "observation:"
EVIDENCE_FIELDS = (
    "exact_metadata_base64",
    "exact_metadata_sha256",
    "evidence_source_sha256",
    "evidence_for_observation_id",
    "evidence_export_version",
    "is_export_evidence",
)
VERIFIED_METADATA_FIELDS = (
    "requested_model",
    "response_model",
    "tool_call_id",
    "execution_started",
    "before_files",
    "after_files",
    "before_snapshot_errors",
    "after_snapshot_errors",
    "snapshot",
    "snapshot_timing",
    "tool_schema",
    "normalized_input",
    "is_error",
    "tool_error",
    "is_judge",
    "judge_repeat",
    "metric_id",
    "turn",
) + EVIDENCE_FIELDS

# DeepEval's native StepEfficiencyMetric evaluates the complete saved trace.
# Keep this an exact contract allowlist: other chain metrics still identify the
# child observation they score, and a missing event ID remains invalid.
_ROOT_CHAIN_METRIC_IDENTITIES = {
    (
        "deepeval",
        "StepEfficiencyMetric",
        "step_efficiency",
        "trajectory-native-v1",
    )
}


def _is_root_chain_metric(metric: dict) -> bool:
    return (
        metric.get("scope") == "chain"
        and (
            metric.get("backend"),
            metric.get("implementation"),
            metric.get("name"),
            metric.get("version"),
        )
        in _ROOT_CHAIN_METRIC_IDENTITIES
    )


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


def build_payload(
    run: dict, tasks: dict, dataset_id: str, source_hash: str, *, presentation=None
):
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
            "evaluation_level": task.get("evaluation_level", "e2e"),
            "execution_mode": task.get("execution_mode", "agent"),
            "results_sha256": source_hash,
            "execution_backend": "inspect_ai",
            "formal_score_owner": "deepeval",
            "mode": run["mode"],
            "runtime_identity": observation.get("runtime_identity"),
            "evidence_complete": observation.get("evidence_complete"),
            "verdict": row["assessment"]["verdict"],
        }
        if run["mode"] == "real_agent_official_tau":
            metadata.update(
                official_task_id=row["official_task_id"],
                official_reward_owner=run["official_reward_owner"],
                official_summary_sha256=run["official_summary_sha256"],
                official_summary_path=run["official_summary_path"],
                official_observation_path=row.get("official_observation_path"),
                official_result_path=row.get("official_result_path"),
                official_leaderboard_result=False,
                synthetic_presentation_descriptor_only=True,
            )
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
        events = observation.get("events", [])
        event_names = [event.get("id") for event in events]
        if any(not isinstance(value, str) or not value for value in event_names):
            raise ValueError("export event IDs must be nonempty strings")
        if len(set(event_names)) != len(event_names):
            raise ValueError("duplicate event IDs cannot be exported")
        for event in events:
            parent = event.get("parent_id")
            if parent is not None and parent not in event_names:
                raise ValueError(f"unknown event parent: {parent}")
        parents = {event["id"]: event.get("parent_id") for event in events}
        for event in events:
            seen = {event["id"]}
            parent = event.get("parent_id")
            while parent is not None:
                if parent in seen:
                    raise ValueError("event parent cycle cannot be exported")
                seen.add(parent)
                parent = parents[parent]
        ids = {
            event["id"]: stable_id(trace, event["id"], length=16) for event in events
        }
        for event in events:
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
                            "before_files",
                            "after_files",
                            "before_snapshot_errors",
                            "after_snapshot_errors",
                            "snapshot",
                            "snapshot_timing",
                            "tool_schema",
                            "normalized_input",
                            "is_error",
                            "tool_error",
                            "is_judge",
                            "judge_repeat",
                            "metric_id",
                            "turn",
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
                        "cache_read_input_tokens": usage.get("input_tokens_cache_read"),
                        "cache_creation_input_tokens": usage.get(
                            "input_tokens_cache_write"
                        ),
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
        # Validate links even for unscored metrics. Missing evidence is retained
        # in assessment metadata, never silently exported as a numeric zero.
        metrics = row["assessment"]["metrics"]
        for metric in metrics:
            scope = metric.get("scope", "task")
            event_id = metric.get("event_id")
            if scope not in {"task", "tool", "turn", "chain", "generation", "event"}:
                raise ValueError(f"unsupported metric scope: {scope}")
            if event_id is not None and event_id not in ids:
                raise ValueError(f"metric references unknown event: {event_id}")
            if (
                scope != "task"
                and event_id is None
                and not _is_root_chain_metric(metric)
            ):
                raise ValueError(f"{scope} metric requires an event ID")
            if scope == "task" and event_id is not None:
                raise ValueError("task metric cannot reference a child event")
        entries = [("verdict", row["assessment"]["verdict"], "CATEGORICAL", {})]
        entries += [
            (metric["name"], metric["score"], "NUMERIC", metric)
            for metric in metrics
            if metric.get("score") is not None
        ]
        score_ids = set()
        for name, value, dtype, metric in entries:
            # Preserve immutable v1 identities. Scoped metrics need the target
            # node and repeat in their IDs so repeated names never overwrite.
            if "scope" in metric:
                score_id = stable_id(
                    trace,
                    name,
                    metric["scope"],
                    metric.get("event_id") or "root",
                    str(metric.get("version", "")),
                    str(metric.get("metric_id", "")),
                    str(metric.get("judge_repeat", "")),
                )
            else:
                score_id = stable_id(trace, name)
            if score_id in score_ids:
                raise ValueError(f"duplicate score identity: {name}")
            score_ids.add(score_id)
            scores.append(
                CreateScoreRequest(
                    id=score_id,
                    trace_id=trace,
                    observation_id=ids.get(metric.get("event_id"), root),
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
    if presentation is not None:
        if presentation.get("source_hash") != source_hash:
            raise ValueError("presentation source mismatch")
        from .langfuse_presentation import enrich_spans

        spans = enrich_spans(spans, run, presentation, traces)
    return spans, scores, traces


def _source(run_dir: Path, dataset_path: Path):
    raw = (run_dir / "results.json").read_bytes()
    run = json.loads(raw)
    if run.get("mode") == "real_agent_official_tau":
        summary_raw = Path(dataset_path).read_bytes()
        summary_hash = hashlib.sha256(summary_raw).hexdigest()
        identity = run["identity"]
        if summary_hash != identity.get(
            "official_summary_sha256"
        ) or summary_hash != run.get("official_summary_sha256"):
            raise ValueError("Official summary SHA256 does not match run identity")
        if digest(identity) != run.get("identity_hash"):
            raise ValueError("Official task selection identity hash changed")
        summary = json.loads(summary_raw)
        selected = summary.get("task_ids", [])
        cases = ["tau-retail-v1.0.1/" + task_id for task_id in selected]
        tasks = run.get("task_descriptors", {})
        if (
            summary.get("domain") != "retail"
            or not selected
            or len(set(selected)) != len(selected)
            or identity["config"]["task_ids"] != selected
            or identity.get("case_ids") != cases
            or run.get("planned_case_ids") != cases
            or set(tasks) != set(cases)
        ):
            raise ValueError("Official task selection or descriptors do not match")
        for key in ("source_identity", "task_sha256", "policy_sha256"):
            if identity["dataset"].get(key) != summary.get(key):
                raise ValueError("Official dataset provenance does not match summary")
        for case, task_id in zip(cases, selected, strict=True):
            task = tasks[case]
            if (
                task.get("id") != case
                or task.get("official_task_id") != task_id
                or task.get("synthetic_presentation_descriptor_only") is not True
            ):
                raise ValueError("Official task descriptor does not match selection")
        if any(
            row["case_id"] not in tasks
            or row.get("official_task_id") != tasks[row["case_id"]]["official_task_id"]
            for row in run["trials"]
        ):
            raise ValueError("Official trial task ID does not match descriptor")
        return run, tasks, hashlib.sha256(raw).hexdigest()
    identify, load = dataset_identity, load_tasks
    if run["identity"]["dataset"].get("task_contract") == "provider-tasks-v1":
        from .provider_tasks import load_provider_tasks, provider_dataset_identity

        identify, load = provider_dataset_identity, load_provider_tasks
    if run["identity"]["dataset"] != identify(dataset_path):
        raise ValueError("export dataset does not match run identity")
    return (
        run,
        {t["id"]: t for t in load(dataset_path)},
        hashlib.sha256(raw).hexdigest(),
    )


def export_run(run_dir: Path, dataset_path: Path, *, client=None) -> dict:
    run_dir = Path(run_dir)
    run, tasks, source_hash = _source(run_dir, dataset_path)
    client = client or client_from_env()
    receipt_path = run_dir / "langfuse_export.json"
    first_export = not receipt_path.exists()
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
    if first_export:
        from .report_diagnostics import write_diagnostics

        receipt["presentation"] = json.loads(write_diagnostics(run_dir).read_text())
        save_json(receipt_path, receipt)
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
        run["identity"]["dataset"].get("dataset_id", "file-tools-v1")
        + "-"
        + hashlib.sha256(
            json.dumps(run["identity"]["dataset"], sort_keys=True).encode()
        ).hexdigest()[:12]
    )
    if "dataset_id" not in receipt:
        dataset = client.datasets.create(
            name=name,
            description=(
                "Selected official τ retail tasks; official reward preserved by "
                "DeepEval; Inspect orchestration; not an official leaderboard result."
                if run["mode"] == "real_agent_official_tau"
                else run["identity"]["dataset"].get(
                    "description",
                    "Frozen benchmark; AI-assisted synthetic fixtures; "
                    "DeepEval scoring.",
                )
            ),
            metadata=run["identity"]["dataset"],
            request_options={"max_retries": 0},
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
        official = run["mode"] == "real_agent_official_tau"
        metadata = {
            "case_id": case,
            "family": task["family"],
            "split": task["split"],
            "category": task["category"],
        }
        if official:
            metadata.update(
                official_task_id=task["official_task_id"],
                official_summary_sha256=run["official_summary_sha256"],
                source_identity=run["identity"]["dataset"]["source_identity"],
                task_sha256=run["identity"]["dataset"]["task_sha256"].get(
                    task["official_task_id"]
                ),
                policy_sha256=run["identity"]["dataset"]["policy_sha256"],
                synthetic_presentation_descriptor_only=True,
                environment_state_owner="official_tau",
            )
        _connect_retry(
            client.dataset_items.create,
            dataset_name=name,
            id=item_id(dataset_id, case),
            input={
                "prompt": task["prompt"],
                "followups": task.get("followups", []),
                "fixtures": {} if official else task["fixtures"],
            },
            expected_output=task["oracle"],
            metadata=metadata,
            request_options={"max_retries": 0},
        )
        return case

    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed(pool.submit(register, case) for case in pending):
            case = future.result()
            receipt["registered_cases"].append(case)
            save_json(receipt_path, receipt)
    spans, scores, traces = build_payload(
        run, tasks, dataset_id, source_hash, presentation=receipt.get("presentation")
    )
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


def _flatten_metadata(metadata: dict) -> dict:
    """Match the API's dotted leaf keys without splitting literal filename dots."""
    leaves = {}

    def visit(value, path):
        if isinstance(value, dict) and value:
            for key, child in value.items():
                visit(child, path + "." + key if path else key)
        else:
            if path in leaves:
                raise ValueError("Metadata has ambiguous flattened paths: " + path)
            leaves[path] = value

    for key, value in metadata.items():
        visit(value, key)
    return leaves


def _metadata_with_json_values(value):
    """Model the API's lossy JSON parsing; never sufficient evidence by itself."""
    if isinstance(value, str):
        try:
            return _metadata_with_json_values(json.loads(value))
        except ValueError:
            return value
    if isinstance(value, dict):
        return {key: _metadata_with_json_values(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_metadata_with_json_values(child) for child in value]
    return value


def _contains_json_string(value):
    if isinstance(value, str):
        try:
            json.loads(value)
            return True
        except ValueError:
            return False
    if isinstance(value, dict):
        return any(_contains_json_string(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_json_string(child) for child in value)
    return False


def _contains_empty_object(value):
    if isinstance(value, dict):
        return not value or any(_contains_empty_object(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_empty_object(v) for v in value)
    return False


def _empty_object_projection_matches(expected: dict, actual: dict, field: str) -> bool:
    """API omits empty object leaves; call ONLY with separately verified exact proof."""
    wanted = {
        k: v
        for k, v in _flatten_metadata({field: expected[field]}).items()
        if not (isinstance(v, dict) and not v)
    }
    observed = {
        k: v
        for k, v in _flatten_metadata(actual).items()
        if k == field or k.startswith(field + ".")
    }
    return _json_equal(wanted, observed)


def _evidence_target_id(span_id: str, version: str) -> str:
    if version == EVIDENCE_VERSION_V1:
        return span_id
    if version in {EVIDENCE_VERSION_V2, EVIDENCE_VERSION}:
        return EVIDENCE_TARGET_PREFIX + span_id
    raise ValueError(f"Unsupported supplemental evidence version: {version!r}")


def _evidence_source_id(source_hash: str, version: str) -> str:
    if version == EVIDENCE_VERSION_V1:
        return source_hash
    if version in {EVIDENCE_VERSION_V2, EVIDENCE_VERSION}:
        return "sha256:" + source_hash
    raise ValueError(f"Unsupported supplemental evidence version: {version!r}")


def build_evidence_payload(spans, source_hash, *, version=EVIDENCE_VERSION):
    """Lossless presentation-only children for fields the API parses as JSON.

    Original execution spans and results remain unchanged. These children record
    saved metadata, never Agent operations, Judge calls, scores, or new trials.
    """
    if version not in EVIDENCE_VERSIONS:
        raise ValueError(f"Unsupported supplemental evidence version: {version!r}")
    evidence = []
    for span in spans:
        attrs = {a.key: a.value.string_value for a in span.attributes}
        metadata = json.loads(attrs.get("langfuse.observation.metadata", "{}"))
        affected = {
            key: metadata[key]
            for key in VERIFIED_METADATA_FIELDS
            if key in metadata
            and (
                _contains_json_string(metadata[key])
                or (
                    version == EVIDENCE_VERSION
                    and _contains_empty_object(metadata[key])
                )
            )
        }
        if not affected:
            continue
        raw = json.dumps(
            affected, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        target_id = _evidence_target_id(span.span_id, version)
        proof = _span(
            span.trace_id,
            stable_id(version, source_hash, span.span_id, length=16),
            "saved-exact-metadata",
            "1970-01-01T00:00:00Z",
            "1970-01-01T00:00:00Z",
            {
                "langfuse.environment": "benchmark",
                "langfuse.observation.type": "span",
                "langfuse.observation.metadata": {
                    "evidence_export_version": version,
                    "evidence_source_sha256": _evidence_source_id(source_hash, version),
                    "evidence_for_observation_id": target_id,
                    "is_export_evidence": True,
                    "exact_metadata_base64": "base64:"
                    + base64.b64encode(raw).decode("ascii"),
                    "exact_metadata_sha256": "sha256:"
                    + hashlib.sha256(raw).hexdigest(),
                },
            },
            span.span_id,
        ).model_copy(
            update={
                "start_time_unix_nano": span.start_time_unix_nano,
                "end_time_unix_nano": span.end_time_unix_nano,
            }
        )
        evidence.append(proof)
    return evidence


def export_metadata_evidence(run_dir: Path, dataset_path: Path, *, client=None):
    """Append separately receipted lossless evidence, without replaying old spans."""
    run_dir = Path(run_dir)
    run, tasks, source_hash = _source(run_dir, dataset_path)
    original = json.loads((run_dir / "langfuse_export.json").read_text())
    destination = destination_fingerprint()
    if (
        original["source_hash"] != source_hash
        or original["destination"] != destination
        or original["status"] not in ("ACCEPTED", "VERIFIED")
    ):
        raise ValueError("Original export must be accepted with matching identity")
    path = run_dir / EVIDENCE_RECEIPT
    receipt = json.loads(path.read_text()) if path.exists() else None
    evidence_version = (
        receipt.get("version") if receipt is not None else EVIDENCE_VERSION
    )
    if evidence_version not in EVIDENCE_VERSIONS:
        raise ValueError(
            f"Unsupported supplemental evidence version: {evidence_version!r}"
        )
    spans, _, _ = build_payload(
        run,
        tasks,
        original["dataset_id"],
        source_hash,
        presentation=original.get("presentation"),
    )
    evidence = build_evidence_payload(spans, source_hash, version=evidence_version)
    identity = {
        "version": evidence_version,
        "source_hash": source_hash,
        "destination": destination,
        "dataset_id": original["dataset_id"],
        "evidence_observation_ids": [span.span_id for span in evidence],
        "target_observation_ids": [span.parent_span_id for span in evidence],
    }
    receipt = (
        receipt
        if receipt is not None
        else {
            **identity,
            "status": "PENDING",
            "accepted_observation_ids": [],
            "inflight": [],
            "purpose": "Lossless saved metadata presentation; no execution or scoring",
        }
    )
    if any(receipt.get(key) != value for key, value in identity.items()):
        raise ValueError("Immutable supplemental evidence identity changed")
    if receipt["inflight"]:
        raise ValueError("Uncertain evidence batch: reconcile IDs before retry")
    if receipt["status"] in ("ACCEPTED", "VERIFIED"):
        return receipt
    client = client or client_from_env()
    accepted = set(receipt["accepted_observation_ids"])
    pending = [span for span in evidence if span.span_id not in accepted]
    for start in range(0, len(pending), 75):
        batch = pending[start : start + 75]
        receipt["inflight"] = [span.span_id for span in batch]
        save_json(path, receipt)
        try:
            response = _connect_retry(
                client.opentelemetry.export_traces,
                resource_spans=[
                    OtelResourceSpan(
                        scope_spans=[
                            OtelScopeSpan(
                                scope=OtelScope(name="agent-eval-suite-saved-evidence"),
                                spans=batch,
                            )
                        ]
                    )
                ],
                request_options={"max_retries": 0},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            receipt["inflight"] = []
            save_json(path, receipt)
            raise
        partial = response.model_dump(by_alias=True).get("partialSuccess")
        if partial and (partial.get("rejectedSpans") or partial.get("errorMessage")):
            raise ValueError("Langfuse partial evidence rejection; reconcile batch")
        receipt["accepted_observation_ids"].extend(receipt["inflight"])
        receipt["inflight"] = []
        save_json(path, receipt)
    receipt.update(status="ACCEPTED", accepted_at=now(), observations=len(evidence))
    save_json(path, receipt)
    return receipt


def _json_equal(expected, actual):
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and set(expected) == set(actual)
            and all(_json_equal(value, actual[key]) for key, value in expected.items())
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(
                _json_equal(left, right)
                for left, right in zip(expected, actual, strict=True)
            )
        )
    return isinstance(expected, bool) == isinstance(actual, bool) and expected == actual


def _metadata_matches(expected: dict, actual: dict, field: str) -> bool:
    expected_leaves = _flatten_metadata({field: expected[field]})
    actual_leaves = {
        key: value
        for key, value in _flatten_metadata(actual).items()
        if key == field or key.startswith(field + ".")
    }
    if set(expected_leaves) != set(actual_leaves):
        return False
    for key, value in expected_leaves.items():
        observed = actual_leaves[key]
        # Object arrays are exposed as JSON strings by the metadata API. Only
        # decode structured expected values: a file containing "null" is text.
        if isinstance(value, (list, dict)) and isinstance(observed, str):
            try:
                observed = json.loads(observed)
            except ValueError:
                return False
        # Langfuse's flattened metadata represents an explicit null as "".
        if value is None and observed == "":
            observed = None
        # This duplicate binding is also checked against the exact core parent
        # ID. The API parses all-decimal strings; accept only a reversible int
        # representation here, never floats or coercion of other metadata.
        if (
            field == "evidence_for_observation_id"
            and isinstance(value, str)
            and type(observed) is int
            and str(observed) == value
        ):
            observed = value
        if not _json_equal(value, observed):
            return False
    return True


def _expand_metadata(method, rows: list[dict], long_keys: dict, **kwargs):
    """Fetch exact long values; bound query size and never accept API previews."""
    chunks, current = [], []
    for key in sorted(long_keys):
        if "," in key or len(quote(key, safe="")) > 2500:
            raise ValueError("Metadata key cannot be expanded exactly: " + key)
        if current and len(quote(",".join([*current, key]), safe="")) > 2500:
            chunks.append(current)
            current = []
        current.append(key)
    if current:
        chunks.append(current)
    by_id = {row["id"]: row for row in rows}
    for keys in chunks:
        expanded = _paginate(
            method,
            page_size=1000,
            fields="core,metadata",
            expand_metadata=",".join(keys),
            **kwargs,
        )
        for row in expanded:
            if row["id"] not in by_id:
                continue
            original = by_id[row["id"]]
            metadata = _flatten_metadata(original.get("metadata") or {})
            full = _flatten_metadata(row.get("metadata") or {})
            for key in keys:
                metadata.pop(key, None)
            # Preserve prior expanded values, while retaining new unexpected
            # leaves so exact comparison still rejects added evidence.
            metadata.update(
                {
                    key: value
                    for key, value in full.items()
                    if key in keys
                    or key not in metadata
                    or any(key.startswith(parent + ".") for parent in keys)
                }
            )
            original["metadata"] = metadata


def _read_remote_evidence(client, spans, traces):
    """Read only this run's trace IDs, including every cursor page per batch."""
    by_trace = defaultdict(list)
    for span in spans:
        by_trace[span.trace_id].append(span)
    identities = list(dict.fromkeys(trace["trace_id"] for trace in traces))
    observation_rows, score_rows = [], []
    # IDs are stable 32-character hashes. Fifty keep the encoded trace filter
    # below 3 KB, including when full metadata keys need a second query.
    for start in range(0, len(identities), 50):
        selected = identities[start : start + 50]
        trace_filter = json.dumps(
            [
                {
                    "type": "stringOptions",
                    "column": "traceId",
                    "operator": "any of",
                    "value": selected,
                }
            ],
            separators=(",", ":"),
        )
        if len(quote(trace_filter, safe="")) > 3000:
            raise ValueError("Trace filter exceeds bounded readback query size")
        observations = _paginate(
            client.observations.get_many,
            page_size=1000,
            filter=trace_filter,
            fields="core,basic,io,metadata,model,usage",
        )
        long_keys = {}
        for identity in selected:
            for span in by_trace[identity]:
                attrs = {a.key: a.value.string_value for a in span.attributes}
                metadata = json.loads(attrs.get("langfuse.observation.metadata", "{}"))
                required = {
                    key: metadata[key]
                    for key in VERIFIED_METADATA_FIELDS
                    if key in metadata
                }
                for key, value in _flatten_metadata(required).items():
                    serialized = value if isinstance(value, str) else json.dumps(value)
                    if len(serialized) > 200:
                        long_keys[key] = True
        _expand_metadata(
            client.observations.get_many,
            observations,
            long_keys,
            filter=trace_filter,
        )
        observation_rows.extend(observations)
        score_rows.extend(
            _paginate(
                client.scores.get_many,
                page_size=100,
                trace_id=",".join(selected),
                # Numeric values are core fields. Scope validation needs the
                # subject, not another copy of prompts in score metadata.
                fields="subject",
            )
        )
    return observation_rows, score_rows


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
        run,
        tasks,
        receipt["dataset_id"],
        source_hash,
        presentation=receipt.get("presentation"),
    )
    evidence_path = run_dir / EVIDENCE_RECEIPT
    evidence_receipt = None
    evidence = []
    if evidence_path.exists():
        evidence_receipt = json.loads(evidence_path.read_text())
        evidence_version = evidence_receipt.get("version")
        if evidence_version not in EVIDENCE_VERSIONS:
            raise ValueError(
                f"Unsupported supplemental evidence version: {evidence_version!r}"
            )
        evidence = build_evidence_payload(spans, source_hash, version=evidence_version)
        ids = [span.span_id for span in evidence]
        if (
            evidence_receipt.get("source_hash") != source_hash
            or evidence_receipt.get("destination") != destination_fingerprint()
            or evidence_receipt.get("dataset_id") != receipt["dataset_id"]
            or evidence_receipt.get("status") not in ("ACCEPTED", "VERIFIED")
            or evidence_receipt.get("inflight")
            or evidence_receipt.get("evidence_observation_ids") != ids
            or evidence_receipt.get("target_observation_ids")
            != [span.parent_span_id for span in evidence]
            or set(evidence_receipt.get("accepted_observation_ids", [])) != set(ids)
        ):
            raise ValueError("Supplemental evidence receipt identity is invalid")
        for trace in traces:
            trace["observation_ids"].extend(
                span.span_id for span in evidence if span.trace_id == trace["trace_id"]
            )
        spans.extend(evidence)
    evidence_by_target = {span.parent_span_id: span for span in evidence}
    expected_scores = {s.id: s for s in scores}
    expected_spans = {s.span_id: s for s in spans}
    observation_rows, score_rows = _read_remote_evidence(client, spans, traces)
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
            proof = evidence_by_target.get(identity)
            proof_actual = by_id.get(proof.span_id) if proof is not None else None
            proof_valid = False
            if proof_actual is not None:
                proof_metadata = json.loads(
                    next(
                        a.value.string_value
                        for a in proof.attributes
                        if a.key == "langfuse.observation.metadata"
                    )
                )
                proof_valid = (
                    proof_actual.get("parent_observation_id") == identity
                    and proof_actual.get("type", "").lower() == "span"
                    and all(
                        _metadata_matches(
                            proof_metadata, proof_actual.get("metadata") or {}, field
                        )
                        for field in EVIDENCE_FIELDS
                    )
                )
            for field in VERIFIED_METADATA_FIELDS:
                if field in expected_metadata and not _metadata_matches(
                    expected_metadata, actual.get("metadata") or {}, field
                ):
                    # The original flattened value and the separately saved
                    # lossless bytes must BOTH agree. A missing or altered proof
                    # never authorizes semantic-only comparison.
                    restored = proof_valid and (
                        (
                            _contains_json_string(expected_metadata[field])
                            and _metadata_matches(
                                _metadata_with_json_values(expected_metadata),
                                actual.get("metadata") or {},
                                field,
                            )
                        )
                        or (
                            evidence_version == EVIDENCE_VERSION
                            and _contains_empty_object(expected_metadata[field])
                            and _empty_object_projection_matches(
                                expected_metadata,
                                actual.get("metadata") or {},
                                field,
                            )
                        )
                    )
                    if not restored:
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
    if evidence_receipt is not None:
        result["supplemental_evidence"] = {
            "version": evidence_receipt["version"],
            "source_hash": source_hash,
            "receipt_path": str(evidence_path),
            "observations": len(evidence),
            "status": "VERIFIED" if passed else "MISMATCH",
            "purpose": "Lossless saved metadata presentation; no new trials or calls",
        }
        if passed:
            evidence_receipt.update(status="VERIFIED", verified_at=now())
            save_json(evidence_path, evidence_receipt)
        result["supplemental_evidence"]["receipt_sha256"] = hashlib.sha256(
            evidence_path.read_bytes()
        ).hexdigest()
    save_json(run_dir / "langfuse_verification.json", result)
    if passed and evidence_receipt is None:
        receipt["status"] = "VERIFIED"
        save_json(receipt_path, receipt)
    return {
        "status": result["status"],
        "trials": len(checks),
        "failed_checks": [c for c in checks if c["errors"]],
        "experiments": experiment_checks,
    }
