import copy
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from .test_report_trends import source


def example():
    s = source()
    s["analysis"]["analysis_id"] = "analysis"
    for i, (t, d) in enumerate(
        zip(s["run"]["trials"], s["analysis"]["trials"], strict=True)
    ):
        t["observation"] = {
            "evidence_complete": True,
            "events": [{"type": "tool"}] * i,
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }
        t["started_at"] = "2026-11-01T00:00:00Z"
        t["finished_at"] = "2026-11-01T00:01:00Z"
        t["latency_seconds"] = 10 + i * 20
        d["category"] = t["category"]
        d["findings"] = ([{"kind": "schema_mismatch"}] * 2) if i else []
    return s


def test_explorer_deduplicates_diagnosis_and_does_not_double_count_cache():
    from eval_framework.benchmark.report_explorer import summarize

    s = example()
    before = copy.deepcopy(s)
    usages = [
        {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12, "cached_tokens": 4}
    ] * 2
    x = summarize(s["run"], s["analysis"], usages, None)
    assert x["stats"]["total_tokens"] == 24 and x["stats"]["cached_input_tokens"] == 8
    assert (
        x["stats"]["noncached_input_tokens"] == 12 and x["stats"]["input_tokens"] == 20
    )
    assert x["stats"]["tool_calls_mean"] == 0.5
    assert (
        x["stats"]["latency_mean_seconds"] == 20
        and x["stats"]["latency_p95_seconds"] == 30
    )
    assert x["stats"]["actual_cost_usd"] is None
    assert len(x["issues"]["schema_mismatch"]) == 1
    assert (
        x["categories"]["write"]["total"] == 1
        and x["categories"]["write"]["pass_rate_percent"] == 0
    )
    assert s == before


def test_unknown_usage_and_incomplete_tool_evidence_are_not_zero():
    from eval_framework.benchmark.report_explorer import summarize

    s = example()
    s["run"]["trials"][0]["observation"]["evidence_complete"] = False
    x = summarize(s["run"], s["analysis"], [{}, {}], None)
    assert x["stats"]["total_tokens"] is None
    assert x["stats"]["tool_calls_mean"] is None
    assert x["estimate"] is None


def test_exact_observation_url_has_ids_and_time_range_and_rejects_oversize():
    from eval_framework.benchmark.report_explorer import observation_url

    url = observation_url("https://example.test", "p", ["a", "b"], [1000, 2000])
    q = parse_qs(urlsplit(url).query)
    assert unquote(q["filter"][0]) == "id;stringOptions;;any of;a|b"
    assert q["dateRange"] == ["1000-2000"]
    with pytest.raises(ValueError):
        observation_url("https://example.test", "p", [], [1000, 2000])
    with pytest.raises(ValueError):
        observation_url("https://example.test", "p", ["a" * 5000], [1000, 2000])


def test_estimate_is_separate_from_actual_and_formal_metrics_are_only_reused():
    from eval_framework.benchmark.report_explorer import summarize

    s = example()
    s["run"]["trials"][0]["assessment"]["metrics"] = [
        {"name": "field_match", "score": 0, "formal": True, "status": "SCORED"}
    ]
    estimate = {"low": 1, "high": 2, "pricing": {"kind": "subscription_allowance"}}
    x = summarize(s["run"], s["analysis"], [{}, {}], estimate)
    assert x["stats"]["actual_cost_usd"] is None and x["estimate"] == estimate
    assert x["formal_metrics"]["field_match"] == {"count": 1, "values": [0]}


def test_partial_cache_does_not_fall_back_to_mixed_input_conventions():
    from eval_framework.benchmark.report_explorer import summarize

    s = example()
    usages = [
        {
            "input_tokens": 10,
            "cached_tokens": 4,
            "output_tokens": 2,
            "total_tokens": 16,
        },
        {
            "input_tokens": 10,
            "cached_tokens": None,
            "output_tokens": 2,
            "total_tokens": 12,
        },
    ]
    assert (
        summarize(s["run"], s["analysis"], usages, None)["stats"]["input_tokens"]
        is None
    )


def test_histogram_omits_ambiguous_same_name_nonformal_scores():
    from eval_framework.benchmark.report_explorer import summarize

    s = example()
    s["run"]["trials"][0]["assessment"]["metrics"] = [
        {"name": "shared", "score": 1, "formal": True, "status": "SCORED"},
        {"name": "shared", "score": 0, "formal": False, "status": "SCORED"},
    ]
    x = summarize(s["run"], s["analysis"], [{}, {}], None)
    assert x["formal_metrics"]["shared"]["values"] == [1]
    assert "shared" not in x["histogram_eligible"]
