"""Receipt-version coverage for lossless Langfuse metadata evidence."""

import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from eval_framework.benchmark import langfuse_export
from eval_framework.observability import _span

SOURCE_HASH = "a" * 64


def saved_span(span_id: str):
    return _span(
        "1" * 32,
        span_id,
        "recorded-operation",
        "2026-11-01T00:00:01Z",
        "2026-11-01T00:00:02Z",
        {
            "langfuse.observation.type": "tool",
            "langfuse.observation.metadata": {
                "snapshot": {"config.json": '{\n  "ready": true\n}\n'}
            },
            "langfuse.observation.input": {"saved": "input"},
            "langfuse.observation.output": "saved output",
            "langfuse.environment": "benchmark",
        },
    )


class SavedLangfuse:
    """Minimal in-memory transport for production export and read-back."""

    def __init__(self, spans):
        self.spans = list(spans)
        self.export_calls = 0
        self.opentelemetry = SimpleNamespace(export_traces=self.save_spans)
        self.observations = SimpleNamespace(get_many=self.observation_page)
        self.scores = SimpleNamespace(get_many=lambda **kwargs: self.page([]))
        self.experiments = SimpleNamespace(
            list_items=lambda **kwargs: self.page([{"id": "item"}])
        )

    @staticmethod
    def page(rows):
        return SimpleNamespace(model_dump=lambda **kwargs: {"data": rows, "meta": {}})

    def save_spans(self, resource_spans, **kwargs):
        self.export_calls += 1
        for resource in resource_spans:
            for scope in resource.scope_spans:
                self.spans.extend(scope.spans)
        return SimpleNamespace(model_dump=lambda **kwargs: {})

    def observation_page(self, **kwargs):
        rows = []
        for span in self.spans:
            attributes = {
                item.key: self._decode(item.value.string_value)
                for item in span.attributes
            }
            rows.append(
                {
                    "id": span.span_id,
                    "trace_id": span.trace_id,
                    "parent_observation_id": span.parent_span_id,
                    "type": attributes["langfuse.observation.type"],
                    "start_time": datetime.fromtimestamp(
                        int(span.start_time_unix_nano) / 1e9, UTC
                    ),
                    "end_time": datetime.fromtimestamp(
                        int(span.end_time_unix_nano) / 1e9, UTC
                    ),
                    "input": attributes.get("langfuse.observation.input"),
                    "output": attributes.get("langfuse.observation.output"),
                    "metadata": langfuse_export._metadata_with_json_values(
                        attributes.get("langfuse.observation.metadata") or {}
                    ),
                    "model": attributes.get("langfuse.observation.model.name"),
                    "usage_details": attributes.get(
                        "langfuse.observation.usage_details"
                    ),
                }
            )
        return self.page(rows)

    @staticmethod
    def _decode(value):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value


def configure_run(tmp_path, monkeypatch, original):
    run = {"started_at": "2026-11-01T00:00:00+00:00"}
    trace = {
        "trace_id": original.trace_id,
        "observation_ids": [original.span_id],
        "score_ids": [],
        "case_id": "case-1",
        "trial": 1,
        "experiment_id": "experiment-1",
    }
    monkeypatch.setattr(
        langfuse_export,
        "_source",
        lambda run_dir, dataset_path: (run, [], SOURCE_HASH),
    )
    monkeypatch.setattr(
        langfuse_export,
        "build_payload",
        lambda run, tasks, dataset_id, source_hash: (
            [original],
            [],
            [copy.deepcopy(trace)],
        ),
    )
    monkeypatch.setattr(langfuse_export, "destination_fingerprint", lambda: "offline")
    (tmp_path / "langfuse_export.json").write_text(
        json.dumps(
            {
                "source_hash": SOURCE_HASH,
                "destination": "offline",
                "dataset_id": "dataset-1",
                "status": "ACCEPTED",
            }
        )
    )
    return tmp_path / "dataset.json"


def test_v2_numeric_looking_target_survives_export_and_verify(tmp_path, monkeypatch):
    original = saved_span("24481393e7248852")
    original_bytes = original.model_dump_json()
    dataset_path = configure_run(tmp_path, monkeypatch, original)
    client = SavedLangfuse([original])

    receipt = langfuse_export.export_metadata_evidence(
        tmp_path, dataset_path, client=client
    )

    assert receipt["version"] == langfuse_export.EVIDENCE_VERSION
    proof = client.spans[-1]
    proof_metadata = SavedLangfuse._decode(
        next(
            item.value.string_value
            for item in proof.attributes
            if item.key == "langfuse.observation.metadata"
        )
    )
    assert proof_metadata["evidence_for_observation_id"] == (
        "observation:24481393e7248852"
    )
    assert proof.parent_span_id == original.span_id
    assert proof.trace_id == original.trace_id
    assert original.model_dump_json() == original_bytes
    assert (
        langfuse_export.verify_run(tmp_path, dataset_path, client=client)["status"]
        == "VERIFIED"
    )


def test_existing_v1_receipt_reuses_bytes_without_export_and_verifies(
    tmp_path, monkeypatch
):
    original = saved_span("6501968862483609")
    dataset_path = configure_run(tmp_path, monkeypatch, original)
    proof = langfuse_export.build_evidence_payload(
        [original], SOURCE_HASH, version=langfuse_export.EVIDENCE_VERSION_V1
    )[0]
    receipt = {
        "version": langfuse_export.EVIDENCE_VERSION_V1,
        "source_hash": SOURCE_HASH,
        "destination": "offline",
        "dataset_id": "dataset-1",
        "evidence_observation_ids": [proof.span_id],
        "target_observation_ids": [original.span_id],
        "status": "ACCEPTED",
        "accepted_observation_ids": [proof.span_id],
        "inflight": [],
    }
    (tmp_path / langfuse_export.EVIDENCE_RECEIPT).write_text(json.dumps(receipt))
    client = SavedLangfuse([original, proof])

    returned = langfuse_export.export_metadata_evidence(
        tmp_path, dataset_path, client=client
    )

    assert returned == receipt
    assert client.export_calls == 0
    assert (
        langfuse_export.verify_run(tmp_path, dataset_path, client=client)["status"]
        == "VERIFIED"
    )
    assert client.export_calls == 0


def test_export_and_verify_reject_unknown_evidence_receipt_version(
    tmp_path, monkeypatch
):
    original = saved_span("6501968862483609")
    dataset_path = configure_run(tmp_path, monkeypatch, original)
    (tmp_path / langfuse_export.EVIDENCE_RECEIPT).write_text(
        json.dumps({"version": "langfuse-exact-metadata-v9"})
    )
    client = SavedLangfuse([original])

    with pytest.raises(ValueError, match="Unsupported supplemental evidence version"):
        langfuse_export.export_metadata_evidence(tmp_path, dataset_path, client=client)
    with pytest.raises(ValueError, match="Unsupported supplemental evidence version"):
        langfuse_export.verify_run(tmp_path, dataset_path, client=client)
    assert client.export_calls == 0
