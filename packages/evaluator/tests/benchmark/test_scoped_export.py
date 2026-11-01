import json

import pytest

from eval_framework.benchmark.agentic_metrics import _record_specs
from eval_framework.benchmark.langfuse_export import build_payload


def fixture(metrics):
    events = [
        {
            "id": "turn",
            "type": "turn",
            "name": "turn-1",
            "input": "write",
            "output": "done",
            "snapshot": {"a": "b"},
        },
        {
            "id": "tool1",
            "parent_id": "turn",
            "type": "tool",
            "name": "write_file",
            "input": {"path": "a", "content": "b"},
            "output": "written",
            "before_files": {},
            "after_files": {"a": "b"},
        },
        {
            "id": "tool2",
            "parent_id": "turn",
            "type": "tool",
            "name": "read_file",
            "input": {"path": "a"},
            "output": "b",
        },
    ]
    for event in events:
        event.update(start_time="2026-11-01T00:00:01Z", end_time="2026-11-01T00:00:02Z")
    run = {
        "run_id": "scoped",
        "mode": "real_agent",
        "trials": [
            {
                "case_id": "c",
                "trial": 1,
                "category": "multi_file",
                "split": "dev",
                "started_at": "2026-11-01T00:00:00Z",
                "finished_at": "2026-11-01T00:00:03Z",
                "observation": {
                    "events": events,
                    "turns": [{"input": "write", "output": "done"}],
                },
                "assessment": {"verdict": "PASS", "metrics": metrics},
            }
        ],
    }
    return run, {
        "c": {"id": "c", "prompt": "write", "oracle": {"expected_files": {"a": "b"}}}
    }


def test_repeated_metric_names_bind_to_distinct_child_observations_idempotently():
    run, tasks = fixture(
        [
            {
                "name": "tool_schema",
                "score": 1.0,
                "scope": "tool",
                "event_id": "tool1",
                "version": "v2",
            },
            {
                "name": "tool_schema",
                "score": 0.0,
                "scope": "tool",
                "event_id": "tool2",
                "version": "v2",
            },
            {
                "name": "checkpoint:first",
                "score": 1.0,
                "scope": "turn",
                "event_id": "turn",
                "version": "v2",
            },
        ]
    )
    spans, scores, _ = build_payload(run, tasks, "data", "hash")
    assert [score.observation_id for score in scores[1:]] == [
        spans[2].span_id,
        spans[3].span_id,
        spans[1].span_id,
    ]
    assert len({score.id for score in scores}) == 4
    assert [score.id for score in scores] == [
        score.id for score in build_payload(run, tasks, "data", "hash")[1]
    ]
    tool_attrs = {a.key: a.value.string_value for a in spans[2].attributes}
    metadata = json.loads(tool_attrs["langfuse.observation.metadata"])
    assert metadata["before_files"] == {} and metadata["after_files"] == {"a": "b"}


@pytest.mark.parametrize("event_id", ["unknown", None])
def test_scoped_scores_cannot_silently_fall_back_to_root(event_id):
    run, tasks = fixture(
        [{"name": "tool_schema", "score": 1.0, "scope": "tool", "event_id": event_id}]
    )
    with pytest.raises(ValueError, match="event"):
        build_payload(run, tasks, "data", "hash")


def test_arbitrary_chain_metric_cannot_silently_fall_back_to_root():
    run, tasks = fixture(
        [
            {
                "name": "damaged_chain_metric",
                "score": 1.0,
                "backend": "deepeval",
                "implementation": "UnknownChainMetric",
                "scope": "chain",
                "event_id": None,
            }
        ]
    )
    with pytest.raises(ValueError, match="event"):
        build_payload(run, tasks, "data", "hash")


def test_node_chain_metric_keeps_its_explicit_observation_binding():
    run, tasks = fixture(
        [
            {
                "name": "node_chain_metric",
                "score": 0.5,
                "scope": "chain",
                "event_id": "tool1",
            }
        ]
    )

    spans, scores, _ = build_payload(run, tasks, "data", "hash")

    assert scores[1].name == "node_chain_metric"
    assert scores[1].observation_id == spans[2].span_id


def test_native_step_efficiency_whole_trace_score_binds_to_root():
    run, tasks = fixture([])
    observation = run["trials"][0]["observation"]
    record, target = _record_specs(
        tasks["c"], observation, ["step_efficiency"]
    )[0]
    assert target is None
    record.update(score=0.75, status="SCORED", reason="Recorded trace is efficient.")
    run["trials"][0]["assessment"]["metrics"] = [record]

    spans, scores, traces = build_payload(run, tasks, "data", "hash")

    score = next(item for item in scores if item.name == "step_efficiency")
    assert score.observation_id == spans[0].span_id == traces[0]["root_id"]
    assert score.metadata["metric"] == record


def test_duplicate_event_ids_and_unknown_parents_are_rejected():
    run, tasks = fixture([])
    run["trials"][0]["observation"]["events"][2]["id"] = "tool1"
    with pytest.raises(ValueError, match="duplicate"):
        build_payload(run, tasks, "data", "hash")
    run, tasks = fixture([])
    run["trials"][0]["observation"]["events"][2]["parent_id"] = "missing"
    with pytest.raises(ValueError, match="parent"):
        build_payload(run, tasks, "data", "hash")


def test_legacy_root_score_identity_is_preserved():
    from eval_framework.observability import stable_id

    run, tasks = fixture([{"name": "task_success", "score": 1.0}])
    spans, scores, traces = build_payload(run, tasks, "data", "hash")
    assert scores[1].id == stable_id(traces[0]["trace_id"], "task_success")
    assert scores[1].observation_id == spans[0].span_id


def test_judge_repeats_keep_both_scores_and_real_generation_calls():
    run, tasks = fixture(
        [
            {
                "name": "action_appropriateness",
                "score": 0.8,
                "scope": "tool",
                "event_id": "tool1",
                "metric_id": "action-tool1",
                "judge_repeat": 1,
            },
            {
                "name": "action_appropriateness",
                "score": 0.9,
                "scope": "tool",
                "event_id": "tool1",
                "metric_id": "action-tool1",
                "judge_repeat": 2,
            },
        ]
    )
    run["trials"][0]["observation"]["events"].append(
        {
            "id": "judge1",
            "parent_id": "tool1",
            "type": "generation",
            "name": "GEval",
            "model": "judge-model",
            "is_judge": True,
            "input": "evaluate evidence",
            "output": "score=8",
            "start_time": "2026-11-01T00:00:04Z",
            "end_time": "2026-11-01T00:00:05Z",
            "usage": {"input_tokens": 20, "output_tokens": 4},
        }
    )
    spans, scores, _ = build_payload(run, tasks, "data", "hash")
    assert scores[1].id != scores[2].id
    assert scores[1].observation_id == scores[2].observation_id == spans[2].span_id
    assert spans[-1].parent_span_id == spans[2].span_id
    attrs = {a.key: a.value.string_value for a in spans[-1].attributes}
    assert json.loads(attrs["langfuse.observation.metadata"])["is_judge"] is True


def test_parent_cycle_cannot_be_published_as_a_valid_trace():
    run, tasks = fixture([])
    run["trials"][0]["observation"]["events"][0]["parent_id"] = "tool1"
    with pytest.raises(ValueError, match="cycle"):
        build_payload(run, tasks, "data", "hash")
