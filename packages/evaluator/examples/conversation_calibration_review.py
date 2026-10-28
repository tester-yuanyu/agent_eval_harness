"""Explicit local Langfuse review handoff for immutable calibration results.

Observations upload once: a receipt is reserved before mutations. Interrupted
score upserts can resume; uncertain observations/queue changes need reconciliation.
No evaluation or human annotation is performed by this adapter.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from conversation_calibration import load_corpus, project_log
from inspect_ai.log import read_eval_log
from langfuse.api import (
    ConfigCategory,
    CreateScoreRequest,
    OtelResourceSpan,
    OtelScope,
    OtelScopeSpan,
    OtelSpan,
)
from langfuse.api.client import LangfuseAPI

from eval_framework.evidence import atomic_json
from eval_framework.local_delivery import _config
from eval_framework.observability import _span, stable_id

OPTIONS = {"max_retries": 0}


def verified_inputs(root: Path, corpus_path: Path) -> tuple[dict, dict]:
    projection = json.loads((root / "projection.json").read_text())
    native = Path(projection["native_log"])
    if (
        hashlib.sha256(native.read_bytes()).hexdigest()
        != projection["native_log_sha256"]
    ):
        raise ValueError("Modified native log")
    corpus = load_corpus(corpus_path)
    snapshot = json.loads((root / "corpus.snapshot.json").read_text())
    ids = {case["id"] for case in snapshot["cases"]}
    corpus["cases"] = [case for case in corpus["cases"] if case["id"] in ids]
    if corpus != snapshot:
        raise ValueError("Modified corpus snapshot")
    stored = project_log(read_eval_log(str(native)), corpus)
    if any(projection.get(k) != v for k, v in stored.items()):
        raise ValueError("Projection differs from native Inspect evidence")
    return corpus, projection


def review_material(
    corpus: dict[str, Any], projection: dict[str, Any]
) -> tuple[list[OtelSpan], list[CreateScoreRequest], list[dict[str, str]]]:
    spans, scores, bindings = [], [], []
    for case in corpus["cases"]:
        trace_id = stable_id("calibration-review-v1", projection["run_id"], case["id"])
        span_id = stable_id(trace_id, "dialogue", length=16)
        rows = [t for t in projection["trials"] if t["case_id"] == case["id"]]
        metadata = {
            "purpose": "synthetic_judge_calibration_only",
            "case_id": case["id"],
            "category": case["category"],
            "run_id": projection["run_id"],
            "corpus_sha256": corpus["source_sha256"],
            "native_log_sha256": projection["native_log_sha256"],
            "reference_status": "PENDING_HUMAN_REVIEW",
            "gate_eligible": False,
            "draft_reference": case["draft"],
        }
        spans.append(
            _span(
                trace_id,
                span_id,
                f"calibration/{case['id']}/{case['category']}",
                projection["started_at"],
                projection["completed_at"],
                {
                    "langfuse.observation.type": "span",
                    "langfuse.observation.input": case["turns"],
                    "langfuse.observation.output": rows,
                    "langfuse.observation.metadata": metadata,
                    "langfuse.trace.name": f"Calibration {case['id']}",
                    "langfuse.trace.input": case["turns"],
                    "langfuse.trace.output": rows,
                    "langfuse.trace.metadata": metadata,
                    "langfuse.trace.tags": [
                        "synthetic",
                        "pending-human-review",
                        "no-gate",
                    ],
                },
            )
        )
        bindings.append(
            {"case_id": case["id"], "trace_id": trace_id, "span_id": span_id}
        )
        for row in rows:
            diagnostic = row["diagnostic"]
            for kind in ("status", "score"):
                value = diagnostic[kind]
                if value is None:
                    continue
                name = f"calibration.epoch{row['epoch']}.{kind}"
                scores.append(
                    CreateScoreRequest(
                        id=stable_id(trace_id, name),
                        trace_id=trace_id,
                        name=name,
                        value=value,
                        data_type="CATEGORICAL" if kind == "status" else "NUMERIC",
                        metadata={**metadata, "authority": "immutable_inspect_log"},
                    )
                )
    return spans, scores, bindings


def prepare_receipt(path: Path, expected: dict, *, resume_scores: bool) -> dict:
    if resume_scores:
        previous = json.loads(path.read_text())
        if any(
            previous.get(k) != expected[k]
            for k in (
                "destination",
                "projection_sha256",
                "bindings",
            )
        ):
            raise ValueError("Delivery identity changed")
        if previous["status"] not in {
            "OBSERVATIONS_ACCEPTED",
            "SCORES_INFLIGHT",
            "SCORES_ACCEPTED",
        }:
            raise ValueError("Uncertain observations or queue changes: reconcile first")
        return previous
    with path.open("x") as f:
        json.dump(expected, f, indent=2)
    return expected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--local-config", type=Path, required=True)
    parser.add_argument("--resume-scores", action="store_true")
    parser.add_argument(
        "--include-content",
        action="store_true",
        help="Explicitly include this synthetic corpus and Judge explanations",
    )
    args = parser.parse_args()
    corpus, projection = verified_inputs(args.run_dir, args.corpus)
    config = _config(args.local_config)
    if config is None or not (config.get("include_content") or args.include_content):
        raise ValueError("Review requires an enabled local target with content enabled")
    spans, scores, bindings = review_material(corpus, projection)
    path = args.run_dir / "review_delivery.json"
    lock = path.with_suffix(".lock").open("a")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    receipt: dict[str, Any] = {
        "status": "RESERVED",
        "destination": config["target"],
        "projection_sha256": hashlib.sha256(
            (args.run_dir / "projection.json").read_bytes()
        ).hexdigest(),
        "bindings": bindings,
        "accepted_score_ids": [],
        "items": [],
        "human_approved_cases": 0,
    }
    receipt = prepare_receipt(path, receipt, resume_scores=args.resume_scores)

    def checkpoint(status: str) -> None:
        receipt["status"] = status
        atomic_json(path, receipt)

    client = LangfuseAPI(
        base_url=config["base_url"],
        username=config["public_key"],
        password=config["secret_key"],
        timeout=30,
        follow_redirects=False,
        headers={"x-langfuse-ingestion-version": "4"},
    )
    if not args.resume_scores:
        checkpoint("OBSERVATIONS_INFLIGHT")
        response = client.opentelemetry.export_traces(
            resource_spans=[
                OtelResourceSpan(
                    scope_spans=[
                        OtelScopeSpan(
                            scope=OtelScope(name="agent_evaluator.calibration"),
                            spans=spans,
                        )
                    ]
                )
            ],
            request_options=OPTIONS,
        )
        partial = response.model_dump(by_alias=True).get("partialSuccess")
        if partial and (partial.get("rejectedSpans") or partial.get("errorMessage")):
            raise ValueError("Observation ingestion uncertain; reconcile receipt")
        checkpoint("OBSERVATIONS_ACCEPTED")
    accepted = set(receipt["accepted_score_ids"])
    pending = [s for s in scores if s.id not in accepted]
    for offset in range(0, len(pending), 100):
        batch = pending[offset : offset + 100]
        checkpoint("SCORES_INFLIGHT")
        result = client.scores.create(request=batch, request_options=OPTIONS)
        if result.message != "Accepted":
            raise ValueError("Score ingestion incomplete")
        receipt["accepted_score_ids"].extend(s.id for s in batch)
        checkpoint("SCORES_ACCEPTED")
    checkpoint("CONFIG_INFLIGHT")
    score_config = client.score_configs.create(
        name=f"calibration.review.{projection['run_id'][:8]}",
        data_type="CATEGORICAL",
        categories=[
            ConfigCategory(value=i, label=name)
            for i, name in enumerate(
                [
                    "CONFIRM_DRAFT",
                    "CORRECT_DRAFT",
                    "AMBIGUOUS",
                ]
            )
        ],
        description=(
            "Human review only: effective intentions, cancellations and changes. "
            "Comment with corrected intentions, score interval/status and rationale. "
            "Assistant-authored drafts are not gold. No release gates."
        ),
        request_options=OPTIONS,
    )
    receipt["score_config_id"] = score_config.id
    checkpoint("QUEUE_INFLIGHT")
    queue = client.annotation_queues.create_queue(
        name=f"Calibration {projection['run_id'][:8]} - pending human review",
        score_config_ids=[score_config.id],
        description=(
            "Synthetic dialogue fixtures; Inspect repeats retained. "
            "Review each intention. No release gate."
        ),
        request_options=OPTIONS,
    )
    receipt["queue_id"] = queue.id
    receipt["queue_url"] = (
        f"{config['base_url']}/project/{config['project_id']}/annotation-queues/{queue.id}"
    )
    for binding in bindings:
        receipt["inflight_item"] = binding["trace_id"]
        checkpoint("ITEM_INFLIGHT")
        item = client.annotation_queues.create_queue_item(
            queue.id,
            object_id=binding["trace_id"],
            object_type="TRACE",
            status="PENDING",
            request_options=OPTIONS,
        )
        receipt["items"].append({"case_id": binding["case_id"], "item_id": item.id})
        receipt["inflight_item"] = None
        checkpoint("ITEM_ACCEPTED")
    # Read back persisted API scores, keeping categorical values as text.
    expected = {s.id: s.value for s in scores}
    deadline = time.monotonic() + 45
    while True:
        observed = {}
        for binding in bindings:
            page = client.scores.get_many(
                trace_id=binding["trace_id"],
                limit=100,
                request_options=OPTIONS,
            )
            if page.meta.cursor:
                raise ValueError(
                    "Unexpected score pagination; reconcile before acceptance"
                )
            observed.update({s.id: s.value for s in page.data if s.id in expected})
        if observed == expected:
            break
        if time.monotonic() >= deadline:
            raise ValueError("Persisted score values not yet verified")
        time.sleep(2)
    page = client.annotation_queues.list_queue_items(
        queue.id, limit=100, request_options=OPTIONS
    )
    if (
        {i.object_id for i in page.data} != {b["trace_id"] for b in bindings}
        or len(page.data) != len(bindings)
        or any(i.status != "PENDING" for i in page.data)
    ):
        raise ValueError("Review queue readback differs")
    receipt["verified_score_count"] = len(observed)
    receipt["verified_pending_items"] = len(page.data)
    checkpoint("VERIFIED")
    print(
        json.dumps(
            {
                k: receipt[k]
                for k in (
                    "status",
                    "queue_url",
                    "verified_score_count",
                    "verified_pending_items",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
