import json
from types import SimpleNamespace

import pytest
from eval_framework.benchmark import langfuse_export


def test_flat_metadata_preserves_literal_filename_dots_and_rejects_extra_files():
    expected = {"before_files": {"docs/a.v1.txt": "null", "other": "1"}}
    actual = {"before_files.docs/a.v1.txt": "null", "before_files.other": "1"}
    assert langfuse_export._metadata_matches(expected, actual, "before_files")
    actual["before_files.extra.txt"] = "unexpected"
    assert not langfuse_export._metadata_matches(expected, actual, "before_files")


def test_metadata_arrays_may_be_json_encoded_but_strings_remain_exact():
    expected = {"before_snapshot_errors": [{"path": "a", "error": "denied"}]}
    actual = {"before_snapshot_errors": json.dumps(expected["before_snapshot_errors"])}
    assert langfuse_export._metadata_matches(expected, actual, "before_snapshot_errors")
    assert not langfuse_export._metadata_matches(
        {"normalized_input": {"content": "null"}},
        {"normalized_input.content": None},
        "normalized_input",
    )
    assert not langfuse_export._metadata_matches(
        {"execution_started": True}, {"execution_started": 1}, "execution_started"
    )
    assert not langfuse_export._metadata_matches(
        {"tool_schema": {"enum": [True]}}, {"tool_schema.enum": [1]}, "tool_schema"
    )


def test_metadata_never_accepts_a_matching_truncated_prefix():
    value = "a" * 400
    assert not langfuse_export._metadata_matches(
        {"snapshot": {"file.txt": value}},
        {"snapshot.file.txt": value[:200]},
        "snapshot",
    )


def test_flattening_ambiguous_paths_is_rejected():
    with pytest.raises(ValueError, match="ambiguous"):
        langfuse_export._flatten_metadata({"a.b": "first", "a": {"b": "second"}})


def test_duplicate_evidence_id_metadata_accepts_only_exact_decimal_representation():
    field = "evidence_for_observation_id"
    assert langfuse_export._metadata_matches(
        {field: "6501968862483609"}, {field: 6501968862483609}, field
    )
    for bad in (6501968862483610, 6501968862483609.0, True):
        assert not langfuse_export._metadata_matches(
            {field: "6501968862483609"}, {field: bad}, field
        )
    assert not langfuse_export._metadata_matches(
        {"tool_call_id": "6501968862483609"},
        {"tool_call_id": 6501968862483609},
        "tool_call_id",
    )


def test_expanded_json_parent_replaces_child_preview_and_retains_unexpected_leaf():
    rows = [
        {
            "id": "span",
            "metadata": {
                "snapshot.file.json.message": "x" * 200,
                "snapshot.file.json.unexpected": "retain for mismatch detection",
            },
        }
    ]

    def get_many(**kwargs):
        assert kwargs["expand_metadata"] == "snapshot.file.json"
        return SimpleNamespace(
            model_dump=lambda: {
                "data": [
                    {
                        "id": "span",
                        "metadata": {"snapshot.file.json": {"message": "x" * 500}},
                    }
                ],
                "meta": {},
            }
        )

    langfuse_export._expand_metadata(get_many, rows, {"snapshot.file.json": True})
    assert rows[0]["metadata"]["snapshot.file.json.message"] == "x" * 500
    assert "snapshot.file.json.unexpected" in rows[0]["metadata"]


def test_expansion_requests_full_long_values_in_bounded_queries():
    from urllib.parse import quote

    keys = {f"snapshot.folder-{i}/file.v1.txt": "x" * 300 for i in range(150)}
    rows = [
        {
            "id": "span",
            "trace_id": "trace",
            "metadata": {k: v[:200] for k, v in keys.items()},
        }
    ]
    calls = []

    def get_many(**kwargs):
        calls.append(kwargs)
        selected = kwargs["expand_metadata"].split(",")
        assert len(quote(kwargs["expand_metadata"], safe="")) <= 2500
        return SimpleNamespace(
            model_dump=lambda: {
                "data": [
                    {
                        "id": "span",
                        "trace_id": "trace",
                        "metadata": {
                            key: value if key in selected else value[:200]
                            for key, value in keys.items()
                        },
                    }
                ],
                "meta": {},
            }
        )

    langfuse_export._expand_metadata(get_many, rows, keys, environment="benchmark")
    assert rows[0]["metadata"] == keys
    assert len(calls) > 1


def test_readback_queries_only_bounded_trace_batches_and_paginates_each():
    from urllib.parse import urlencode

    identities = [f"{i:032x}" for i in range(101)]
    calls = []
    spans = [
        SimpleNamespace(
            trace_id=identity,
            attributes=[
                SimpleNamespace(
                    key="langfuse.observation.metadata",
                    value=SimpleNamespace(
                        string_value=json.dumps(
                            {"snapshot": {"a.v1.txt": "x" * 300}} if index == 0 else {}
                        )
                    ),
                )
            ],
        )
        for index, identity in enumerate(identities)
    ]

    def page(kind, **kwargs):
        calls.append((kind, kwargs))
        assert (
            len(
                urlencode(
                    {key: value for key, value in kwargs.items() if value is not None}
                )
            )
            < 6000
        )
        if kind == "observations":
            filters = json.loads(kwargs["filter"])
            assert len(filters) == 1
            selection = filters[0]
            assert selection["type"] == "stringOptions"
            assert selection["column"] == "traceId"
            assert selection["operator"] == "any of"
            selected = selection["value"]
        else:
            selected = kwargs["trace_id"].split(",")
            assert kwargs["limit"] == 100
        assert 1 <= len(selected) <= 50
        assert set(selected).issubset(identities)
        # Force two pages for every chunk to prove cursors keep the same scope.
        midpoint = max(1, len(selected) // 2)
        current = selected[midpoint:] if kwargs.get("cursor") else selected[:midpoint]
        rows = [
            {"id": identity, "trace_id": identity, "metadata": {}}
            for identity in current
        ]
        for row in rows:
            if row["trace_id"] == identities[0] and kind == "observations":
                row["metadata"] = {
                    "snapshot.a.v1.txt": "x"
                    * (300 if kwargs.get("expand_metadata") else 200)
                }
        cursor = (
            "second-page"
            if len(selected) > midpoint and not kwargs.get("cursor")
            else None
        )
        return SimpleNamespace(
            model_dump=lambda: {"data": rows, "meta": {"cursor": cursor}}
        )

    client = SimpleNamespace(
        observations=SimpleNamespace(get_many=lambda **kw: page("observations", **kw)),
        scores=SimpleNamespace(get_many=lambda **kw: page("scores", **kw)),
    )
    observations, scores = langfuse_export._read_remote_evidence(
        client, spans, [{"trace_id": identity} for identity in identities]
    )
    assert sorted(row["id"] for row in observations) == identities
    assert sorted(row["id"] for row in scores) == identities
    assert observations[0]["metadata"]["snapshot.a.v1.txt"] == "x" * 300
    assert any(call.get("expand_metadata") for _, call in calls)
    assert len({call["trace_id"] for kind, call in calls if kind == "scores"}) == 3
