# ruff: noqa: E402 -- optional SDK availability is checked before integration imports.
"""Exact saved metadata must survive the API's JSON-string normalization."""

import base64
import copy
import hashlib
import json

import pytest

pytest.importorskip("langfuse", reason="requires agent-evaluator[langfuse]")

from eval_framework.benchmark import langfuse_export
from eval_framework.observability import _span

SOURCE_HASH = "a" * 64


def saved_span(span_id: str, metadata: dict, *, kind: str = "tool"):
    return _span(
        "1" * 32,
        span_id,
        "recorded-operation",
        "2026-11-01T00:00:01Z",
        "2026-11-01T00:00:02Z",
        {
            "langfuse.observation.type": kind,
            "langfuse.observation.metadata": metadata,
            "langfuse.observation.input": {"saved": "input"},
            "langfuse.observation.output": "saved output",
            "langfuse.environment": "benchmark",
        },
    )


def metadata_of(span):
    attributes = {item.key: item.value.string_value for item in span.attributes}
    return json.loads(attributes["langfuse.observation.metadata"])


def decode_evidence(span):
    metadata = metadata_of(span)
    assert metadata["exact_metadata_base64"].startswith("base64:")
    raw = base64.b64decode(
        metadata["exact_metadata_base64"].removeprefix("base64:"), validate=True
    )
    assert metadata["exact_metadata_sha256"] == (
        "sha256:" + hashlib.sha256(raw).hexdigest()
    )
    return json.loads(raw), metadata


def test_new_evidence_target_identity_survives_json_value_parsing():
    original = saved_span("24481393e7248852", {"snapshot": {"config.json": "{}"}})

    evidence = langfuse_export.build_evidence_payload([original], SOURCE_HASH)

    metadata = metadata_of(evidence[0])
    assert metadata["evidence_for_observation_id"] == ("observation:24481393e7248852")
    assert (
        langfuse_export._metadata_with_json_values(metadata)[
            "evidence_for_observation_id"
        ]
        == metadata["evidence_for_observation_id"]
    )
    assert evidence[0].parent_span_id == original.span_id
    assert evidence[0].trace_id == original.trace_id


def test_v2_numeric_source_hash_survives_json_value_parsing():
    numeric_source_hash = "2" * 64
    original = saved_span("2" * 16, {"snapshot": {"config.json": "{}"}})

    evidence = langfuse_export.build_evidence_payload([original], numeric_source_hash)

    metadata = metadata_of(evidence[0])
    assert metadata["evidence_source_sha256"] == "sha256:" + numeric_source_hash
    assert (
        langfuse_export._metadata_with_json_values(metadata)["evidence_source_sha256"]
        == metadata["evidence_source_sha256"]
    )


@pytest.mark.parametrize(
    "content",
    [
        ' { "status" : "ready", "count": 1 } \n',
        '[ 1, "二", {"nested": "{ \\"x\\": 2 }"} ]',
        "\n true \t",
        " 1.00 \n",
        " null\n",
        ' "a string" ',
        '{"long": "' + "x" * 400 + '"}\n',
    ],
)
def test_evidence_preserves_json_text_bytes_and_source_binding(content):
    # These strings are file contents, not the decoded values the API exposes.
    json.loads(content)
    original = saved_span("2" * 16, {"before_files": {"docs/a.v1.json": content}})

    evidence = langfuse_export.build_evidence_payload([original], SOURCE_HASH)

    assert len(evidence) == 1
    restored, metadata = decode_evidence(evidence[0])
    assert restored == {"before_files": {"docs/a.v1.json": content}}
    assert restored["before_files"]["docs/a.v1.json"].encode() == content.encode()
    assert metadata["evidence_source_sha256"] == "sha256:" + SOURCE_HASH
    assert metadata["evidence_for_observation_id"] == (
        langfuse_export.EVIDENCE_TARGET_PREFIX + original.span_id
    )
    assert metadata["is_export_evidence"] is True
    assert isinstance(metadata["evidence_export_version"], str)
    assert metadata["evidence_export_version"]
    assert evidence[0].parent_span_id == original.span_id
    assert evidence[0].trace_id == original.trace_id
    assert evidence[0].name == "saved-exact-metadata"


def test_v1_evidence_identity_remains_rebuildable_for_existing_receipts():
    original = saved_span("6501968862483609", {"snapshot": {"config.json": "{}"}})

    first = langfuse_export.build_evidence_payload(
        [original], SOURCE_HASH, version=langfuse_export.EVIDENCE_VERSION_V1
    )
    replay = langfuse_export.build_evidence_payload(
        [original], SOURCE_HASH, version=langfuse_export.EVIDENCE_VERSION_V1
    )

    assert [span.model_dump() for span in first] == [
        span.model_dump() for span in replay
    ]
    metadata = metadata_of(first[0])
    assert metadata["evidence_export_version"] == (langfuse_export.EVIDENCE_VERSION_V1)
    assert metadata["evidence_source_sha256"] == SOURCE_HASH
    assert metadata["evidence_for_observation_id"] == original.span_id
    assert first[0].parent_span_id == original.span_id
    assert first[0].trace_id == original.trace_id


def test_unknown_evidence_version_is_rejected_even_without_payload():
    with pytest.raises(ValueError, match="Unsupported supplemental evidence version"):
        langfuse_export.build_evidence_payload([], SOURCE_HASH, version="unknown-v9")


def test_only_affected_verified_fields_and_observations_get_evidence():
    affected = saved_span(
        "2" * 16,
        {
            "before_files": {"settings.json": ' { "enabled": true } '},
            "normalized_input": {"path": "settings.json", "content": "null\n"},
            "after_files": {"note.txt": "ordinary text"},
            "unverified_extra": {"text": '{"ignored": true}'},
        },
    )
    plain = saved_span("3" * 16, {"snapshot": {"note.txt": "ordinary text"}})
    unverified = saved_span("4" * 16, {"unverified_extra": '{"ignored": true}'})
    typed = saved_span(
        "5" * 16,
        {"tool_schema": {"additionalProperties": False}, "turn": 1, "is_error": False},
    )

    evidence = langfuse_export.build_evidence_payload(
        [affected, plain, unverified, typed], SOURCE_HASH
    )

    assert len(evidence) == 1
    restored, _ = decode_evidence(evidence[0])
    assert restored == {
        "before_files": {"settings.json": ' { "enabled": true } '},
        "normalized_input": {"path": "settings.json", "content": "null\n"},
    }
    assert evidence[0].parent_span_id == affected.span_id
    assert langfuse_export.build_evidence_payload([], SOURCE_HASH) == []


def test_nested_lists_and_json_strings_remain_exact_without_mutating_spans():
    metadata = {
        "normalized_input": {
            "payload": [
                {"content": ' { "inner": "[ 1, 2 ]", "label": "二" } \n'},
                [" true ", "ordinary text", {"number": " 3.0 "}],
            ],
        },
        "is_error": False,
    }
    original = saved_span("2" * 16, metadata)
    original_dump = copy.deepcopy(original.model_dump())
    original_metadata = copy.deepcopy(metadata)

    evidence = langfuse_export.build_evidence_payload([original], SOURCE_HASH)

    restored, _ = decode_evidence(evidence[0])
    assert restored == {"normalized_input": metadata["normalized_input"]}
    assert original.model_dump() == original_dump
    assert metadata == original_metadata


def test_evidence_ids_are_stable_unique_and_bound_to_the_saved_source():
    originals = [
        saved_span("2" * 16, {"snapshot": {"a.json": "{}"}}),
        saved_span("3" * 16, {"snapshot": {"a.json": "{}"}}),
    ]

    first = langfuse_export.build_evidence_payload(originals, SOURCE_HASH)
    replay = langfuse_export.build_evidence_payload(originals, SOURCE_HASH)
    changed_source = langfuse_export.build_evidence_payload(originals, "b" * 64)

    assert [span.model_dump() for span in first] == [
        span.model_dump() for span in replay
    ]
    assert len({span.span_id for span in first}) == len(originals)
    assert not ({span.span_id for span in first} & {span.span_id for span in originals})
    assert not (
        {span.span_id for span in first} & {span.span_id for span in changed_source}
    )
    assert [metadata_of(span)["evidence_source_sha256"] for span in changed_source] == [
        "sha256:" + "b" * 64,
        "sha256:" + "b" * 64,
    ]


def test_supplemental_evidence_is_not_a_model_tool_or_score_event():
    original = saved_span("2" * 16, {"normalized_input": {"content": "[1, 2]"}})

    evidence = langfuse_export.build_evidence_payload([original], SOURCE_HASH)

    assert len(evidence) == 1
    attributes = {item.key: item.value.string_value for item in evidence[0].attributes}
    assert attributes["langfuse.observation.type"] == "span"
    assert not any(
        key.startswith("langfuse.observation.model")
        or key.startswith("langfuse.observation.usage")
        or key.startswith("langfuse.score")
        for key in attributes
    )
    assert not metadata_of(evidence[0]).get("is_judge", False)
    assert "tool_call_id" not in metadata_of(evidence[0])


def test_semantic_metadata_conversion_recurses_without_mutating_saved_evidence():
    original = {
        "before_files": {"null.json": " null\n", "text.txt": "ordinary text"},
        "normalized_input": {
            "nested": [
                " true ",
                {"json": ' { "items": "[ 1, 2 ]", "nested": {"flag": "false"} } '},
            ],
            "encoded_boolean": '" true "',
            "count": 1,
        },
    }
    saved = copy.deepcopy(original)

    parsed = langfuse_export._metadata_with_json_values(original)

    assert parsed == {
        "before_files": {"null.json": None, "text.txt": "ordinary text"},
        "normalized_input": {
            "nested": [True, {"json": {"items": [1, 2], "nested": {"flag": False}}}],
            "encoded_boolean": True,
            "count": 1,
        },
    }
    assert original == saved


def test_semantically_equal_json_strings_need_distinct_exact_evidence():
    first = {"snapshot": {"config.json": '{"enabled": true}\n'}}
    second = {"snapshot": {"config.json": '  { "enabled" : true }  '}}
    assert langfuse_export._metadata_with_json_values(
        first
    ) == langfuse_export._metadata_with_json_values(second)

    first_evidence = langfuse_export.build_evidence_payload(
        [saved_span("2" * 16, first)], SOURCE_HASH
    )[0]
    second_evidence = langfuse_export.build_evidence_payload(
        [saved_span("2" * 16, second)], SOURCE_HASH
    )[0]

    restored_first, metadata_first = decode_evidence(first_evidence)
    restored_second, metadata_second = decode_evidence(second_evidence)
    assert restored_first == first
    assert restored_second == second
    assert (
        metadata_first["exact_metadata_sha256"]
        != metadata_second["exact_metadata_sha256"]
    )
    assert (
        metadata_first["exact_metadata_base64"]
        != metadata_second["exact_metadata_base64"]
    )


def test_empty_objects_need_lossless_proof_and_legacy_payload_stays_stable():
    original = saved_span(
        "2" * 16, {"before_files": {}, "snapshot": {"empty": {}, "count": 0}}
    )
    evidence = langfuse_export.build_evidence_payload([original], SOURCE_HASH)
    assert len(evidence) == 1
    decoded, _ = decode_evidence(evidence[0])
    assert decoded == {"before_files": {}, "snapshot": {"empty": {}, "count": 0}}
    assert (
        langfuse_export.build_evidence_payload(
            [original], SOURCE_HASH, version="langfuse-exact-metadata-v2"
        )
        == []
    )
    assert not langfuse_export._metadata_matches(
        {"before_files": {}}, {}, "before_files"
    )
    matches = langfuse_export._empty_object_projection_matches
    assert matches(
        {"snapshot": {"empty": {}, "count": 0}}, {"snapshot.count": 0}, "snapshot"
    )
    assert not matches({"snapshot": {"empty": {}, "count": 0}}, {}, "snapshot")
    assert not matches({"snapshot": {}}, {"snapshot.extra": 1}, "snapshot")
