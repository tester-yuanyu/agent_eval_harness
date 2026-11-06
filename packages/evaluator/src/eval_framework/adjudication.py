"""Read-only Langfuse annotation import; cloud is the sole editable authority."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from .observability import RECEIPT, client_from_env, destination_fingerprint
from .optional_dependencies import require_langfuse
from .result_loader import load_run_result
from .schema_base import StrictModel
from .schemas import ManualConclusion
from .taxonomy import BUILTIN_LABELS, TAXONOMY_VERSION

if TYPE_CHECKING:
    from langfuse.api.client import LangfuseAPI

REVIEW_SCORE_NAME = "review.decision.v1"


class ReviewDetails(StrictModel):
    """Business taxonomy stored in the annotation comment as JSON."""

    reason: str = Field(min_length=1)
    primary_cause: str | None = None
    secondary_causes: list[str] = Field(default_factory=list)
    optimization_direction: Literal[
        "none", "prompt", "tool", "agent_logic", "environment", "dataset_contract"
    ]


class ReviewSnapshot(StrictModel):
    source: Literal["langfuse"] = "langfuse"
    source_project_id: str
    source_score_id: str
    source_revision_sha256: str
    source_updated_at: str
    result_sha256: str
    case_id: str
    trial_id: str
    automatic_conclusion: str
    manual_conclusion: ManualConclusion
    reviewer: str = Field(min_length=1)
    taxonomy_version: str = TAXONOMY_VERSION
    taxonomy_sha256: str
    details: ReviewDetails


def import_reviews(
    run_dir: str | Path,
    *,
    client: LangfuseAPI | None = None,
) -> dict[str, Any]:
    """Validate the complete fetch before appending revisions. No verdict override."""
    require_langfuse()
    root = Path(run_dir).expanduser().resolve()
    loaded = load_run_result(root)
    receipt = json.loads((root / RECEIPT).read_text())
    if loaded.sha256 != receipt["results_sha256"]:
        raise ValueError("Review source must match immutable exported results")
    if (
        receipt["status"] != "ACCEPTED"
        or receipt["destination"] != destination_fingerprint()
    ):
        raise ValueError("Review import requires an accepted export to this project")
    client = client or client_from_env()
    cases = {(c.case_id, c.trial_id): c for c in loaded.result.cases}
    taxonomy = set(BUILTIN_LABELS)
    taxonomy.update(d.code for c in cases.values() for d in c.diagnoses)
    taxonomy_hash = hashlib.sha256(json.dumps(sorted(taxonomy)).encode()).hexdigest()
    records: list[ReviewSnapshot] = []
    for binding in receipt["trials"]:
        case = cases[(binding["case_id"], binding["trial_id"])]
        cursor = None
        seen_cursors: set[str] = set()
        while True:
            page = client.scores.get_many(
                trace_id=binding["trace_id"],
                name=REVIEW_SCORE_NAME,
                source="ANNOTATION",
                limit=100,
                cursor=cursor,
                fields="details,subject,annotation",
            )
            for score in page.data:
                subject = score.subject
                trace_id = (
                    subject.id
                    if subject and subject.kind == "trace"
                    else getattr(subject, "trace_id", None)
                )
                if (
                    score.source != "ANNOTATION"
                    or score.name != REVIEW_SCORE_NAME
                    or score.data_type != "CATEGORICAL"
                    or trace_id != binding["trace_id"]
                ):
                    raise ValueError("Review source or run binding is invalid")
                details = ReviewDetails.model_validate_json(score.comment or "{}")
                labels = [details.primary_cause, *details.secondary_causes]
                if any(label is not None and label not in taxonomy for label in labels):
                    raise ValueError("Unknown Error Taxonomy label")
                raw = score.model_dump(mode="json")
                revision = hashlib.sha256(
                    json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                records.append(
                    ReviewSnapshot(
                        source_project_id=score.project_id,
                        source_score_id=score.id,
                        source_revision_sha256=revision,
                        source_updated_at=score.updated_at.isoformat(),
                        result_sha256=loaded.sha256,
                        case_id=case.case_id,
                        trial_id=case.trial_id,
                        automatic_conclusion=case.quality_conclusion,
                        manual_conclusion=score.value,
                        reviewer=score.author_user_id or "",
                        taxonomy_sha256=taxonomy_hash,
                        details=details,
                    )
                )
            cursor = page.meta.cursor
            if not cursor:
                break
            if cursor in seen_cursors:
                raise ValueError("Langfuse returned a repeated pagination cursor")
            seen_cursors.add(cursor)
    path = root / "langfuse_reviews.jsonl"
    previous = (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )
    known = {row["source_revision_sha256"] for row in previous}
    pending: list[dict[str, Any]] = []
    for record in records:
        if record.source_revision_sha256 not in known:
            pending.append(record.model_dump(mode="json"))
            known.add(record.source_revision_sha256)
    if pending:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False) + "\n"
                for row in [*previous, *pending]
            )
        )
        temporary.replace(path)
    snapshot = {
        "authority": "Langfuse Annotation",
        "results_sha256": loaded.sha256,
        "imported": len(pending),
        "active_revisions": sorted({r.source_revision_sha256 for r in records}),
        "automatic_results_unchanged": True,
    }
    active = root / "langfuse_review_sync.json"
    temporary = active.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    temporary.replace(active)
    return snapshot
