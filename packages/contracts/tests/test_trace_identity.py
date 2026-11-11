"""身份校验不依赖存储框架，不重写调用者的数据。"""

from eval_contracts import trace


def test_duplicate_event_ids_preserve_counts_and_allow_distinct_ids():
    assert trace.duplicate_event_ids(["a", "b", "a", "a", "c", "b"]) == {"a": 3, "b": 2}
    assert trace.duplicate_event_ids(iter(["a", "b"])) == {}


def test_associations_require_every_event_to_match_without_coercion():
    assert trace.associations_match(["trial", "trial"], "trial")
    assert not trace.associations_match(["trial", None], "trial")
    assert not trace.associations_match(["trial", "other"], "trial")
    assert not trace.associations_match(["1"], 1)
